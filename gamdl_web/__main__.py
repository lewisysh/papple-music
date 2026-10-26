import argparse
import os
import threading
import webbrowser

import uvicorn


def main() -> None:
    from .config import DEFAULT_PORT

    parser = argparse.ArgumentParser(prog="papple-music", description="Papple Music: web GUI for gamdl")
    parser.add_argument("--host", default=os.environ.get("GAMDL_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GAMDL_WEB_PORT", DEFAULT_PORT)))
    parser.add_argument("--open", action="store_true", help="open the browser after start")
    args = parser.parse_args()

    # On a NAS the container runs as root; a umask like 000 keeps downloads
    # editable from file sharing (SMB / File Station).
    if umask := os.environ.get("GAMDL_WEB_UMASK"):
        os.umask(int(umask, 8))

    # Anyone who can reach the settings API can point ffmpeg at any program, so an
    # exposed server needs a password. Docker sets GAMDL_WEB_ALLOW_NO_PASSWORD
    # because its port is only published on the host's loopback address.
    if (
        args.host not in {"127.0.0.1", "localhost", "::1"}
        and not os.environ.get("GAMDL_WEB_PASSWORD")
        and os.environ.get("GAMDL_WEB_ALLOW_NO_PASSWORD") != "1"
    ):
        raise SystemExit(
            "error: set a password with the GAMDL_WEB_PASSWORD environment variable to listen on a public address."
        )

    if args.open:
        url = f"http://{'127.0.0.1' if args.host in {'0.0.0.0', '::'} else args.host}:{args.port}"
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()

    uvicorn.run("gamdl_web.app:app", host=args.host, port=args.port, log_level="warning")


# The guard matters: gamdl downloads through multiprocessing, and macOS spawns
# child processes by re-importing this module.
if __name__ == "__main__":
    main()
