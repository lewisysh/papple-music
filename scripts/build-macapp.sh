#!/bin/bash
# build-macapp.sh - Build "Papple Music.app" and a .dmg for macOS (current CPU architecture).
#
# Usage:
#   scripts/build-macapp.sh
#
# Output: dist/macapp/Papple Music.app and dist/Papple-Music-<version>-<arch>.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v uv >/dev/null || { echo "error: uv is required (brew install uv)" >&2; exit 1; }

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
ARCH="$(uname -m)"
DIST="$ROOT/dist/macapp"
DMG="$ROOT/dist/Papple-Music-$VERSION-$ARCH.dmg"

echo "==> Building Papple Music.app ($VERSION, $ARCH)"
rm -rf "$DIST" "$ROOT/build/pyinstaller"
uv run --group app pyinstaller --noconfirm --clean \
    --distpath "$DIST" --workpath "$ROOT/build/pyinstaller" \
    packaging/macos/PappleMusic.spec

APP="$DIST/Papple Music.app"
# Drop the onedir helper folder; only the .app bundle is shipped.
rm -rf "$DIST/Papple Music"

echo "==> Creating $DMG"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -quiet -volname "Papple Music" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

echo
echo "Done:"
du -sh "$APP" "$DMG"
