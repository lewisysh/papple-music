# 시놀로지(x86_64)에서 실행하기

Intel / AMD CPU를 쓰는 시놀로지 NAS (예: DS220+, DS920+, DS923+, DS1522+)의 **Container Manager**에서 Papple Music을 실행하는 방법입니다.
ARM 기반 모델(DS223j, DS124 등)은 지원하지 않습니다.

## 1. 이미지 만들기 (PC에서 한 번)

wrapper 이미지에는 Apple Music 앱의 라이브러리가 들어가야 해서, 미리 만들어진 공개 이미지가 없습니다.
Docker가 설치된 PC(Mac / Linux)에서 본인의 APK로 직접 만듭니다.

```bash
git clone https://github.com/lewisysh/papple-music.git
cd papple-music
./scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk
```

끝나면 `dist/synology/` 폴더에 세 파일이 생깁니다.

| 파일 | 설명 |
| --- | --- |
| `papple-music.tar` | 웹 UI 이미지 |
| `wrapper-v2.tar` | wrapper 이미지 (본인 APK의 Apple 라이브러리 포함 — **공개된 곳에 올리지 마세요**) |
| `docker-compose.yml` | 바로 쓸 수 있는 설정 파일 (웹 비밀번호가 새로 생성되어 들어 있음) |

## 2. 시놀로지에 올리기

1. **File Station**에서 `docker` 공유 폴더 안에 `papple-music` 폴더를 만들고 세 파일을 올립니다.
2. **Container Manager → 이미지 → 추가 → 파일에서 추가**로 `papple-music.tar`, `wrapper-v2.tar`를 하나씩 가져옵니다.
3. **Container Manager → 프로젝트 → 생성**
   - 프로젝트 이름: `papple-music`
   - 경로: 1번에서 만든 폴더
   - 소스: **기존 docker-compose.yml 사용**
   - 웹 포털 설정은 건너뛰고 완료
4. 브라우저에서 `http://NAS-IP:8765` 접속 → 아이디는 아무거나, 비밀번호는 `docker-compose.yml`의 `GAMDL_WEB_PASSWORD` 값.

## 3. 처음 설정

처음에는 Apple 로그인과 쿠키가 모두 비어 있습니다.

1. **Wrapper** 탭에서 Apple ID로 로그인하고 2단계 인증 코드를 입력합니다. (ALAC 무손실에 필요)
2. 필요하면 **설정 → 쿠키**에서 `cookies.txt`를 올리거나 `media-user-token`을 붙여넣습니다.
3. 다운로드 위치 확인: 기본은 프로젝트 폴더의 `downloads/`입니다.

## 다운로드 위치 바꾸기

`docker-compose.yml`에서 아래 줄을 원하는 공유 폴더로 바꾸고 프로젝트를 다시 빌드(정지 → 빌드)합니다.

```yaml
      - /volume1/music/AppleMusic:/downloads
```

받은 파일은 `GAMDL_WEB_UMASK: "000"` 설정 덕분에 File Station / SMB에서 바로 이름을 바꾸거나 지울 수 있습니다.

## 저장되는 위치

| 폴더 | 내용 |
| --- | --- |
| `data/wrapper/` | Apple 로그인 세션 (지우면 로그아웃) |
| `data/web/` | 설정, 쿠키, 재생 캐시 |
| `downloads/` | 받은 음악 |

## 내 로고 쓰기 (선택)

프로젝트 폴더의 `data/web/brand/`에 로고 파일을 넣으면 내 NAS 화면에만 그 로고가 보입니다. 파일 이름과 형식은 메인 README의 "로고 바꾸기" 항목을 보세요.

## 참고

- **Docker 탭**의 컨테이너 시작/중지 버튼은 컨테이너 안에서는 동작하지 않습니다. Container Manager에서 조작하세요.
- 바깥(인터넷)에서 접속하려면 포트를 직접 열지 말고 시놀로지 **역방향 프록시 + HTTPS** 또는 Tailscale 같은 VPN을 쓰세요.
- 업데이트: PC에서 저장소를 `git pull` 한 뒤 1번을 다시 하고, 새 tar를 가져와서 프로젝트를 다시 빌드합니다. `data/` 폴더는 그대로 두면 로그인과 설정이 유지됩니다.
