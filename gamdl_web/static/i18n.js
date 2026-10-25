// Korean is the source language. For English, rendered text and a few
// attributes are translated as they appear (a MutationObserver), so app code
// keeps writing Korean. Keys use {} for interpolated values; English values
// may use {0}, {1} to reorder them.
const I18N_EN = {
"{}분 {}초": "{}m {}s",
"{}초": "{}s",
"앨범": "Album",
"보관함 앨범": "Library album",
"플레이리스트": "Playlist",
"보관함 플레이리스트": "Library playlist",
"아티스트": "Artist",
"곡": "Song",
"뮤직비디오": "Music video",
"영상": "Video",
"AAC 바이노럴": "AAC Binaural",
"AAC 다운믹스": "AAC Downmix",
"AAC-HE 바이노럴": "AAC-HE Binaural",
"AAC-HE 다운믹스": "AAC-HE Downmix",
"ALAC 무손실": "ALAC Lossless",
"직접 선택": "Choose manually",
"선택": "Select",
"로그아웃됨": "Signed out",
"로그인 중…": "Signing in…",
"2단계 인증 대기": "Waiting for 2FA",
"로그인됨": "Signed in",
"로그인 실패": "Sign-in failed",
"미국": "United States",
"프랑스": "France",
"독일": "Germany",
"영국": "United Kingdom",
"캐나다": "Canada",
"호주": "Australia",
"뉴질랜드": "New Zealand",
"일본": "Japan",
"홍콩": "Hong Kong",
"싱가포르": "Singapore",
"중국": "China",
"한국": "Korea",
"대만": "Taiwan",
"{} · 검색 · {}": "{} · Search · {}",
"연결됨": "Connected",
"재연결 중": "Reconnecting",
"노래": "Songs",
"붙여넣은 링크": "Pasted link",
"링크 {}개를 대기열에 추가했습니다": "Added {} links to the queue",
"곡마다 제공되는 가장 높은 음질": "Best quality each song offers",
"Atmos가 없는 곡은 AAC로": "Songs without Atmos fall back to AAC",
"wrapper에 로그인되어 있지 않아 무손실·Atmos는 실패할 수 있습니다.": "The wrapper isn't signed in, so Lossless and Atmos may fail.",
"저장 형식: {}": "Saved as: {}",
"저장 형식: m4a": "Saved as: m4a",
"제공되는 음질을 확인하는 중…": "Checking available quality…",
"이 항목의 음질 정보를 찾지 못해 종류별로 고릅니다.": "Couldn't find quality info for this item, so pick a format family.",
"첫 곡 기준": "Based on the first song",
"곡마다 제공 음질이 다르면 같은 종류에서 가장 좋은 걸로 받습니다.": "If songs differ, each one gets the best quality in the same family.",
"wrapper 없이 조회해서 48kHz 넘는 Hi-Res가 빠졌을 수 있어요.": "Looked up without the wrapper, so Hi-Res above 48 kHz may be missing.",
"음질 정보를 가져오지 못했습니다: {}": "Couldn't get quality info: {}",
"{}대기열에 추가됨": "{}Queued",
"대기열에 추가됨 · 누르면 다운로드 화면으로": "Queued · click to open Downloads",
"대기열에 추가했습니다 · {}": "Added to the queue · {}",
"카테고리를 불러오지 못했습니다: {}": "Couldn't load categories: {}",
"재생": "Play",
"영상 재생": "Play video",
"링크 복사": "Copy link",
"Apple Music에서 열기": "Open in Apple Music",
"계정 없이 {} 스토어에서 검색": "Searching the {} store without an account",
"{} 스토어": "{} store",
"\"{}\"에 대한 결과가 없습니다.": "No results for \"{}\".",
"더 보기": "Show more",
"인기 결과": "Top results",
"링크를 복사했습니다": "Link copied",
"클립보드에 복사하지 못했습니다": "Couldn't copy to the clipboard",
"카테고리": "Categories",
"싱글": "Single",
"컴필레이션": "Compilation",
"{}시간 {}분": "{} hr {} min",
"{}분": "{} min",
"앨범 다운로드": "Download album",
"플레이리스트 다운로드": "Download playlist",
"아티스트 다운로드": "Download artist",
"뒤로": "Back",
"디스크 {}": "Disc {}",
"{}곡": "{} songs",
"{} 업데이트": "Updated {}",
"반복 안 함": "Repeat off",
"전체 반복": "Repeat all",
"한 곡 반복": "Repeat one",
"{} · 눌러서 {}로 전환": "{} · click to switch to {}",
"\"{}\" 검색 결과": "Results for \"{}\"",
"재생할 수 있는 곡이 없습니다": "Nothing playable here",
"재생하지 못했습니다: {}": "Couldn't play: {}",
"무손실 스트리밍은 wrapper 로그인이 필요합니다": "Lossless streaming needs the wrapper to be signed in",
"무손실(ALAC)로 스트리밍합니다 · 처음엔 준비가 조금 걸려요": "Streaming in Lossless (ALAC) · the first play takes a moment",
"AAC 256kbps로 스트리밍합니다": "Streaming in AAC 256 kbps",
"연결할 수 있는 기기를 찾지 못했습니다": "No devices found",
"이 브라우저는 다른 기기로 보내기를 지원하지 않습니다 (Safari에서 AirPlay 가능)": "This browser can't send audio to other devices (AirPlay works in Safari)",
"무손실 재생 준비에 실패했습니다. wrapper 상태를 확인하세요.": "Couldn't prepare lossless playback. Check the wrapper.",
"재생 준비에 실패했습니다. 다음 곡으로 넘어갑니다.": "Couldn't prepare playback. Skipping to the next song.",
"재생 기록": "History",
"지우기": "Clear",
"계속 재생": "Continue playing",
"다음에 재생할 곡이 없습니다.": "Nothing up next.",
"재생 중인 곡이 없습니다.": "Nothing is playing.",
"이 곡은 가사가 없습니다.": "This song has no lyrics.",
"영상 플레이어를 불러오지 못했습니다": "Couldn't load the video player",
"이 브라우저는 HLS 재생을 지원하지 않습니다": "This browser can't play HLS",
"미리보기 · 전체 영상 준비 중": "Preview · preparing full video",
"전체 영상 준비 중": "Preparing full video",
"전체 영상": "Full video",
"미리보기만 재생할 수 있어요": "Only the preview is available",
"재생할 수 없어요": "Can't play this video",
"다음에 재생": "Play next",
"플레이리스트에 추가": "Add to playlist",
"앨범으로 이동": "Go to album",
"아티스트로 이동": "Go to artist",
"정보 가져오기": "Get info",
"열기": "Open",
"Apple Music에서 보기": "View in Apple Music",
"다운로드…": "Download…",
"다음에 재생: {}": "Playing next: {}",
"플레이리스트에 추가했습니다": "Added to playlist",
"아티스트 정보를 찾지 못했습니다": "Couldn't find the artist",
"작곡가": "Composer",
"장르": "Genre",
"발매일": "Release date",
"트랙": "Track",
"길이": "Length",
"레이블": "Label",
"음질": "Quality",
"저작권": "Copyright",
"2160p (H.265) 영상 제공": "2160p (H.265) video available",
"영상 제공": "Video available",
"음질 확인 중…": "Checking quality…",
"정확한 음질 정보를 찾지 못했습니다": "Couldn't find exact quality info",
"진행 중 {}": "Active {}",
"대기 {}": "Waiting {}",
"끝남 {}": "Finished {}",
"대기열과 진행 상황": "Queue and progress",
"링크 {}개": "{} links",
"외 {}개": "and {} more",
"가사": "Lyrics",
"대기 중": "Waiting",
"다운로드 중 · {}/{}곡": "Downloading · {}/{} songs",
"준비 중…": "Preparing…",
"취소됨": "Canceled",
"실패": "Failed",
"{}곡 완료": "{} songs done",
"건너뜀 {}": "Skipped {}",
"오류 {}": "Errors {}",
"받은 항목 없음": "Nothing downloaded",
"다시 받기": "Download again",
"목록에서 지우기": "Remove from list",
"대기 취소": "Cancel",
"다운로드 중지": "Stop download",
"다운로드 중": "Downloading",
"준비 중": "Preparing",
"아직 트랙 정보가 없습니다.": "No track info yet.",
"상세": "Details",
"로그": "Log",
"트랙 {}": "Track {}",
"로그 없음": "No log",
"대기 {}개": "{} waiting",
"{}개 선택됨": "{} selected",
"하나 이상 고르거나 건너뛰기를 누르세요": "Pick at least one, or press Skip",
"항목을 고르세요": "Pick an item",
"확인 중": "Checking",
"꺼짐": "Off",
"복호화 포트": "Decrypt port",
"버전": "Version",
"Apple 라이브러리": "Apple libraries",
"재생 준비": "Playback ready",
"계정": "Account",
"오류": "Error",
"워커 재시작": "Worker restarts",
"{}회": "{}×",
"Docker 컨테이너가 실행 중인지, 설정의 주소가 맞는지 확인하세요.": "Make sure the Docker container is running and the address in Settings is right.",
"wrapper가 켜지면 여기서 로그인할 수 있습니다.": "You can sign in here once the wrapper is running.",
"구독 확인": "Check subscription",
"로그아웃": "Sign out",
"신뢰하는 Apple 기기에 표시된 6자리 코드를 입력하세요.": "Enter the 6-digit code shown on your trusted Apple device.",
"확인": "OK",
"취소": "Cancel",
"로그인 실패{}": "Sign-in failed{}",
"암호": "Password",
"로그인": "Sign in",
"로그인 중… (최대 1분)": "Signing in… (up to a minute)",
"로그인되었습니다": "Signed in",
"2단계 인증 코드를 입력하세요": "Enter the 2FA code",
"로그인 실패 ({}): {}": "Sign-in failed ({}): {}",
"인증 실패 ({}): {}": "Verification failed ({}): {}",
"{} 계정 · 스토어 {} · 구독 {}{}": "{} account · storefront {} · subscription {}{}",
"· {}부터": " · since {}",
"시작": "Start",
"중지": "Stop",
"재시작": "Restart",
"로그 보기": "View logs",
"컨테이너를 시작했습니다": "Container started",
"컨테이너를 중지했습니다": "Container stopped",
"컨테이너를 재시작했습니다": "Container restarted",
"(로그 없음)": "(no logs)",
"변수: {album} {album_artist} {artist} {title} {track:02d} {disc} {date:%Y} {composer} {media_type} · '/'로 하위 폴더를 만듭니다.": "Variables: {album} {album_artist} {artist} {title} {track:02d} {disc} {date:%Y} {composer} {media_type} · '/' makes subfolders.",
"플레이리스트 링크로 받을 때만 적용됩니다. 변수: {playlist_title} {playlist_artist} {playlist_track:02d} {artist} {title} {album}": "Only used for playlist links. Variables: {playlist_title} {playlist_artist} {playlist_track:02d} {artist} {title} {album}",
"커버": "Cover",
"제목": "Title",
"앨범 아티스트": "Album artist",
"트랙 번호": "Track number",
"총 트랙 수": "Track count",
"디스크 번호": "Disc number",
"총 디스크 수": "Disc count",
"Explicit 표시": "Explicit",
"갭리스": "Gapless",
"코멘트": "Comment",
"미디어 종류": "Media type",
"스토어": "Storefront",
"정렬용 제목": "Sort title",
"정렬용 아티스트": "Sort artist",
"정렬용 앨범": "Sort album",
"정렬용 작곡가": "Sort composer",
"Apple Music 링크": "Apple Music link",
"언어": "Language",
"Apple ID (곡)": "Apple ID (song)",
"앨범 ID": "Album ID",
"아티스트 ID": "Artist ID",
"작곡가 ID": "Composer ID",
"장르 ID": "Genre ID",
"저장": "Save",
"저장 폴더": "Download folder",
"임시 폴더": "Temp folder",
"일반": "General",
"메타데이터 언어": "Metadata language",
"en-US, ko-KR, ja-JP 등": "en-US, ko-KR, ja-JP, …",
"아티스트 링크": "Artist links",
"매번 물어보기": "Ask every time",
"로그 수준": "Log level",
"기본으로 wrapper 사용": "Use the wrapper by default",
"HTTP 주소": "HTTP address",
"복호화 호스트": "Decrypt host",
"Docker 컨테이너": "Docker container",
"음악": "Music",
"코덱 우선순위": "Codec priority",
"다운로드 창에서 음질을 고르지 않을 때 쓰는 기본값입니다. 앞에서부터 순서대로 시도해요.": "Used when you don't pick a quality in the download window. Tried in order.",
"싱크 가사 형식": "Synced lyrics format",
"싱크 가사 파일 저장 안 함": "Don't save synced lyrics files",
"가사만 저장": "Lyrics only",
"음원은 받지 않습니다": "Doesn't download the audio",
"곡 날짜에 앨범 발매일 사용": "Use the album release date for songs",
"뮤직비디오 · 영상": "Music videos",
"최대 해상도": "Max resolution",
"1440p 이상은 H.265 전용": "1440p and up are H.265 only",
"컨테이너": "Container",
"포스트 영상 화질": "Post video quality",
"커버 · 파일": "Cover · files",
"커버 형식": "Cover format",
"raw는 따로 저장만 하고 파일에는 넣지 않습니다": "raw is saved as a separate file only, not embedded",
"커버 크기(px)": "Cover size (px)",
"원본보다 크게 적으면 원본 해상도로 받습니다": "Sizes above the original fall back to the original resolution",
"커버 이미지 따로 저장": "Save the cover as a file",
"움직이는 커버도 저장 (Cover.mp4)": "Also save the motion cover (Cover.mp4)",
"움직이는 앨범아트가 있는 앨범만 · 최고 화질 HEVC": "Albums with motion art only · best quality HEVC",
"기존 파일 덮어쓰기": "Overwrite existing files",
"파일 형식": "File format",
"ALAC으로 받은 곡을 다운로드 직후 변환합니다. 태그·커버·가사는 그대로 옮겨요. Dolby Atmos는 m4a로 남고, AAC 같은 손실 음원은 FLAC/WAV로 바꾸지 않습니다.": "Converts ALAC downloads right after they finish, keeping tags, cover and lyrics. Dolby Atmos stays m4a, and lossy sources like AAC aren't turned into FLAC/WAV.",
"저장 형식": "Format",
"m4a 그대로 (ALAC · AAC · Atmos)": "Keep m4a (ALAC · AAC · Atmos)",
"MP3 비트레이트": "MP3 bitrate",
"V0 (가변 최고 음질)": "V0 (best variable quality)",
"변환 후 원본 m4a도 남기기": "Keep the original m4a after converting",
"오디오 메타데이터": "Audio metadata",
"켠 태그만 파일에 넣습니다.": "Only the tags you turn on are written.",
"플레이리스트 폴더에 따로 저장": "Save playlist songs in their own folder",
"플레이리스트 곡 경로": "Playlist song path",
"M3U8 파일 만들기": "Create M3U8 files",
"M3U8 폴더": "M3U8 folder",
"M3U8 파일 이름": "M3U8 file name",
"파일 이름": "File names",
"앨범 폴더": "Album folder",
"컴필레이션 폴더": "Compilation folder",
"파일 (디스크 1장)": "File (single disc)",
"파일 (디스크 여러 장)": "File (multiple discs)",
"앨범 없는 항목 폴더": "Folder for items without an album",
"앨범 없는 항목 파일": "File for items without an album",
"날짜 태그 형식": "Date tag format",
"파일 이름 최대 길이": "Max file name length",
"비우면 제한 없음": "Leave empty for no limit",
"고급": "Advanced",
"다운로드 방식": "Download mode",
"DRM 백엔드": "DRM backend",
"FFmpeg 경로": "FFmpeg path",
"N_m3u8DL-RE 경로": "N_m3u8DL-RE path",
".wvd 파일 경로": ".wvd file path",
".prd 파일 경로": ".prd file path",
"모두 켜기": "Turn all on",
"모두 끄기": "Turn all off",
"태그를 전혀 넣지 않음": "No tags at all",
"설정을 저장했습니다": "Settings saved",
"{}없음": "{}None",
"{}만료됨 ({})": "{}Expired ({})",
"{}정상 · {}": "{}OK · {}",
"쿠키를 업로드했습니다": "Cookies uploaded",
"토큰을 저장했습니다": "Token saved",
"쿠키 파일을 삭제할까요?": "Delete the cookie file?",
"초기화 실패: {}": "Couldn't start: {}",
"검색": "Search",
"다운로드": "Download",
"설정": "Settings",
"서버": "Server",
"연결 중": "Connecting",
"노래 · 앨범 · 아티스트 이름으로 찾거나 Apple Music 링크를 붙여넣으세요. 다운로드 버튼을 누르면 음질을 고를 수 있어요.": "Find songs, albums and artists, or paste an Apple Music link. Press download to choose the quality.",
"전체": "All",
"최근 검색": "Recent searches",
"카테고리 둘러보기": "Browse categories",
"Finder에서 폴더 열기": "Open folder in Finder",
"완료 항목 지우기": "Clear finished",
"대기열이 비어 있습니다": "The queue is empty",
"검색에서 곡을 찾거나 링크를 붙여넣으면 여기에 나타나요.": "Find songs in Search or paste a link and they'll show up here.",
"검색으로 가기": "Go to Search",
"ALAC 무손실을 받기 위한 복호화 서버입니다.": "The decryption server for downloading ALAC lossless.",
"연결 상태": "Connection",
"새로고침": "Refresh",
"확인 중…": "Checking…",
"비밀번호는 저장하지 않고 wrapper로만 전달합니다. 로그인 세션은 wrapper 컨테이너에 유지돼요.": "Your password isn't stored; it's only passed to the wrapper. The session stays in the wrapper container.",
"최근 로그": "Recent log",
"설치 가이드": "Setup guide",
"(권장) 또는": "(recommended) or",
"을 설치하고 실행합니다.": "and start it.",
")를 준비합니다. 라이브러리는 wrapper-v2에 고정된 해시로 검증합니다.": "). The libraries are verified against hashes pinned by wrapper-v2.",
"프로젝트 폴더에서 설치 스크립트를 실행합니다. 첫 빌드는 10분 이상 걸릴 수 있어요.": "Run the setup script from the project folder. The first build can take over 10 minutes.",
"위의": "Sign in at",
"에서 로그인하고 2단계 인증 코드를 입력합니다.": "above and enter the 2FA code.",
"다운로드 화면에서": "In the download window, turn on",
"를 켜고": "and pick",
"무손실": "Lossless",
"을 고릅니다.": ".",
"저장 위치, 음질, 파일 이름, 메타데이터를 정합니다.": "Where to save, quality, file names and metadata.",
"Apple Music 쿠키": "Apple Music cookies",
"상태": "Status",
"cookies.txt 업로드": "Upload cookies.txt",
"삭제": "Delete",
"wrapper 없이 받을 때 필요합니다. music.apple.com에 로그인한 브라우저에서": "Needed to download without the wrapper. Export from a browser signed in to music.apple.com with",
"또는": "or",
"로 내보내세요.": ".",
"다음 재생": "Up next",
"전체 영상을 준비하는 중…": "Preparing the full video…",
"저장하지 않은 변경사항": "Unsaved changes",
"되돌리기": "Revert",
"모두 선택": "Select all",
"선택 해제": "Select none",
"건너뛰기": "Skip",
"음질 선택": "Choose quality",
"Apple Music 프로필 열기": "Open Apple Music profile",
"아티스트, 노래, 앨범 또는 링크": "Artists, songs, albums or a link",
"검색 제안": "Search suggestions",
"검색 종류": "Search type",
"media-user-token 붙여넣기": "Paste media-user-token",
"플레이어": "Player",
"셔플": "Shuffle",
"이전": "Previous",
"이전 곡": "Previous song",
"다음": "Next",
"다음 곡": "Next song",
"반복": "Repeat",
"AirPlay · 다른 기기로 재생": "AirPlay · play on another device",
"볼륨": "Volume",
"음량": "Volume",
"음소거": "Mute",
"지금 재생 중": "Now playing",
"플레이어 닫기": "Close player",
"앨범 아트 보기": "Show album art",
"재생/일시정지": "Play/Pause",
"재생 목록과 가사": "Queue and lyrics",
"닫기": "Close",
"오류: 외부에 공개된 주소로 실행하려면 GAMDL_WEB_PASSWORD 환경 변수로 비밀번호를 설정하세요.": "Error: set a password with GAMDL_WEB_PASSWORD to run on a public address.",
"{}: {} 실행 파일만 지정할 수 있습니다": "{}: only a {} executable is allowed",
"cookies_path: {} 안의 경로만 지정할 수 있습니다": "cookies_path: must be inside {}",
"{}: 루트나 홈 폴더가 아닌 절대 경로를 지정하세요": "{}: use an absolute path that isn't the root or home folder",
"Netscape 형식 쿠키 파일이 아닙니다: {}": "Not a Netscape cookie file: {}",
"media-user-token 쿠키가 없습니다. music.apple.com에 로그인한 상태로 내보내세요.": "No media-user-token cookie. Export while signed in to music.apple.com.",
"파일이 너무 큽니다": "File too large",
"잘못된 쿠키 파일": "Invalid cookie file",
"media-user-token 값이 올바르지 않습니다": "Invalid media-user-token",
"검색어를 입력하세요": "Enter a search term",
"검색할 종류를 고르세요": "Choose what to search",
"Apple Music 검색에 실패했습니다: {}": "Apple Music search failed: {}",
"지원하지 않는 항목입니다": "Unsupported item",
"잘못된 요청입니다": "Bad request",
"움직이는 커버를 가져오지 못했습니다: {}": "Couldn't get the motion cover: {}",
"움직이는 커버가 없는 앨범입니다": "This album has no motion cover",
"재생 준비에 실패했습니다: {}": "Couldn't prepare playback: {}",
"잘못된 영상 ID입니다": "Invalid video ID",
"영상 준비에 실패했습니다: {}": "Couldn't prepare the video: {}",
"영상이 아직 준비되지 않았습니다": "The video isn't ready yet",
"잘못된 곡 ID입니다": "Invalid song ID",
"플레이리스트에 추가하지 못했습니다 (HTTP {})": "Couldn't add to the playlist (HTTP {})",
"macOS에서만 지원합니다": "Only supported on macOS",
"출력 폴더 밖의 경로입니다": "That path is outside the download folder",
"폴더가 없습니다": "Folder not found",
"URL을 입력하세요": "Enter a URL",
"Apple Music URL이 아닙니다:": "Not an Apple Music URL:",
"작업을 찾을 수 없습니다": "Job not found",
"이미 닫힌 선택창입니다": "That prompt is already closed",
"docker {} 실패": "docker {} failed",
"출력 폴더 밖의 경로이거나 파일이 없습니다": "Outside the download folder, or the file doesn't exist",
"Dolby 음원이라 m4a 그대로 둠": "Dolby audio, kept as m4a",
"손실 음원({})이라 {} 변환 안 함": "Lossy source ({}), not converted to {}",
"{} 변환 ({})": "Converted to {} ({})",
"잘못된 컨테이너 이름: {}": "Invalid container name: {}",
"docker 명령을 찾을 수 없습니다 (OrbStack 또는 Docker Desktop 설치 필요)": "docker command not found (install OrbStack or Docker Desktop)",
"컨테이너가 아직 없습니다. scripts/setup-wrapper.sh로 빌드하세요.": "The container doesn't exist yet. Build it with scripts/setup-wrapper.sh.",
"docker 데몬에 연결할 수 없습니다": "Can't connect to the Docker daemon",
"지원하지 않는 동작: {}": "Unsupported action: {}",
"바이노럴": "Binaural",
"다운믹스": "Downmix",
"스트리밍할 수 없는 항목": "Can't be streamed",
"고른 코덱으로 제공되지 않음": "Not available in the chosen codec",
"복호화할 수 없음": "Can't be decrypted",
"해당 종류의 항목이 없음": "No items of that kind",
"이미 받은 파일": "Already downloaded",
"필터로 제외됨": "Excluded by filter",
"선택을 건너뜀": "Selection skipped",
"진행 중인 작업은 삭제할 수 없습니다": "A running job can't be deleted",
"세션 준비 중": "Preparing session",
"(wrapper 사용)": "(using the wrapper)",
"계정에 콘텐츠 제한이 걸려 있어 일부 항목은 받을 수 없을 수 있습니다": "Your account has content restrictions, so some items may not download",
"완료 — 성공 {}, 건너뜀 {}, 오류 {}": "Done — {} succeeded, {} skipped, {} errors",
"작업이 취소되었습니다": "Job canceled",
"처리 중: \"{}\"": "Working on: \"{}\"",
"건너뜀 \"{}\": {}": "Skipped \"{}\": {}",
"오류 \"{}\": {}": "Error \"{}\": {}",
"변환 중…": "Converting…",
"지원하지 않는 URL입니다: {}": "Unsupported URL: {}",
"지원하지 않는 URL: {}": "Unsupported URL: {}",
"선택이 취소되어 이 URL을 건너뜁니다": "Selection canceled, skipping this URL",
"추가 태그(레이블·UPC 등)를 쓰지 못했습니다: {}": "Couldn't write extra tags (label, UPC, …): {}",
"움직이는 커버 저장: Cover.mp4": "Saved motion cover: Cover.mp4",
"움직이는 커버를 저장하지 못했습니다: {}": "Couldn't save the motion cover: {}",
"변환 실패 \"{}\": {}": "Conversion failed \"{}\": {}",
"변환 실패, m4a로 남김: {}": "Conversion failed, kept as m4a: {}",
"정규 앨범": "Albums",
"컴필레이션 앨범": "Compilations",
"라이브 앨범": "Live albums",
"싱글 & EP": "Singles & EPs",
"모든 앨범": "All albums",
"인기곡": "Top songs",
"사용자가 선택을 취소했습니다": "Selection canceled",
"선택 항목이 범위를 벗어났습니다": "Selection out of range",
"하나만 선택해야 합니다": "Pick only one",
"다운로드할 오디오 코덱을 선택하세요": "Choose the audio codec to download",
"뮤직비디오 화질/코덱을 선택하세요": "Choose the music video quality/codec",
"뮤직비디오 오디오 코덱을 선택하세요": "Choose the music video audio codec",
"영상 화질을 선택하세요": "Choose the video quality",
"\"{}\" — 무엇을 다운로드할까요?": "\"{}\" — what should be downloaded?",
"{}개 이상": "{} or more",
"{} — 다운로드할 항목을 고르세요": "{} — choose items to download",
"커버 이미지를 받지 못해 커버 없이 진행합니다: {}": "Couldn't get the cover image, continuing without it: {}",
"wrapper({})에 연결할 수 없습니다: {}": "Can't connect to the wrapper ({}): {}",
"wrapper에 로그인되어 있지 않습니다. Wrapper 탭에서 Apple ID로 로그인하세요.": "The wrapper isn't signed in. Sign in with your Apple ID in the Wrapper tab.",
"wrapper({})에 연결할 수 없습니다. 컨테이너가 실행 중인지 확인하세요.": "Can't connect to the wrapper ({}). Make sure the container is running.",
"wrapper 오류: {}": "Wrapper error: {}",
"Apple Music이 wrapper 세션을 거부했습니다 ({}). Wrapper 탭에서 로그아웃 후 다시 로그인해 보세요.": "Apple Music rejected the wrapper session ({}). Sign out and back in on the Wrapper tab.",
"cookies.txt가 없습니다. 설정 탭에서 Apple Music 쿠키 파일을 업로드하거나 wrapper를 사용하세요.": "No cookies.txt. Upload an Apple Music cookie file in Settings, or use the wrapper.",
"쿠키 파일 문제: {}": "Cookie file problem: {}",
"Apple Music이 쿠키/토큰을 거부했습니다 ({}).": "Apple Music rejected the cookies/token ({}).",
"만료되었거나 잘못된 값일 수 있으니 music.apple.com에서 다시 내보내 주세요.": "They may be expired or invalid; export them again from music.apple.com.",
"PlayReady 백엔드를 쓰려면 .prd 파일 경로가 필요합니다.": "The PlayReady backend needs a .prd file path.",
"활성화된 Apple Music 구독을 찾지 못했습니다.": "No active Apple Music subscription found.",
"최신 발매": "Latest release",
"싱글 및 EP": "Singles & EPs",
"참여한 앨범": "Appears on",
"다른 버전": "Other versions",
"{}의 다른 앨범": "More by {}",
"비슷한 앨범": "Similar albums",
"수록된 플레이리스트": "Featured in playlists",
"계정 없이 검색합니다: {}": "Searching without an account: {}",
"Apple Music에 연결하지 못했습니다 ({})": "Couldn't reach Apple Music ({})",
"Apple Music에서 찾을 수 없습니다": "Not found on Apple Music",
"Apple Music 요청이 너무 많습니다. 잠시 후 다시 시도하세요.": "Too many requests to Apple Music. Try again in a moment.",
"Apple Music이 HTTP {}로 응답했습니다": "Apple Music responded with HTTP {}",
"Apple Music 인증에 실패했습니다": "Apple Music authentication failed",
"내 보관함": "My library",
"검색 세션을 미리 준비하지 못했습니다: {}": "Couldn't warm up the search session: {}",
"재생할 수 있는 음원을 찾지 못했습니다": "Couldn't find a playable stream",
"/me 요청 실패: {}": "/me request failed: {}",
"wrapper에 연결할 수 없습니다: {}": "Can't connect to the wrapper: {}",
"{}번": "#{}",
"대기열에 추가됨": "Queued",
"없음": "None",
"만료됨 ({})": "Expired ({})",
"정상 · {}": "OK · {}",
"정상": "OK",
"로그인 실패: {}": "Sign-in failed: {}",
"{} 계정": "{} account",
"스토어 {}": "storefront {}",
"구독 {}": "subscription {}",
"구독": "Subscription",
"활성": "active",
"비활성": "inactive",
"{}부터": "since {}",
"Wrapper 로그인됨": "Wrapper signed in",
"Finder에서 열기": "Open in Finder",
"Finder에서 보기": "Show in Finder",
"불러옴": "Loaded",
"준비됨": "Ready",
"준비 안 됨": "Not ready",
"응답 없음": "No response",
"쿠키": "Cookies",
"콘텐츠 제한 있음": "content restrictions",
"실행 중": "Running",
"최고": "Best",
"{}에서": "from {}",
"{} ({})": "{} ({})",
"움직이는 커버 저장": "Save motion cover",
"모두 보기": "See all",
"아래에서 추가하세요": "Add some below",
"필요: {}": "Required: {}",
"{} (필요: {})": "{} (required: {})",
"저장 위치": "Storage",
"{} · {}부터": "{0} · since {1}"
};

