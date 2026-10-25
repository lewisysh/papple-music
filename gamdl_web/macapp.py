"""Entry point of Papple Music.app (macOS).

A regular Mac app: it runs the web server in a background thread and shows the
UI in its own window (WKWebView). Closing the window keeps the app running like
the Music app; clicking the Dock icon brings it back, and quitting (⌘Q) stops
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
T = {
    "about": ("Papple Music에 관하여", "About Papple Music"),
    "folder": ("다운로드 폴더 열기", "Open Download Folder"),
    "browser": ("브라우저에서 열기", "Open in Browser"),
    "login": ("로그인 시 자동 실행", "Open at Login"),
    "hide": ("Papple Music 가리기", "Hide Papple Music"),
    "hide_others": ("기타 가리기", "Hide Others"),
    "show_all": ("모두 보기", "Show All"),
    "quit": ("Papple Music 종료", "Quit Papple Music"),
    "edit": ("편집", "Edit"),
    "undo": ("실행 취소", "Undo"),
    "redo": ("실행 복귀", "Redo"),
    "cut": ("오려두기", "Cut"),
    "copy": ("복사하기", "Copy"),
    "paste": ("붙여넣기", "Paste"),
    "select_all": ("전체 선택", "Select All"),
    "view": ("보기", "View"),
    "back": ("뒤로", "Back"),
    "forward": ("앞으로", "Forward"),
    "reload": ("새로고침", "Reload"),
    "actual": ("실제 크기", "Actual Size"),
    "zoom_in": ("확대", "Zoom In"),
    "zoom_out": ("축소", "Zoom Out"),
    "fullscreen": ("전체 화면 시작", "Enter Full Screen"),
    "window": ("윈도우", "Window"),
    "minimize": ("최소화", "Minimize"),
    "zoom": ("확대/축소", "Zoom"),
    "close": ("닫기", "Close"),
    "main_window": ("Papple Music", "Papple Music"),
    "ok": ("확인", "OK"),
    "cancel": ("취소", "Cancel"),
    "port_busy": ("포트 {port}을(를) 다른 프로그램이 쓰고 있어 시작할 수 없습니다.", "Port {port} is used by another program, so Papple Music can't start."),
    "loading": ("Papple Music을 시작하는 중…", "Starting Papple Music…"),
}


def tr(key: str) -> str:
    ko, en = T[key]
    return ko if KO else en


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


def _unique(path: Path) -> Path:
    stem, suffix, n = path.stem, path.suffix, 2
    while path.exists():
        path = path.with_name(f"{stem} {n}{suffix}")
        n += 1
    return path


LOADING_HTML = """<!doctype html><meta charset="utf-8"><style>
html,body{height:100%;margin:0;font:13px -apple-system,sans-serif;display:grid;place-items:center;
background:#f5f5f7;color:#6e6e73}@media (prefers-color-scheme:dark){html,body{background:#1c1c1e;color:#98989d}}
div{display:flex;flex-direction:column;align-items:center;gap:14px}
i{width:22px;height:22px;border-radius:50%;border:2.5px solid #8884;border-top-color:#fa2d48;animation:s .8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}</style><div><i></i>{text}</div>"""


def main() -> None:
    multiprocessing.freeze_support()

    from AppKit import (
        NSAlert,
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSBackingStoreBuffered,
        NSMenu,
        NSMenuItem,
        NSOpenPanel,
        NSTerminateNow,
        NSWindow,
        NSWorkspace,
    )
    from Foundation import NSURL, NSMakeRect, NSObject, NSURLRequest
    from WebKit import WKWebView, WKWebViewConfiguration

    from .config import DATA_DIR, SettingsStore

    port = int(os.environ.get("GAMDL_WEB_PORT", 8765))
    url = f"http://127.0.0.1:{port}"
    background = "--background" in sys.argv

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(DATA_DIR / "app.log", "a", buffering=1)  # noqa: SIM115 - lives as long as the app
    sys.stdout = sys.stderr = log
    _use_bundled_ffmpeg(DATA_DIR)

    # Reuse a server that is already running (e.g. `uv run papple-music`).
    server = thread = None
    external = _port_open(port)
    if external and not _is_papple(port):
        NSApplication.sharedApplication()
        alert = NSAlert.alloc().init()
        alert.setMessageText_(tr("port_busy").format(port=port))
        alert.runModal()
        return
    if not external:
        import uvicorn

        from .app import app as web_app

        server = uvicorn.Server(uvicorn.Config(web_app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, name="server", daemon=True)
        thread.start()

    def open_external(ns_url) -> None:
        NSWorkspace.sharedWorkspace().openURL_(ns_url)

    # PyObjC knows the WebKit delegate signatures (incl. completion blocks) from
    # its metadata, so the delegate just implements the methods it needs.
    class Delegate(NSObject):
        # ---- app lifecycle
        def applicationDidFinishLaunching_(self, _note) -> None:
            if not background:
                self.showWindow_(None)
            threading.Thread(target=self.waitForServer, daemon=True).start()

        def waitForServer(self) -> None:
            for _ in range(600):
                if server is None or server.started:
                    self.performSelectorOnMainThread_withObject_waitUntilDone_("serverReady:", None, False)
                    return
                if thread is not None and not thread.is_alive():
                    return
                time.sleep(0.1)

        def serverReady_(self, _obj) -> None:
            self.ready = True
            self.webView.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))

        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible) -> bool:
            self.showWindow_(None)
            return True

        def applicationDockMenu_(self, _app):
            return self.dockMenu

        def applicationShouldTerminate_(self, _app) -> int:
            if server is not None:
                server.should_exit = True
                thread.join(timeout=5)
            return NSTerminateNow

        # ---- menu actions
        def showWindow_(self, _sender) -> None:
            self.window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        def openFolder_(self, _sender) -> None:
            folder = Path(SettingsStore().get().output_path).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(folder)], check=False)

        def openInBrowser_(self, _sender) -> None:
            current = self.webView.URL()
            open_external(current if current and current.host() else NSURL.URLWithString_(url))

        def toggleLogin_(self, _sender) -> None:
            _set_login_item(not LAUNCH_AGENT.exists())
            for item in self.loginItems:
                item.setState_(1 if LAUNCH_AGENT.exists() else 0)

        def reloadPage_(self, _sender) -> None:
            self.webView.reload()

        def goBack_(self, _sender) -> None:
            self.webView.goBack()

        def goForward_(self, _sender) -> None:
            self.webView.goForward()

        def zoomIn_(self, _sender) -> None:
            self.webView.setPageZoom_(min(2.0, self.webView.pageZoom() + 0.1))

        def zoomOut_(self, _sender) -> None:
            self.webView.setPageZoom_(max(0.5, self.webView.pageZoom() - 0.1))

        def actualSize_(self, _sender) -> None:
            self.webView.setPageZoom_(1.0)

        # ---- window title follows the page title
        def observeValueForKeyPath_ofObject_change_context_(self, _path, _obj, _change, _ctx) -> None:
            self.window.setTitle_(self.webView.title() or "Papple Music")

        # ---- WKUIDelegate: new windows, JS dialogs, file pickers
        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, _wv, _cfg, action, _features):
            target = action.request().URL()
            if target is not None:
                open_external(target)
            return None

        def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(self, _wv, message, _frame, handler):
            alert = NSAlert.alloc().init()
            alert.setMessageText_(message)
            alert.runModal()
            handler()

        def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(self, _wv, message, _frame, handler):
            alert = NSAlert.alloc().init()
            alert.setMessageText_(message)
            alert.addButtonWithTitle_(tr("ok"))
            alert.addButtonWithTitle_(tr("cancel"))
            handler(alert.runModal() == 1000)  # NSAlertFirstButtonReturn

        def webView_runOpenPanelWithParameters_initiatedByFrame_completionHandler_(self, _wv, params, _frame, handler):
            panel = NSOpenPanel.openPanel()
            panel.setAllowsMultipleSelection_(params.allowsMultipleSelection())
            panel.setCanChooseDirectories_(False)
            handler(panel.URLs() if panel.runModal() == 1 else None)

        # ---- WKNavigationDelegate: keep the app in the window, send the rest out
        def webView_decidePolicyForNavigationAction_decisionHandler_(self, _wv, action, handler):
            target = action.request().URL()
            host = target.host() if target is not None else None
            if action.shouldPerformDownload():
                handler(2)  # WKNavigationActionPolicyDownload
            elif host and host not in {"127.0.0.1", "localhost"} and target.scheme() in {"http", "https"}:
                open_external(target)
                handler(0)  # cancel
            else:
                handler(1)  # allow

        def webView_decidePolicyForNavigationResponse_decisionHandler_(self, _wv, response, handler):
            headers = response.response().allHeaderFields() if hasattr(response.response(), "allHeaderFields") else {}
            disposition = str(headers.get("Content-Disposition") or headers.get("content-disposition") or "")
            download = not response.canShowMIMEType() or disposition.lower().startswith("attachment")
            handler(2 if download else 1)

        def webView_navigationAction_didBecomeDownload_(self, _wv, _action, download):
            download.setDelegate_(self)

        def webView_navigationResponse_didBecomeDownload_(self, _wv, _response, download):
            download.setDelegate_(self)

        # ---- WKDownloadDelegate: save to ~/Downloads
        def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(self, _dl, _resp, filename, handler):
            target = _unique(Path.home() / "Downloads" / (filename or "download"))
            self.lastDownload = target
            handler(NSURL.fileURLWithPath_(str(target)))

        def downloadDidFinish_(self, _dl) -> None:
            target = getattr(self, "lastDownload", None)
            if target is not None:
                NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([NSURL.fileURLWithPath_(str(target))])

    def item(title: str, action: str | None, key: str = "", target=None, mods: int | None = None) -> NSMenuItem:
        menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            menu_item.setTarget_(target)
        if mods is not None:
            menu_item.setKeyEquivalentModifierMask_(mods)
        return menu_item

    def submenu(main: NSMenu, title: str, items: list) -> NSMenu:
        menu = NSMenu.alloc().initWithTitle_(title)
        for entry in items:
            menu.addItem_(entry if entry is not None else NSMenuItem.separatorItem())
        holder = NSMenuItem.alloc().init()
        holder.setSubmenu_(menu)
        main.addItem_(holder)
        return menu

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = Delegate.alloc().init()
    delegate.ready = False
    delegate.loginItems = []

    # ---- window with the web UI
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, 1280, 820), 1 | 2 | 4 | 8, NSBackingStoreBuffered, False
    )  # titled | closable | miniaturizable | resizable
    window.setTitle_("Papple Music")
    window.setMinSize_((760, 520))
    window.setReleasedWhenClosed_(False)
    window.setTabbingMode_(2)  # NSWindowTabbingModeDisallowed
    if not window.setFrameUsingName_("PappleMusicMain"):
        window.center()
    window.setFrameAutosaveName_("PappleMusicMain")

    config = WKWebViewConfiguration.alloc().init()
    config.setMediaTypesRequiringUserActionForPlayback_(0)  # let the player start without a click
    config.setApplicationNameForUserAgent_("Version/18.0 Safari/605.1.15 PappleMusicApp")
    config.preferences().setElementFullscreenEnabled_(True)
    web = WKWebView.alloc().initWithFrame_configuration_(window.contentView().bounds(), config)
    web.setAutoresizingMask_(2 | 16)  # width | height sizable
    web.setAllowsBackForwardNavigationGestures_(True)
    web.setUIDelegate_(delegate)
    web.setNavigationDelegate_(delegate)
    web.loadHTMLString_baseURL_(LOADING_HTML.replace("{text}", tr("loading")), None)
    web.addObserver_forKeyPath_options_context_(delegate, "title", 1, None)
    window.setContentView_(web)
    delegate.window = window
    delegate.webView = web

    # ---- menus
    def login_item() -> NSMenuItem:
        entry = item(tr("login"), "toggleLogin:", "", delegate)
        entry.setState_(1 if LAUNCH_AGENT.exists() else 0)
        delegate.loginItems.append(entry)
        return entry

    main_menu = NSMenu.alloc().init()
    cmd, shift, opt, ctrl = 1 << 20, 1 << 17, 1 << 19, 1 << 18
    submenu(main_menu, "Papple Music", [
        item(tr("about"), "orderFrontStandardAboutPanel:"),
        None,
        item(tr("folder"), "openFolder:", "", delegate),
        item(tr("browser"), "openInBrowser:", "", delegate),
        login_item(),
        None,
        item(tr("hide"), "hide:", "h"),
        item(tr("hide_others"), "hideOtherApplications:", "h", None, cmd | opt),
        item(tr("show_all"), "unhideAllApplications:"),
        None,
        item(tr("quit"), "terminate:", "q"),
    ])
    submenu(main_menu, tr("edit"), [
        item(tr("undo"), "undo:", "z"),
        item(tr("redo"), "redo:", "z", None, cmd | shift),
        None,
        item(tr("cut"), "cut:", "x"),
        item(tr("copy"), "copy:", "c"),
        item(tr("paste"), "paste:", "v"),
        item(tr("select_all"), "selectAll:", "a"),
    ])
    submenu(main_menu, tr("view"), [
        item(tr("back"), "goBack:", "[", delegate),
        item(tr("forward"), "goForward:", "]", delegate),
        item(tr("reload"), "reloadPage:", "r", delegate),
        None,
        item(tr("actual"), "actualSize:", "0", delegate),
        item(tr("zoom_in"), "zoomIn:", "+", delegate),
        item(tr("zoom_out"), "zoomOut:", "-", delegate),
        None,
        item(tr("fullscreen"), "toggleFullScreen:", "f", None, cmd | ctrl),
    ])
    window_menu = submenu(main_menu, tr("window"), [
        item(tr("minimize"), "performMiniaturize:", "m"),
        item(tr("zoom"), "performZoom:"),
        item(tr("close"), "performClose:", "w"),
        None,
        item(tr("main_window"), "showWindow:", "1", delegate),
    ])
    app.setMainMenu_(main_menu)
    app.setWindowsMenu_(window_menu)

    # Right-click menu on the Dock icon (Quit is added by macOS).
    dock_menu = NSMenu.alloc().init()
    dock_menu.addItem_(item(tr("folder"), "openFolder:", "", delegate))
    dock_menu.addItem_(item(tr("browser"), "openInBrowser:", "", delegate))
    dock_menu.addItem_(login_item())
    delegate.dockMenu = dock_menu

    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
