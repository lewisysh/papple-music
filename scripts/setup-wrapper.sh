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

[[ -n "$APK" ]] || die "APK 경로를 넘겨주세요: scripts/setup-wrapper.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk"
[[ -f "$APK" ]] || die "파일이 없습니다: $APK"
APK="$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK")"

for cmd in git jq unzip docker; do
    command -v "$cmd" >/dev/null || die "$cmd 명령이 필요합니다"
done
docker info >/dev/null 2>&1 || die "Docker 데몬이 실행 중이 아닙니다 (OrbStack 또는 Docker Desktop을 켜세요)"
docker compose version >/dev/null 2>&1 || die "docker compose 플러그인이 필요합니다"

if [[ -z "${WRAPPER_ARCH:-}" ]]; then
    case "$(uname -m)" in
        arm64|aarch64) WRAPPER_ARCH=arm64-v8a ;;
        x86_64|amd64)  WRAPPER_ARCH=x86_64 ;;
        *) die "지원하지 않는 아키텍처: $(uname -m)" ;;
    esac
fi
case "$WRAPPER_ARCH" in
    arm64-v8a) RUNTIME_PLATFORM=linux/arm64 ;;
    x86_64)    RUNTIME_PLATFORM=linux/amd64 ;;
    *) die "WRAPPER_ARCH는 x86_64 또는 arm64-v8a" ;;
esac

echo "==> wrapper-v2 소스 준비 ($VENDOR)"
if [[ -d "$VENDOR/.git" ]]; then
    git -C "$VENDOR" fetch --depth 1 origin "${WRAPPER_REF:-main}"
    git -C "$VENDOR" checkout -q FETCH_HEAD
else
    mkdir -p "$(dirname "$VENDOR")"
    git clone --depth 1 --branch "${WRAPPER_REF:-main}" https://github.com/glomatico/wrapper-v2 "$VENDOR"
fi

echo "==> Apple Music 라이브러리 추출 및 해시 검증 ($WRAPPER_ARCH)"
# Clear libraries staged for another arch; keep the tracked .gitkeep files.
find "$VENDOR/rootfs/system/lib64" "$VENDOR/rootfs/system/bin" -mindepth 1 ! -name .gitkeep -delete
rm -rf "$VENDOR/rootfs/system/usr"
bash "$VENDOR/tools/extract-libs.sh" --bundle "$APK" --arch "$WRAPPER_ARCH"
bash "$VENDOR/tools/stage-system.sh" --arch "$WRAPPER_ARCH"

echo "==> Docker 이미지 빌드 및 실행 (첫 빌드는 NDK 다운로드로 10분 이상 걸릴 수 있습니다)"
cd "$ROOT"
mkdir -p data/wrapper
export TARGET_ARCH="$WRAPPER_ARCH" RUNTIME_PLATFORM
docker compose up -d --build wrapper

echo "==> wrapper 응답 대기"
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${WRAPPER_HTTP_PORT:-8080}/health" >/dev/null 2>&1; then
        curl -fsS "http://127.0.0.1:${WRAPPER_HTTP_PORT:-8080}/health"; echo
        echo "완료! Papple Music의 Wrapper 탭에서 Apple ID로 로그인하세요."
        exit 0
    fi
    sleep 2
done
echo "wrapper가 아직 응답하지 않습니다. 로그 확인: docker compose logs wrapper" >&2
exit 1
