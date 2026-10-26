"""Papple Music: a web GUI for gamdl."""

import importlib.metadata
import re
from pathlib import Path


def _version() -> str:
    # A source checkout (or the Mac app, which bundles pyproject.toml) reads the
    # project file, so the version is right without reinstalling the package.
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        match = re.search(r'^version = "([^"]+)"', pyproject.read_text(), re.M)
        if match:
            return match.group(1)
    try:
        return importlib.metadata.version("papple-music")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


__version__ = _version()
