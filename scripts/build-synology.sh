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

[[ -n "$APK" && -f "$APK" ]] || die "APK 경로를 넘겨주세요: scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk"
APK="$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"
for cmd in git jq unzip zip docker openssl; do
    command -v "$cmd" >/dev/null || die "$cmd 명령이 필요합니다"
done
docker buildx version >/dev/null 2>&1 || die "docker buildx가 필요합니다"

echo "==> wrapper-v2 소스 준비 ($WRAPPER_SRC)"
rm -rf "$WRAPPER_SRC"
mkdir -p "$(dirname "$WRAPPER_SRC")"
git clone --depth 1 --branch "${WRAPPER_REF:-main}" https://github.com/glomatico/wrapper-v2 "$WRAPPER_SRC"

echo "==> Apple Music x86_64 라이브러리 추출 및 해시 검증"
# extract-libs.sh can fall back to the first ABI in a universal APK (arm64-v8a),
# so hand it an APK that only contains the x86_64 libraries.
SPLIT="$(mktemp -d)"
trap 'rm -rf "$SPLIT"' EXIT
unzip -q "$APK" 'lib/x86_64/*' -d "$SPLIT/x86_64" || die "APK에 x86_64 라이브러리가 없습니다"
(cd "$SPLIT/x86_64" && zip -qr "$SPLIT/x86_64.apk" lib)
bash "$WRAPPER_SRC/tools/extract-libs.sh" --bundle "$SPLIT/x86_64.apk" --arch x86_64
bash "$WRAPPER_SRC/tools/stage-system.sh" --arch x86_64

echo "==> wrapper 이미지 빌드 (linux/amd64, 첫 빌드는 10분 이상 걸릴 수 있습니다)"
docker buildx build --platform linux/amd64 --load \
    --build-arg TARGET_ARCH=x86_64 --build-arg RUNTIME_PLATFORM=linux/amd64 \
    -t wrapper-v2:x86_64 "$WRAPPER_SRC"

echo "==> 웹 UI 이미지 빌드 (linux/amd64)"
docker buildx build --platform linux/amd64 --load -t papple-music:latest "$ROOT"

echo "==> 이미지 저장 ($OUT)"
mkdir -p "$OUT"
docker save -o "$OUT/papple-music.tar" papple-music:latest
docker save -o "$OUT/wrapper-v2.tar" wrapper-v2:x86_64

PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 20)"
sed "s/GAMDL_WEB_PASSWORD: \"CHANGE-ME\"/GAMDL_WEB_PASSWORD: \"$PASSWORD\"/" \
    "$ROOT/deploy/synology/docker-compose.yml" > "$OUT/docker-compose.yml"
cp "$ROOT/deploy/synology/README.md" "$OUT/README.md"

echo
echo "완료: $OUT"
ls -lh "$OUT"
echo
echo "웹 UI 비밀번호: $PASSWORD   (아이디는 아무거나, docker-compose.yml에도 들어 있습니다)"
echo "wrapper-v2.tar에는 Apple Music 라이브러리가 들어 있으니 공개된 곳에 올리지 마세요."