const i18n = (() => {
  const HANGUL = /[가-힣]/;
  const ATTRS = ["title", "placeholder", "aria-label", "alt", "data-tip"];
  const escapeRe = (s) => s.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  const exact = new Map();
  const patterns = [];
  const entries = Object.entries(I18N_EN);
  for (const [key, value] of [...entries]) {
    const bare = key.replace(/^\{\}|\{\}$/g, "");
    if (bare !== key && HANGUL.test(bare) && !(bare in I18N_EN)) entries.push([bare, value.replace(/^\{\}|\{\}$/g, "")]);
  }
  for (const [key, value] of entries) {
    if (key.includes("{}")) {
      const re = new RegExp(`^${key.split("{}").map(escapeRe).join("(.+?)")}$`, "s");
      patterns.push([re, value, key.replace(/\{\}/g, "").length]);
    } else {
      exact.set(key, value);
    }
  }
  patterns.sort((a, b) => b[2] - a[2]);
  const cache = new Map();

  function fill(template, groups) {
    let i = 0;
    return template.replace(/\{(\d*)\}/g, (m, n) => {
      const g = groups[n === "" ? i++ : Number(n)];
      return g === undefined ? m : translate(g);
    });
  }

  function translateCore(s) {
    const norm = s.replace(/\s+/g, " ");
    if (exact.has(norm)) return exact.get(norm);
    for (const [re, value] of patterns) {
      const m = re.exec(norm);
      if (m) return fill(value, m.slice(1));
    }
    const prefix = /^([+·•–—]\s*)(.+)$/.exec(norm);
    if (prefix) {
      const rest = translateCore(prefix[2]);
      if (rest !== prefix[2]) return prefix[1] + rest;
    }
    if (norm.includes(" · ")) {
      const parts = norm.split(" · ");
      const out = parts.map((p) => (HANGUL.test(p) ? translateCore(p) : p));
      if (out.some((o, i) => o !== parts[i])) return out.join(" · ");
    }
    return s;
  }

  function translate(text) {
    if (!text || !HANGUL.test(text)) return text;
    if (cache.has(text)) return cache.get(text);
    const [, lead, core, tail] = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
    const out = translateCore(core);
    const result = out === core ? text : lead + out + tail;
    if (cache.size > 5000) cache.clear();
    cache.set(text, result);
    return result;
  }

  let lang = "ko";
  try {
    lang = JSON.parse(localStorage.getItem("gamdl-web:lang")) || (navigator.language.startsWith("ko") ? "ko" : "en");
  } catch {
    lang = navigator.language?.startsWith("ko") ? "ko" : "en";
  }

  const origText = new WeakMap();
  const shownText = new WeakMap();
  const origAttrs = new WeakMap();
  // Names of songs, albums, playlists and people are content, not UI text.
  const CONTENT = ".sb-playlists, .sb-profile-text, .song-title, .card-title, .sg-text b, .recent-text b, .q-text, "
    + ".pl-text, .fp-text, .fp-head-text, .video-text, .job-title, .t-title, .detail-head h1, .dl-meta h3, .info-head h2";
  const skip = (el) => el?.closest?.(`script, style, textarea, [data-no-i18n], ${CONTENT}`);
  const skipAttr = (el) => el?.closest?.("[data-no-i18n], .sb-playlists");

  function applyText(node) {
    const cur = node.data;
    if (lang !== "en" || shownText.get(node) === cur || !HANGUL.test(cur) || skip(node.parentElement)) return;
    const parent = node.parentElement;
    const out = parent?.dataset.en && parent.childNodes.length === 1 ? parent.dataset.en : translate(cur);
    if (out === cur) return;
    origText.set(node, cur);
    shownText.set(node, out);
    node.data = out;
  }

  function applyAttrs(el) {
    if (lang !== "en" || skipAttr(el)) return;
    for (const name of ATTRS) {
      const value = el.getAttribute(name);
      if (!value || !HANGUL.test(value)) continue;
      const rec = origAttrs.get(el) || {};
      if (rec[name]?.shown === value) continue;
      const out = translate(value);
      if (out === value) continue;
      rec[name] = { orig: value, shown: out };
      origAttrs.set(el, rec);
      el.setAttribute(name, out);
    }
  }

  function walk(root) {
    if (root.nodeType === Node.TEXT_NODE) { applyText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    const texts = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = texts.nextNode(); n; n = texts.nextNode()) applyText(n);
    applyAttrs(root);
    root.querySelectorAll(ATTRS.map((a) => `[${a}]`).join(",")).forEach(applyAttrs);
  }

  function revert(root) {
    const texts = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = texts.nextNode(); n; n = texts.nextNode()) {
      if (shownText.get(n) === n.data) n.data = origText.get(n);
      shownText.delete(n);
    }
    root.querySelectorAll(ATTRS.map((a) => `[${a}]`).join(",")).forEach((el) => {
      const rec = origAttrs.get(el);
      if (!rec) return;
      for (const [name, { orig, shown }] of Object.entries(rec)) if (el.getAttribute(name) === shown) el.setAttribute(name, orig);
      origAttrs.delete(el);
    });
  }

  new MutationObserver((records) => {
    if (lang !== "en") return;
    for (const r of records) {
      if (r.type === "characterData") applyText(r.target);
      else if (r.type === "attributes") applyAttrs(r.target);
      else r.addedNodes.forEach(walk);
    }
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });

  function set(next) {
    lang = next === "en" ? "en" : "ko";
    try { localStorage.setItem("gamdl-web:lang", JSON.stringify(lang)); } catch { /* storage unavailable */ }
    document.documentElement.lang = lang;
    if (lang === "en") walk(document.documentElement);
    else revert(document.documentElement);
    document.dispatchEvent(new CustomEvent("langchange", { detail: lang }));
  }

  document.documentElement.lang = lang;
  if (lang === "en") walk(document.documentElement);

  return {
    t: (text) => (lang === "en" ? translate(text) : text),
    get lang() { return lang; },
    get locale() { return lang === "en" ? "en-US" : "ko-KR"; },
    set,
  };
})();
