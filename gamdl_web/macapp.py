"""Entry point of Papple Music.app (macOS).

Runs the web server in a background thread, opens the browser and keeps a menu
bar icon with a few shortcuts. Built into an app bundle by
scripts/build-macapp.sh (PyInstaller); not used by `uv run papple-music`.
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
    "open": "Papple Music 열기" if KO else "Open Papple Music",
    "folder": "다운로드 폴더 열기" if KO else "Open Download Folder",
    "login": "로그인 시 자동 실행" if KO else "Open at Login",
    "starting": "시작하는 중…" if KO else "Starting…",
    "running": "실행 중 · 127.0.0.1:{port}" if KO else "Running · 127.0.0.1:{port}",
    "failed": "시작하지 못했습니다" if KO else "Couldn't start",
    "quit": "종료" if KO else "Quit Papple Music",
}


def _resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "packaging/macos"))
    return base / name


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

    import rumps

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

    class PappleApp(rumps.App):
        def __init__(self) -> None:
            icon = _resource("menubar.png")
            super().__init__("Papple Music", icon=str(icon) if icon.exists() else None, template=True, quit_button=None)
            self.status = rumps.MenuItem(TEXT["starting"])
            self.login = rumps.MenuItem(TEXT["login"], callback=self.toggle_login)
            self.login.state = LAUNCH_AGENT.exists()
            self.menu = [
                rumps.MenuItem(TEXT["open"], callback=self.open_ui),
                rumps.MenuItem(TEXT["folder"], callback=self.open_folder),
                None,
                self.status,
                self.login,
                None,
                rumps.MenuItem(TEXT["quit"], callback=self.quit_app),
            ]
            self.opened = background
            self.timer = rumps.Timer(self.watch, 0.5)
            self.timer.start()

        def watch(self, _timer) -> None:
            if server.started:
                self.status.title = TEXT["running"].format(port=port)
                if not self.opened:
                    self.opened = True
                    webbrowser.open(url)
                self.timer.interval = 5
            elif not thread.is_alive():
                self.status.title = TEXT["failed"]

        def open_ui(self, _item) -> None:
            webbrowser.open(url)

        def open_folder(self, _item) -> None:
            folder = Path(SettingsStore().get().output_path).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(folder)], check=False)

        def toggle_login(self, item) -> None:
            _set_login_item(not item.state)
            item.state = LAUNCH_AGENT.exists()

        def quit_app(self, _item) -> None:
            server.should_exit = True
            thread.join(timeout=5)
            rumps.quit_application()

    PappleApp().run()
    # Give the server a moment to close sockets if the menu bar loop ends another way.
    server.should_exit = True
    time.sleep(0.2)


if __name__ == "__main__":
    main()
