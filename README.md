<p align="center">
  <img src="gamdl_web/static/brand/icon.svg" alt="Papple Music" width="112">
</p>

<h1 align="center">Papple Music</h1>

<p align="center">
  <b>음악 앱처럼 편한 <a href="https://github.com/glomatico/gamdl">gamdl</a> 웹 GUI</b><br>
  검색하고, 미리 듣고, 원하는 음질을 골라 받는 개인용 Apple Music 다운로더
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/macOS%20%C2%B7%20Linux%20%C2%B7%20Docker-supported-555">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-e8402f">
</p>

<p align="center">
  <img src="docs/screenshots/album-lyrics-dark.png" alt="앨범 화면과 실시간 가사" width="920">
</p>

> **English** — Papple Music is a self-hosted web UI for [gamdl](https://github.com/glomatico/gamdl) with a music-app feel. Search the Apple Music catalog with type-ahead suggestions, browse albums, artists and playlists, stream songs and music videos in the browser, pick the exact quality for every download (ALAC up to 24-bit/192 kHz via [wrapper-v2](https://github.com/glomatico/wrapper-v2), Dolby Atmos, AAC), and convert to FLAC/WAV/MP3 with complete tags and artwork. It runs on your Mac/Linux box or on an x86 NAS such as Synology. You need your own active Apple Music subscription. The UI is in Korean.

---

## 목차

1. [이런 걸 할 수 있어요](#이런-걸-할-수-있어요)
2. [스크린샷](#스크린샷)
3. [시작하기 전에](#시작하기-전에)
4. [5분 만에 실행하기](#5분-만에-실행하기)
5. [로그인: 쿠키와 wrapper](#로그인-쿠키와-wrapper)
6. [wrapper 설치 (ALAC 무손실)](#wrapper-설치-alac-무손실)
7. [사용 설명서](#사용-설명서)
8. [설정](#설정)
9. [Docker · 시놀로지 NAS](#docker--시놀로지-nas)
10. [로고 바꾸기 (개인 브랜딩)](#로고-바꾸기-개인-브랜딩)
11. [보안](#보안)
12. [자주 묻는 질문](#자주-묻는-질문)
13. [프로젝트 구조](#프로젝트-구조)
14. [크레딧 · 면책 조항 · 라이선스](#크레딧--면책-조항--라이선스)

---

## 이런 걸 할 수 있어요

### 🔎 찾기
- **검색 + 연관 검색어** — `justi`만 쳐도 *justin bieber*, *justice* 같은 추천 검색어와 바로 가기 결과가 아래에 뜹니다. ↑↓ · Enter로 키보드만으로도 고를 수 있어요.
- **링크 붙여넣기** — Apple Music 링크를 넣으면 그 앨범 · 플레이리스트 · 아티스트 페이지로 바로 이동합니다. 노래 링크는 앨범에서 그 곡을 찾아 강조해 줘요.
- **둘러보기** — 장르 · 차트 · 무드 카테고리, 최근 검색, 앨범 · 아티스트 · 플레이리스트 상세 페이지, 다른 버전, 같은 아티스트의 다른 앨범.
- **보기 좋은 화면** — 앨범아트 색을 따라가는 배경, 움직이는 앨범 커버, 다크 · 라이트 모드, Lossless · Hi-Res · Dolby Atmos 표시.

### ⬇️ 받기
- **곡마다 실제 음질을 보여주고 골라서 받기** — 예: `ALAC 24bit · 96kHz`, `ALAC 24bit · 48kHz`, `Dolby Atmos 768kbps`, `AAC 256kbps`.
- **FLAC · WAV · MP3 자동 변환** — 24bit 그대로, 태그 · 커버 · 가사 유지.
- **모든 태그 + 추가 태그** — 레이블, UPC, Apple Music 링크, Apple ID, 언어, Explicit.
- **커버 · 가사 · 플레이리스트** — 원본 해상도 커버, 동기화 가사(LRC), M3U8, 움직이는 커버(`Cover.mp4`).
- **대기열** — 여러 개를 한 번에 받고, 트랙별 진행 상황과 로그를 실시간으로 확인. 이미 받은 곡은 건너뛰기.

### ▶️ 듣고 보기
- **브라우저 스트리밍** — AAC 256kbps 또는 무손실(ALAC → FLAC) 중 선택. 다음 곡은 미리 준비해 둬요.
- **음악 앱 같은 플레이어** — 셔플 · 반복 · 탐색바 · 볼륨 · AirPlay(Safari), 다음 재생 대기열과 재생 기록.
- **실시간 가사** — 줄이 바뀔 때마다 부드럽게 흘러가는 동기화 가사. 줄을 누르면 그 위치로 이동.
- **뮤직비디오** — 팝업 플레이어에서 HLS로 재생. 30초 미리보기가 바로 나오고, 전체 영상(1080p)이 준비되면 자동으로 바뀝니다.
- **우클릭 메뉴** — 다음에 재생, 플레이리스트에 추가, 앨범/아티스트로 이동, 정보 가져오기, 링크 복사, 다운로드.

### 📱 어디서나
- **휴대폰 화면** — 하단 탭 바, 미니 플레이어, 미니 플레이어에서 부드럽게 커지는 전체 화면 플레이어와 가사.
- **NAS에서 24시간** — 시놀로지 같은 x86 NAS의 Docker에서 돌리고 집 안 어디서나 접속.

---

## 스크린샷

| 연관 검색어 | 음질 고르기 |
| :---: | :---: |
| ![검색과 연관 검색어](docs/screenshots/search-dark.png) | ![다운로드 음질 선택](docs/screenshots/download-sheet-light.png) |
| **우클릭 메뉴** | **뮤직비디오 팝업** |
| ![우클릭 메뉴](docs/screenshots/context-menu-light.png) | ![뮤직비디오 팝업 플레이어](docs/screenshots/video-dark.png) |

<p align="center">
  <img src="docs/screenshots/phone.png" alt="휴대폰: 앨범과 미니 플레이어, 전체 화면 플레이어, 가사" width="760"><br>
  <sub>휴대폰 — 앨범 페이지와 미니 플레이어 → 전체 화면 플레이어 → 실시간 가사</sub>
</p>

---

## 시작하기 전에

| 필요한 것 | 설명 |
| --- | --- |
| **Apple Music 구독** | 본인 계정의 활성 구독이 꼭 필요합니다. |
| **[uv](https://docs.astral.sh/uv/)** | Python과 필요한 패키지를 알아서 설치해 주는 도구예요. |
| **[ffmpeg](https://ffmpeg.org)** | 변환 · 영상 처리 · 음질 확인에 씁니다. |
| **Docker** *(선택)* | ALAC 무손실을 받으려면 wrapper 컨테이너가 필요해요. macOS는 [OrbStack](https://orbstack.dev)을 추천합니다. |

macOS(Apple Silicon)에서 만들고 테스트했고, Linux에서도 동작합니다. "Finder에서 열기" 같은 몇몇 버튼만 macOS 전용이에요.

---

## 5분 만에 실행하기

**1. 도구 설치** (macOS, [Homebrew](https://brew.sh) 기준)

```bash
brew install uv ffmpeg
```

**2. 내려받고 실행**

```bash
git clone https://github.com/lewisysh/papple-music.git
cd papple-music
uv run papple-music --open
```

브라우저에서 <http://127.0.0.1:8765> 가 열리면 끝! 🎉

**3. 로그인** — 검색과 둘러보기는 바로 됩니다. 다운로드와 재생은 아래 [로그인](#로그인-쿠키와-wrapper) 중 하나를 해 주세요.

> [!TIP]
> - 설정 · 쿠키 · 캐시는 `~/.gamdl-web/`, 받은 음악은 기본으로 `~/Music/gamdl/`에 저장됩니다. (설정에서 바꿀 수 있어요)
> - 다음부터는 `uv run papple-music --open` 한 줄이면 됩니다.

---

## 로그인: 쿠키와 wrapper

| 방법 | 받을 수 있는 음질 | 준비 |
| --- | --- | --- |
| **쿠키 / 토큰** | AAC · AAC-HE · Dolby Atmos · 뮤직비디오 | **설정 → 쿠키**에서 `cookies.txt`를 올리거나 `media-user-token` 붙여넣기 |
| **wrapper** | 위 전부 + **ALAC 무손실 (Hi-Res 포함)** | wrapper 컨테이너 실행 후 **Wrapper** 탭에서 Apple ID 로그인 |

`cookies.txt`는 music.apple.com에 로그인한 브라우저에서 확장 프로그램(예: *Get cookies.txt LOCALLY*)으로 내보낼 수 있어요.

> [!WARNING]
> `media-user-token`과 쿠키 파일은 **비밀번호와 같습니다.** 이슈 · 채팅 · 스크린샷에 절대 올리지 마세요.
> 이 앱은 토큰을 로그와 화면에 표시하지 않고 `~/.gamdl-web/` 안에만 저장합니다.

---

## wrapper 설치 (ALAC 무손실)

[wrapper-v2](https://github.com/glomatico/wrapper-v2)는 Apple Music Android 라이브러리를 컨테이너에서 돌려 ALAC 스트림을 복호화해 주는 도구예요.

1. **Docker 실행** — [OrbStack](https://orbstack.dev)(macOS 추천) 또는 Docker Desktop을 설치하고 켭니다.
2. **APK 준비** — Apple Music Android APK **`3.6.0-beta-1109`**를 직접 준비합니다. *(이 저장소에는 들어 있지 않아요.)* 버전이 다르면 해시 검증에서 거부됩니다.
3. **설치 스크립트 실행**

   ```bash
   ./scripts/setup-wrapper.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk
   ```

   wrapper-v2를 받아 라이브러리를 추출 · 검증하고, 이미지를 빌드해 컨테이너를 띄웁니다. 첫 빌드는 10분 이상 걸릴 수 있어요.
4. **로그인** — 웹의 **Wrapper** 탭에서 Apple ID로 로그인하고 2단계 인증 코드를 넣습니다. 로그인 정보는 `data/wrapper/`에 남아서 컨테이너를 다시 켜도 유지됩니다.
5. **끝** — 이제 다운로드 창에 ALAC 음질이 나타납니다.

> wrapper는 `127.0.0.1:8080`(HTTP)과 `127.0.0.1:10020`(복호화)에서만 열립니다. 포트를 바꾸려면 `WRAPPER_HTTP_PORT`, `WRAPPER_DECRYPT_PORT` 환경 변수를 주고 설정 화면의 주소도 맞춰 주세요.

---

## 사용 설명서

<details open>
<summary><b>🔎 검색하고 찾기</b></summary>

- 검색창에 노래 · 앨범 · 아티스트 이름을 입력하세요. 몇 글자만 쳐도 **연관 검색어**와 바로 가기 결과가 뜹니다.
- 결과 위의 탭(전체 · 노래 · 앨범 · 아티스트 · 플레이리스트 · 뮤직비디오)으로 종류를 좁힐 수 있어요.
- **Apple Music 링크**를 붙여넣으면 그 페이지로 바로 이동합니다. 링크를 여러 줄로 여러 개 붙여넣으면 한꺼번에 대기열에 들어가요.
</details>

<details>
<summary><b>⬇️ 다운로드</b></summary>

- 곡 오른쪽의 빨간 **↓** 버튼 → 그 곡이 제공하는 음질 목록이 뜹니다 → 고르고 **다운로드**.
- 앨범 · 플레이리스트는 상세 페이지의 **앨범 다운로드** 버튼으로 통째로 받을 수 있어요.
- **다운로드** 탭에서 진행 상황, 트랙별 상태, 로그, 다시 시도, **Finder에서 폴더 열기**(macOS)를 볼 수 있습니다.
</details>

<details>
<summary><b>▶️ 듣기 · 가사 · 뮤직비디오</b></summary>

- 곡의 **▶** 버튼으로 재생합니다. 처음 듣는 곡은 몇 초 준비가 필요하고, 그다음부터는 바로 재생돼요.
- 플레이어의 `AAC` 배지를 누르면 **무손실 스트리밍**으로 바뀝니다(wrapper 로그인 필요).
- 💬 버튼은 **가사**, ☰ 버튼은 **다음 재생 / 재생 기록**입니다.
- 뮤직비디오의 ▶를 누르면 **팝업 플레이어**가 열립니다. 미리보기가 먼저 나오고 전체 영상이 준비되면 자동으로 바뀌어요.

| 조작 | 동작 |
| --- | --- |
| `Space` | 재생 / 일시정지 |
| 곡 우클릭 | 컨텍스트 메뉴 |
| 탐색바에 마우스 | 시간 표시, 클릭 · 드래그로 이동 |
| 볼륨 아이콘에 마우스 | 볼륨 막대 열림 |
| 휴대폰: 미니 플레이어 탭 | 전체 화면 플레이어 (아래로 끌어내려 닫기) |
</details>

---

## 설정

설정 화면에서 gamdl의 주요 옵션을 모두 바꿀 수 있어요. 파일은 `~/.gamdl-web/settings.json`에 저장됩니다.

| 항목 | 설명 |
| --- | --- |
| 출력 형식 | 원본(m4a) · FLAC · WAV · MP3(비트레이트 선택), 변환 후 원본 유지 여부 |
| 코덱 우선순위 | 다운로드 창에서 고르지 않았을 때 쓸 순서 (예: ALAC → AAC) |
| 폴더 / 파일 이름 | `{album_artist}/{album}/{track:02d} {title}` 같은 gamdl 템플릿 |
| 플레이리스트 경로 | 플레이리스트로 받은 곡을 따로 저장할 위치 |
| 커버 | 형식(jpg · png · raw), 크기(최대 10000), 파일로도 저장 |
| 가사 | 동기화 가사(LRC) 저장, 태그에 넣기 |
| 태그 | 넣을 태그를 체크박스로 선택 (커버 포함) |
| 뮤직비디오 | 최대 해상도, 코덱, 컨테이너 |
| wrapper | 기본 사용 여부, HTTP / 복호화 주소, 컨테이너 이름 |

<details>
<summary><b>환경 변수</b></summary>

| 이름 | 설명 |
| --- | --- |
| `GAMDL_WEB_HOST`, `GAMDL_WEB_PORT` | 서버 주소 (기본 `127.0.0.1:8765`). `--host`, `--port` 옵션도 있어요. |
| `GAMDL_WEB_PASSWORD` | 설정하면 HTTP Basic 인증을 켭니다 (아이디는 아무거나). `127.0.0.1`이 아닌 주소로 열 때는 필수예요. |
| `GAMDL_WEB_ALLOWED_HOSTS` | 비밀번호 없이 쓸 때 허용할 추가 호스트 이름 (쉼표로 구분) |
| `GAMDL_WEB_DATA_DIR` | 설정 · 쿠키 · 캐시 위치 (기본 `~/.gamdl-web`) |
| `GAMDL_WEB_UMASK` | 받은 파일 권한 (NAS에서 `000`이면 공유 폴더에서 바로 수정 가능) |
| `GAMDL_WEB_<설정 이름>` | 설정 파일이 없을 때 쓸 기본값 (예: `GAMDL_WEB_OUTPUT_PATH`) |
</details>

---

## Docker · 시놀로지 NAS

### 이 컴퓨터에서 전부 컨테이너로

```bash
GAMDL_WEB_PASSWORD='긴-비밀번호' docker compose --profile web up -d --build
```

다운로드는 `./downloads`(`GAMDL_WEB_DOWNLOADS=/경로`로 변경), 설정 · 쿠키는 `./data/web`에 저장됩니다. 포트는 `127.0.0.1:8765`에만 열려요.

### 시놀로지 NAS (Intel · AMD 모델)

DS220+, DS920+, DS923+ 같은 x86 시놀로지의 **Container Manager**에서 돌릴 수 있어요. PC에서 본인 APK로 이미지를 만든 뒤 NAS에 올리면 됩니다.

```bash
./scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk
# → dist/synology/  papple-music.tar · wrapper-v2.tar · docker-compose.yml (웹 비밀번호 자동 생성)
```

Apple 로그인과 쿠키는 빈 상태로 시작해요. 자세한 순서는 **[deploy/synology/README.md](deploy/synology/README.md)**를 보세요.

> [!IMPORTANT]
> `wrapper-v2.tar`에는 본인 APK에서 뽑은 Apple 라이브러리가 들어 있습니다. **공개된 곳에 올리지 마세요.**

---

## 로고 바꾸기 (개인 브랜딩)

설정 폴더에 `brand/` 폴더를 만들면 저장소를 고치지 않고 내 화면의 로고 · 이름만 바꿀 수 있어요. 이 폴더는 git에 올라가지 않습니다.

```
~/.gamdl-web/brand/
  brand.json      {"name": "My Music", "tagline": "Downloader"}
  mark.svg        사이드바 아이콘 (이름 옆)
  wordmark.svg    있으면 아이콘 + 이름 대신 이 워드마크를 표시 (단색 SVG)
  icon-64.png     브라우저 탭 아이콘
  icon-128.png    빈 화면 아이콘
  icon-180.png    홈 화면 아이콘 (iPhone)
```

없는 파일은 기본 Papple 로고를 씁니다. Docker에서는 데이터 폴더(`./data/web/brand/`)에 넣으면 돼요.

---

## 보안

Papple Music은 **혼자 쓰는 로컬 도구**로 설계되었습니다.

- 기본으로 `127.0.0.1`에만 열려서 이 컴퓨터에서만 접속할 수 있어요.
- 다른 사이트가 브라우저를 통해 API를 조작하지 못하도록 `Host` · `Origin` · `Sec-Fetch-Site`를 검사합니다. 비밀번호가 없으면 `localhost` / `127.0.0.1` 요청만 받아서 DNS 리바인딩 공격도 막아요.
- 설정 API로 ffmpeg · 쿠키 경로를 엉뚱한 프로그램 · 파일로 바꾸지 못하게 제한합니다.
- 토큰과 쿠키는 로그(DEBUG 포함) · 이벤트 · API 응답에서 가려집니다.
- 파일 열기 기능은 다운로드 폴더 안에서만 동작합니다.

**다른 기기(휴대폰 등)에서 접속하려면**

```bash
GAMDL_WEB_PASSWORD='긴-비밀번호' uv run papple-music --host 0.0.0.0
```

> [!CAUTION]
> `--host 0.0.0.0`으로 열 때는 **반드시 비밀번호를 설정하세요** (없으면 실행을 거부합니다).
> 인터넷에 직접 노출하지 말고 집 안 네트워크나 Tailscale 같은 VPN 안에서만 쓰는 걸 권장해요.

---

## 자주 묻는 질문

<details>
<summary><b>ALAC 음질이 안 보여요</b></summary>

Wrapper 탭에서 wrapper가 켜져 있고 로그인되어 있는지 확인하세요. 사이드바 아래에 "Wrapper 로그인됨"이 보여야 해요. wrapper 없이 조회하면 Apple 카탈로그 정보만 쓰기 때문에 48kHz가 넘는 Hi-Res가 빠질 수 있어요.
</details>

<details>
<summary><b>다운로드가 실패하거나 "쿠키가 필요합니다"라고 나와요</b></summary>

설정 → 쿠키에서 `cookies.txt`를 다시 올리거나 `media-user-token`을 새로 붙여넣으세요. 토큰은 몇 달 뒤 만료됩니다. 구독이 활성 상태인지도 확인해 주세요.
</details>

<details>
<summary><b>처음 재생할 때 느려요</b></summary>

브라우저는 Apple의 암호화된 스트림을 직접 재생할 수 없어서, 처음 재생할 때 서버가 곡을 받아 복호화합니다. AAC는 3~8초, 무손실은 10초, 뮤직비디오는 20초 정도 걸리고 이후에는 캐시(`~/.gamdl-web/stream/`)에서 바로 재생돼요.
</details>

<details>
<summary><b>wrapper 빌드가 해시 검증에서 실패해요</b></summary>

APK 버전이 정확히 `3.6.0-beta-1109`인지 확인하세요. `.apkm` 번들도 지원합니다.
</details>

<details>
<summary><b>AirPlay 버튼이 동작하지 않아요</b></summary>

웹 페이지의 AirPlay 기기 선택 창은 Safari에서만 열립니다. Chrome에서는 Cast 기능을 써 주세요.
</details>

<details>
<summary><b>"Apple Music 요청이 너무 많습니다"라고 나와요</b></summary>

짧은 시간에 요청이 몰리면 Apple이 잠깐 막습니다. 1분쯤 기다렸다가 다시 시도해 주세요.
</details>

---

## 프로젝트 구조

```
gamdl_web/
  app.py           FastAPI 라우트, 미들웨어(인증 · Origin 검사), SSE
  jobs.py          다운로드 대기열, 트랙별 상태, 변환 · 태그 후처리
  runner.py        설정 → gamdl API / 다운로더 구성
  search.py        카탈로그 검색, 연관 검색어, 상세 페이지, 가사, 보관함
  formats.py       곡별 제공 음질 조회 (wrapper HLS → 카탈로그)
  convert.py       ffmpeg 변환과 태그 복사 (FLAC / WAV / MP3)
  stream.py        미리 듣기 · 뮤직비디오 캐시 (AAC / 무손실 / HLS)
  motion.py        움직이는 앨범 커버
  prompts.py       gamdl의 대화형 질문 → 브라우저 선택창
  wrapper.py       wrapper-v2 HTTP API 프록시 (토큰은 브라우저로 보내지 않음)
  docker_ctl.py    docker CLI로 컨테이너 제어
  static/          웹 UI (빌드 과정 없는 HTML / CSS / JS, hls.js 포함)
scripts/
  setup-wrapper.sh     wrapper-v2 빌드 및 실행
  build-synology.sh    x86 NAS용 이미지 만들기
deploy/synology/       시놀로지용 compose 파일과 안내
compose.yaml           wrapper (+ 선택적으로 웹 UI) 컨테이너
```

웹 UI를 고칠 때는 서버를 켜 둔 채 `gamdl_web/static/` 파일을 수정하고 새로고침하면 됩니다. 파이썬 코드를 고쳤다면 서버를 다시 시작하세요.

---

## 크레딧 · 면책 조항 · 라이선스

**고마운 프로젝트**
- [glomatico/gamdl](https://github.com/glomatico/gamdl) — 실제 다운로드 엔진
- [glomatico/wrapper-v2](https://github.com/glomatico/wrapper-v2) — ALAC 복호화 컨테이너
- [FastAPI](https://fastapi.tiangolo.com) · [mutagen](https://github.com/quodlibet/mutagen) · [ffmpeg](https://ffmpeg.org) · [hls.js](https://github.com/video-dev/hls.js) (Apache-2.0)

**면책 조항**

Papple Music은 Apple Inc.와 관련이 없으며 Apple의 승인이나 지원을 받지 않았습니다. Apple Music, AirPlay, Apple Digital Master는 Apple Inc.의, Dolby Atmos는 Dolby Laboratories의 상표입니다. "Papple"은 배와 사과를 교배한 과일 이름이에요. 🍐🍎

**본인이 구독 중인 계정으로, 개인적인 용도로만 사용하세요.** 받은 음원을 배포하거나 공유하지 마세요. 사용하는 지역의 저작권법과 Apple Media Services 이용 약관을 지키는 것은 사용자의 책임입니다.

**라이선스** — [MIT](LICENSE)
