#!/bin/bash
# setup-wrapper.sh - Build and start the wrapper-v2 container for Papple Music.
#
# Usage:
#   scripts/setup-wrapper.sh <path-to-apple-music.apk|.apkm>
#
# Steps: clone/update wrapper-v2 into vendor/, extract + verify the Apple Music
# native libraries from the APK, stage the Android system files, then build and
# start the "wrapper" service from this project's compose.yaml.
#
# Environment:
#   WRAPPER_REF     git ref of glomatico/wrapper-v2 to build (default: main)
#   WRAPPER_ARCH    x86_64 or arm64-v8a (default: detected from this machine)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor/wrapper-v2"
APK="${1:-}"

die() { echo "error: $*" >&2; exit 1; }

[[ -n "$APK" ]] || die "pass the APK path: scripts/setup-wrapper.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk"
[[ -f "$APK" ]] || die "file not found: $APK"
APK="$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"

for cmd in git jq unzip docker; do
    command -v "$cmd" >/dev/null || die "$cmd is required"
done
docker info >/dev/null 2>&1 || die "the Docker daemon is not running (start OrbStack or Docker Desktop)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is required"

if [[ -z "${WRAPPER_ARCH:-}" ]]; then
    case "$(uname -m)" in
        arm64|aarch64) WRAPPER_ARCH=arm64-v8a ;;
        x86_64|amd64)  WRAPPER_ARCH=x86_64 ;;
        *) die "unsupported architecture: $(uname -m)" ;;
    esac
fi
case "$WRAPPER_ARCH" in
    arm64-v8a) RUNTIME_PLATFORM=linux/arm64 ;;
    x86_64)    RUNTIME_PLATFORM=linux/amd64 ;;
    *) die "WRAPPER_ARCH must be x86_64 or arm64-v8a" ;;
esac

echo "==> Preparing wrapper-v2 source ($VENDOR)"
if [[ -d "$VENDOR/.git" ]]; then
    git -C "$VENDOR" fetch --depth 1 origin "${WRAPPER_REF:-main}"
    git -C "$VENDOR" checkout -q FETCH_HEAD
else
    mkdir -p "$(dirname "$VENDOR")"
    git clone --depth 1 --branch "${WRAPPER_REF:-main}" https://github.com/glomatico/wrapper-v2 "$VENDOR"
fi

echo "==> Extracting and verifying the Apple Music libraries ($WRAPPER_ARCH)"
# Clear libraries staged for another arch; keep the tracked .gitkeep files.
find "$VENDOR/rootfs/system/lib64" "$VENDOR/rootfs/system/bin" -mindepth 1 ! -name .gitkeep -delete
rm -rf "$VENDOR/rootfs/system/usr"
bash "$VENDOR/tools/extract-libs.sh" --bundle "$APK" --arch "$WRAPPER_ARCH"
bash "$VENDOR/tools/stage-system.sh" --arch "$WRAPPER_ARCH"

echo "==> Building and starting the Docker image (the first build downloads the NDK and can take 10+ minutes)"
cd "$ROOT"
mkdir -p data/wrapper
export TARGET_ARCH="$WRAPPER_ARCH" RUNTIME_PLATFORM
docker compose up -d --build wrapper

echo "==> Waiting for the wrapper"
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${WRAPPER_HTTP_PORT:-8080}/health" >/dev/null 2>&1; then
        curl -fsS "http://127.0.0.1:${WRAPPER_HTTP_PORT:-8080}/health"; echo
        echo "Done! Sign in with your Apple ID on the Wrapper tab in Papple Music."
        exit 0
    fi
    sleep 2
done
echo "The wrapper is not responding yet. Check the log: docker compose logs wrapper" >&2
exit 1
