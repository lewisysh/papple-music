#!/bin/bash
# build-synology.sh - Build x86_64 (linux/amd64) images for Synology / any x86 NAS.
#
# Usage:
#   scripts/build-synology.sh [path-to-apple-music.apk|.apkm]
#
# Produces one file, dist/synology/papple-music-<version>-synology.zip, holding:
#   papple-music-<version>-images.tar   both images in one archive: the web UI
#                                       (papple-music:<version> and :latest) and the
#                                       wrapper (wrapper-v2:x86_64, which contains the
#                                       Apple Music libraries from YOUR apk - keep it private)
#   docker-compose.yml                  ready to use; keeps the web password of an
#                                       earlier build, otherwise generates one
#   README.md                           setup steps
# The same files are left unzipped next to it.
#
# The APK is only needed the first time: an existing wrapper-v2:x86_64 image is
# reused unless REBUILD_WRAPPER=1. The wrapper is built in build/wrapper-x86_64
# so the local wrapper in vendor/ (which may be staged for arm64) is left alone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK="${1:-}"
WRAPPER_SRC="$ROOT/build/wrapper-x86_64"
OUT="$ROOT/dist/synology"

die() { echo "error: $*" >&2; exit 1; }

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
for cmd in docker openssl; do
    command -v "$cmd" >/dev/null || die "$cmd is required"
done
docker buildx version >/dev/null 2>&1 || die "docker buildx is required"

if [[ "${REBUILD_WRAPPER:-0}" != 1 ]] && docker image inspect wrapper-v2:x86_64 >/dev/null 2>&1; then
    echo "==> Reusing the existing wrapper-v2:x86_64 image (REBUILD_WRAPPER=1 to rebuild)"
else
    [[ -n "$APK" && -f "$APK" ]] || die "pass the APK path: scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk"
    APK="$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"
    for cmd in git jq unzip zip; do
        command -v "$cmd" >/dev/null || die "$cmd is required"
    done

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
fi

echo "==> Building the web UI image $VERSION (linux/amd64)"
docker buildx build --platform linux/amd64 --load --build-arg VERSION="$VERSION" \
    -t "papple-music:$VERSION" -t papple-music:latest "$ROOT"

NAME="papple-music-$VERSION-synology"
BUNDLE="$OUT/$NAME"
mkdir -p "$OUT"
# Keep the web password of an earlier build so a redeploy doesn't change it.
PASSWORD="$(cat "$OUT"/docker-compose.yml "$OUT"/*/docker-compose.yml 2>/dev/null \
    | sed -n 's/.*GAMDL_WEB_PASSWORD: "\([A-Za-z0-9]*\)".*/\1/p' | grep -v '^CHANGE' | head -1 || true)"
[[ -n "$PASSWORD" ]] || PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 20)"
rm -rf "$OUT"/*.tar "$OUT"/*.zip "$OUT"/docker-compose.yml "$OUT"/README.md "$OUT"/papple-music-*-synology
mkdir -p "$BUNDLE"

echo "==> Saving both images into one archive"
docker save -o "$BUNDLE/papple-music-$VERSION-images.tar" \
    "papple-music:$VERSION" papple-music:latest wrapper-v2:x86_64
sed "s/GAMDL_WEB_PASSWORD: \"CHANGE-ME\"/GAMDL_WEB_PASSWORD: \"$PASSWORD\"/" \
    "$ROOT/deploy/synology/docker-compose.yml" > "$BUNDLE/docker-compose.yml"
cp "$ROOT/deploy/synology/README.md" "$BUNDLE/README.md"

echo "==> Zipping $NAME.zip"
(cd "$OUT" && zip -q -r -X "$NAME.zip" "$NAME")

echo
echo "Done: $OUT/$NAME.zip"
ls -lh "$OUT/$NAME.zip"
echo
echo "Web UI password: $PASSWORD   (any username; it is also in docker-compose.yml)"
echo "The zip contains the wrapper image with Apple Music libraries - never upload it anywhere public."
