# PyInstaller spec for Papple Music.app — built by scripts/build-macapp.sh.
# -*- mode: python ; coding: utf-8 -*-
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

datas = [
    (str(ROOT / "gamdl_web/static"), "gamdl_web/static"),
]
binaries = []
hiddenimports = ["gamdl_web.app", "uvicorn.lifespan.on", "uvicorn.protocols.http.h11_impl", "uvicorn.loops.asyncio"]
for package in ("gamdl", "pywidevine", "pyplayready", "imageio_ffmpeg", "uvicorn", "structlog"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging/macos/launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyInstaller"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Papple Music",
    console=False,
    argv_emulation=False,
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Papple Music")
app = BUNDLE(
    coll,
    name="Papple Music.app",
    icon=str(ROOT / "packaging/macos/AppIcon.icns"),
    bundle_identifier="com.lewisysh.papplemusic",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "Papple Music",
        "CFBundleShortVersionString": VERSION,
        "LSMinimumSystemVersion": "12.0",
        # Lets the web view (and navigator.language) follow a Korean or English system.
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": ["en", "ko"],
        "NSHumanReadableCopyright": "MIT License",
        "NSHighResolutionCapable": True,
    },
)
