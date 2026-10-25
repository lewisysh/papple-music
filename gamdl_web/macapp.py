"""Entry point of Papple Music.app (macOS).

A regular Dock app without windows: it runs the web server in a background
thread and opens the UI in the browser. Clicking the Dock icon opens the UI
again, the Dock and app menus have a few shortcuts, and quitting (⌘Q) stops
the server. Built into an app bundle by scripts/build-macapp.sh (PyInstaller);
not used by `uv run papple-music`.
"""

from __future__ import annotations

import multiprocessing
import os
import plistlib
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_ID = "com.lewisysh.papplemusic"
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents" / f"{APP_ID}.plist"


def _korean() -> bool:
    try:
        from Foundation import NSLocale

        return str(NSLocale.preferredLanguages()[0]).startswith("ko")
    except Exception:
        return os.environ.get("LANG", "").startswith("ko")


KO = _korean()
TEXT = {
    "about": "Papple Music에 관하여" if KO else "About Papple Music",
    "open": "Papple Music 열기" if KO else "Open Papple Music",
    "folder": "다운로드 폴더 열기" if KO else "Open Download Folder",
    "login": "로그인 시 자동 실행" if KO else "Open at Login",
    "hide": "Papple Music 가리기" if KO else "Hide Papple Music",
    "quit": "Papple Music 종료" if KO else "Quit Papple Music",
}


def _use_bundled_ffmpeg(data_dir: Path) -> None:
    """Apps started from Finder don't see Homebrew's PATH, so expose the bundled
    ffmpeg as plain `ffmpeg` for gamdl and the converters."""
    try:
        import imageio_ffmpeg

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return
    bindir = data_dir / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir / "ffmpeg"
    if not link.exists() or link.resolve() != exe.resolve():
        link.unlink(missing_ok=True)
        link.symlink_to(exe)
    extra = [str(bindir), "/opt/homebrew/bin", "/usr/local/bin"]
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "/usr/bin:/bin")])


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _is_papple(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _app_path() -> Path:
    # .../Papple Music.app/Contents/MacOS/Papple Music
    return Path(sys.executable).resolve().parents[2]


def _set_login_item(enabled: bool) -> None:
    if enabled:
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        with LAUNCH_AGENT.open("wb") as f:
            plistlib.dump(
                {
                    "Label": APP_ID,
                    "ProgramArguments": ["/usr/bin/open", "-a", str(_app_path()), "--args", "--background"],
                    "RunAtLoad": True,
                },
                f,
            )
    else:
        LAUNCH_AGENT.unlink(missing_ok=True)


def main() -> None:
    multiprocessing.freeze_support()

    from AppKit import (
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSMenu,
        NSMenuItem,
        NSTerminateNow,
    )
    from Foundation import NSObject

    from .config import DATA_DIR, SettingsStore

    port = int(os.environ.get("GAMDL_WEB_PORT", 8765))
    url = f"http://127.0.0.1:{port}"
    background = "--background" in sys.argv

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(DATA_DIR / "app.log", "a", buffering=1)  # noqa: SIM115 - lives as long as the app
    sys.stdout = sys.stderr = log
    _use_bundled_ffmpeg(DATA_DIR)

    # Already running (this app or `uv run papple-music`): just show it.
    if _port_open(port) and _is_papple(port):
        if not background:
            webbrowser.open(url)
        return

    import uvicorn

    from .app import app as web_app

    server = uvicorn.Server(uvicorn.Config(web_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()

    def open_when_ready() -> None:
        for _ in range(600):
            if server.started:
                webbrowser.open(url)
                return
            if not thread.is_alive():
                return
            time.sleep(0.1)

    class Delegate(NSObject):
        def applicationDidFinishLaunching_(self, _note) -> None:
            if not background:
                threading.Thread(target=open_when_ready, daemon=True).start()

        # Clicking the Dock icon of the running app opens the UI again.
        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible) -> bool:
            webbrowser.open(url)
            return True

        def applicationDockMenu_(self, _app):
            return self.dockMenu

        def applicationShouldTerminate_(self, _app) -> int:
            server.should_exit = True
            thread.join(timeout=5)
            return NSTerminateNow

        def openUI_(self, _sender) -> None:
            webbrowser.open(url)

        def openFolder_(self, _sender) -> None:
            folder = Path(SettingsStore().get().output_path).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(folder)], check=False)

        def toggleLogin_(self, sender) -> None:
            _set_login_item(not LAUNCH_AGENT.exists())
            for item in self.loginItems:
                item.setState_(1 if LAUNCH_AGENT.exists() else 0)

    def item(title: str, action: str | None, key: str = "", target=None) -> NSMenuItem:
        menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            menu_item.setTarget_(target)
        return menu_item

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = Delegate.alloc().init()
    delegate.loginItems = []

    def shortcuts(menu: NSMenu, with_keys: bool) -> None:
        menu.addItem_(item(TEXT["open"], "openUI:", "o" if with_keys else "", delegate))
        menu.addItem_(item(TEXT["folder"], "openFolder:", "", delegate))
        login = item(TEXT["login"], "toggleLogin:", "", delegate)
        login.setState_(1 if LAUNCH_AGENT.exists() else 0)
        delegate.loginItems.append(login)
        menu.addItem_(login)

    # App menu (the bold "Papple Music" menu next to the Apple menu).
    app_menu = NSMenu.alloc().initWithTitle_("Papple Music")
    app_menu.addItem_(item(TEXT["about"], "orderFrontStandardAboutPanel:"))
    app_menu.addItem_(NSMenuItem.separatorItem())
    shortcuts(app_menu, with_keys=True)
    app_menu.addItem_(NSMenuItem.separatorItem())
    app_menu.addItem_(item(TEXT["hide"], "hide:", "h"))
    app_menu.addItem_(item(TEXT["quit"], "terminate:", "q"))
    app_menu_item = NSMenuItem.alloc().init()
    app_menu_item.setSubmenu_(app_menu)
    main_menu = NSMenu.alloc().init()
    main_menu.addItem_(app_menu_item)
    app.setMainMenu_(main_menu)

    # Right-click menu on the Dock icon (Quit is added by macOS).
    dock_menu = NSMenu.alloc().init()
    shortcuts(dock_menu, with_keys=False)
    delegate.dockMenu = dock_menu

    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
