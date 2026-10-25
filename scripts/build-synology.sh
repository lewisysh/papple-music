#!/bin/bash
# build-synology.sh - Build x86_64 (linux/amd64) images for Synology / any x86 NAS.
#
# Usage:
#   scripts/build-synology.sh <path-to-apple-music.apk|.apkm>
#
# Produces dist/synology/ with:
#   papple-music.tar           web UI image   (papple-music:latest)
#   wrapper-v2.tar             wrapper image  (wrapper-v2:x86_64, contains the
#                              Apple Music libraries from YOUR apk - keep it private)
#   docker-compose.yml         ready to use, with a freshly generated web password
#
# The wrapper is built in build/wrapper-x86_64 so the local wrapper in vendor/
# (which may be staged for arm64) is left alone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK="${1:-}"
WRAPPER_SRC="$ROOT/build/wrapper-x86_64"
OUT="$ROOT/dist/synology"

die() { echo "error: $*" >&2; exit 1; }

[[ -n "$APK" && -f "$APK" ]] || die "pass the APK path: scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk"
APK="$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"
for cmd in git jq unzip zip docker openssl; do
    command -v "$cmd" >/dev/null || die "$cmd is required"
done
docker buildx version >/dev/null 2>&1 || die "docker buildx is required"

echo "==> Preparing wrapper-v2 source ($WRAPPER_SRC)"
rm -rf "$WRAPPER_SRC"
mkdir -p "$(dirname "$WRAPPER_SRC")"
git clone --depth 1 --branch "${WRAPPER_REF:-main}" https://github.com/glomatico/wrapper-v2 "$WRAPPER_SRC"

echo "==> Extracting and verifying the Apple Music x86_64 libraries"
# extract-libs.sh can fall back to the first ABI in a universal APK (arm64-v8a),
# so hand it an APK that only contains the x86_64 libraries.
SPLIT="$(mktemp -d)"
trap 'rm -rf "$SPLIT"' EXIT
unzip -q "$APK" 'lib/x86_64/*' -d "$SPLIT/x86_64" || die "the APK has no x86_64 libraries"
(cd "$SPLIT/x86_64" && zip -qr "$SPLIT/x86_64.apk" lib)
bash "$WRAPPER_SRC/tools/extract-libs.sh" --bundle "$SPLIT/x86_64.apk" --arch x86_64
bash "$WRAPPER_SRC/tools/stage-system.sh" --arch x86_64

echo "==> Building the wrapper image (linux/amd64; the first build can take 10+ minutes)"
docker buildx build --platform linux/amd64 --load \
    --build-arg TARGET_ARCH=x86_64 --build-arg RUNTIME_PLATFORM=linux/amd64 \
    -t wrapper-v2:x86_64 "$WRAPPER_SRC"

echo "==> Building the web UI image (linux/amd64)"
docker buildx build --platform linux/amd64 --load -t papple-music:latest "$ROOT"

echo "==> Saving images ($OUT)"
mkdir -p "$OUT"
docker save -o "$OUT/papple-music.tar" papple-music:latest
docker save -o "$OUT/wrapper-v2.tar" wrapper-v2:x86_64

PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 20)"
sed "s/GAMDL_WEB_PASSWORD: \"CHANGE-ME\"/GAMDL_WEB_PASSWORD: \"$PASSWORD\"/" \
    "$ROOT/deploy/synology/docker-compose.yml" > "$OUT/docker-compose.yml"
cp "$ROOT/deploy/synology/README.md" "$OUT/README.md"

echo
echo "Done: $OUT"
ls -lh "$OUT"
echo
echo "Web UI password: $PASSWORD   (any username; it is also in docker-compose.yml)"
echo "wrapper-v2.tar contains Apple Music libraries - never upload it anywhere public."
