<p align="center">
  <img src="gamdl_web/static/brand/icon.svg" alt="Papple Music" width="112">
</p>

<h1 align="center">Papple Music</h1>

<p align="center">
  <b>A friendly, music-app style web GUI for <a href="https://github.com/glomatico/gamdl">gamdl</a></b><br>
  Search, preview and download from Apple Music in the exact quality you want
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/macOS%20%C2%B7%20Linux%20%C2%B7%20Docker-supported-555">
  <img alt="Languages" src="https://img.shields.io/badge/UI-English%20%C2%B7%20%ED%95%9C%EA%B5%AD%EC%96%B4-8e44ad">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-e8402f">
</p>

<p align="center">
  <a href="https://github.com/lewisysh/papple-music/releases/download/v1.0.0/Papple-Music-1.0.0-arm64.dmg"><img alt="Download for macOS" src="https://img.shields.io/badge/Download%20for%20macOS-v1.0.0%20%C2%B7%20Apple%20Silicon-fa2d48?style=for-the-badge"></a>
</p>

<h3 align="center"><a href="https://github.com/lewisysh/papple-music/releases/download/v1.0.0/Papple-Music-1.0.0-arm64.dmg">Papple-Music-1.0.0-arm64.dmg</a></h3>

<p align="center">
  <b>Apple Silicon · macOS 12 or later</b> · <a href="#mac-app-easiest">install guide</a> · <a href="https://github.com/lewisysh/papple-music/releases">all releases</a>
</p>

<p align="center">
  <img src="docs/screenshots/album-lyrics-dark.png" alt="Album page with live lyrics" width="920">
</p>

Papple Music is a self-hosted web app that puts a polished, Apple Music–like interface on top of [gamdl](https://github.com/glomatico/gamdl). Browse the catalog, listen before you download, pick ALAC Hi-Res, Dolby Atmos or AAC per song, and get perfectly tagged files — from your Mac, a Linux box, or a Synology NAS.

> [!NOTE]
> You need your own **active Apple Music subscription**. Papple Music is for personal use with your own account.

---

## Mac app (easiest)

No terminal needed — Python, all libraries and ffmpeg are inside the app.

1. Download **[Papple-Music-1.0.0-arm64.dmg](https://github.com/lewisysh/papple-music/releases/download/v1.0.0/Papple-Music-1.0.0-arm64.dmg)** (Apple Silicon Macs, macOS 12 or later). Older and newer versions are on the [**Releases**](https://github.com/lewisysh/papple-music/releases) page.
2. Open it and drag **Papple Music** into **Applications**.
3. Open **Papple Music**. It opens in its own window and sits in the Dock like any other app.

| | |
| --- | --- |
| Close the window | Papple Music keeps running; click the Dock icon to bring it back |
| Right-click the Dock icon | Open Download Folder · Open in Browser · Open at Login |
| ⌘Q (or Quit in the Dock menu) | Stops the server |

> [!IMPORTANT]
> **First launch:** the app isn't signed with an Apple Developer ID, so macOS blocks it the first time.
> Open **System Settings → Privacy & Security**, scroll down and click **Open Anyway** next to "Papple Music".
> (Or run `xattr -dr com.apple.quarantine "/Applications/Papple Music.app"` once.)

The app uses the same data folder (`~/.gamdl-web/`) as the source version. Everything works with just the app and your [cookies](#signing-in-cookies-vs-wrapper); for ALAC lossless, the [setup wizard](#setting-up-the-wrapper-alac-lossless) in the Wrapper tab installs the wrapper for you.

<details>
<summary><b>Build the app yourself</b></summary>

```bash
git clone https://github.com/lewisysh/papple-music.git
cd papple-music
./scripts/build-macapp.sh
# → dist/macapp/Papple Music.app and dist/Papple-Music-<version>-<arch>.dmg
```

The app is built for the CPU of the Mac you build on (Apple Silicon or Intel).
</details>

---

## Contents

1. [Mac app (easiest)](#mac-app-easiest)
2. [Features](#features)
3. [Screenshots](#screenshots)
4. [Requirements](#requirements)
5. [Quick start from source](#quick-start-from-source)
6. [Signing in: cookies vs. wrapper](#signing-in-cookies-vs-wrapper)
7. [Setting up the wrapper (ALAC lossless)](#setting-up-the-wrapper-alac-lossless)
8. [How to use](#how-to-use)
9. [Settings](#settings)
10. [Docker and Synology NAS](#docker-and-synology-nas)
11. [FAQ](#faq)
12. [Credits, disclaimer and license](#credits-disclaimer-and-license)

---

## Features

### 🔎 Find
- **Search with suggestions** — type `justi` and get *justin bieber*, *justice* and top results right under the box. Arrow keys + Enter work too.
- **Paste a link** — an Apple Music link opens its album, playlist or artist page. Song links open the album and highlight the song.
- **Browse** — genre, chart and mood categories, recent searches, album / artist / playlist / curator pages, other versions and more by the same artist.
- **Looks great** — backgrounds tinted by the artwork, motion album covers, dark and light mode, Lossless · Hi-Res · Dolby Atmos badges.
- **English and Korean UI** — switch any time in Settings.

### ⬇️ Download
- **See the real quality before you download** — e.g. `ALAC 24-bit · 96 kHz`, `ALAC 24-bit · 48 kHz`, `Dolby Atmos 768 kbps`, `AAC 256 kbps`.
- **Convert to FLAC, WAV or MP3** — keeps 24-bit, tags, cover and lyrics.
- **Every tag, plus extras** — label, UPC, Apple Music link, Apple ID, language and explicit flag.
- **Covers, lyrics, playlists** — full-resolution artwork, synced lyrics (LRC), M3U8 playlists, motion covers (`Cover.mp4`).
- **A real queue** — add many at once, watch per-track progress and logs live, skip what you already have.

### ▶️ Listen and watch
- **Stream in the browser** — AAC 256 kbps or lossless (ALAC served as FLAC). The next song is prepared in advance.
- **A music-app player** — shuffle, repeat, scrubber, volume, AirPlay (Safari), up next and history.
- **Live lyrics** — synced lyrics that glide line by line; click a line to jump there.
- **Music videos** — play in a popup HLS player. A 30-second preview starts instantly and the full 1080p video takes over when it's ready.
- **Right-click menu** — play next, add to playlist, go to album or artist, get info, copy link, download.

### 📱 Anywhere
- **Phone layout** — tab bar, mini player, and a full-screen player that grows out of the mini player, with lyrics.
- **Always on** — run it in Docker on an x86 NAS such as Synology and use it from any device at home.

---

## Screenshots

| Search suggestions | Choose the quality |
| :---: | :---: |
| ![Search with suggestions](docs/screenshots/search-dark.png) | ![Quality picker](docs/screenshots/download-sheet-light.png) |
| **Right-click menu** | **Music video popup** |
| ![Context menu](docs/screenshots/context-menu-light.png) | ![Music video player](docs/screenshots/video-dark.png) |

<p align="center">
  <img src="docs/screenshots/phone.png" alt="Phone: album with mini player, full-screen player, lyrics" width="760"><br>
  <sub>On a phone — album page with the mini player → full-screen player → live lyrics</sub>
</p>

---

## Requirements

| You need | Why |
| --- | --- |
| **Apple Music subscription** | An active subscription on your own account. |
| **[uv](https://docs.astral.sh/uv/)** | Installs Python and all dependencies for you. |
| **[ffmpeg](https://ffmpeg.org)** | Conversion, video handling and quality checks. |
| **Docker** *(optional)* | Needed for the wrapper container that unlocks ALAC lossless. On macOS, [OrbStack](https://orbstack.dev) is recommended. |

Built and tested on macOS (Apple Silicon); Linux works too. A few buttons such as "Open in Finder" are macOS-only.

---

## Quick start from source

**1. Install the tools** (macOS with [Homebrew](https://brew.sh))

```bash
brew install uv ffmpeg
```

**2. Get the code and run it**

```bash
git clone https://github.com/lewisysh/papple-music.git
cd papple-music
uv run papple-music --open
```

Your browser opens <http://127.0.0.1:8765>. That's it! 🎉

**3. Sign in** — searching and browsing work right away. To download and play, set up one of the [sign-in options](#signing-in-cookies-vs-wrapper).

> [!TIP]
> - Settings, cookies and caches live in `~/.gamdl-web/`; music is saved to `~/Music/Papple Music/` by default (change it in Settings), with albums in `Albums/`, playlists in `Playlists/` and single songs in `Songs/`.
> - The UI follows your browser language. Switch between **English** and **한국어** at the top of the Settings page.
> - Next time, `uv run papple-music --open` is all you need.

---

## Signing in: cookies vs. wrapper

| Method | Qualities | Setup |
| --- | --- | --- |
| **Cookies / token** | AAC · AAC-HE · Dolby Atmos · music videos | **Settings → Apple Music cookies**: upload `cookies.txt` or paste your `media-user-token` |
| **Wrapper** | All of the above + **ALAC lossless (incl. Hi-Res)** | Run the wrapper container, then sign in with your Apple ID on the **Wrapper** tab |

Export `cookies.txt` from a browser signed in to music.apple.com with an extension such as *Get cookies.txt LOCALLY*.

> [!WARNING]
> Your `media-user-token` and cookie file are **as sensitive as a password**. Never post them in issues, chats or screenshots.
> Papple Music never shows them in logs or the UI and only stores them in `~/.gamdl-web/`.

---

## Setting up the wrapper (ALAC lossless)

[wrapper-v2](https://github.com/glomatico/wrapper-v2) runs the Apple Music Android libraries in a container to decrypt ALAC streams. You only need it for lossless — search, streaming and AAC/Atmos downloads work without it.

### With the setup wizard (no terminal)

Open the **Wrapper** tab. The setup wizard walks you through three steps:

1. **Docker** — install the free [OrbStack](https://orbstack.dev) (or Docker Desktop). The wizard detects it and can start it for you.
2. **Apple Music APK** — get the Apple Music Android app **version `3.6.0-beta (1109)`** yourself (for example from APKMirror) and save it to your **Downloads** folder; the wizard finds and verifies it automatically. You can also drop the file onto the wizard. *(Papple Music doesn't include the APK — it's Apple's software.)*
3. **Install** — press **Start install**. The wizard downloads wrapper-v2, extracts and verifies the libraries, builds the image and starts the container, with a progress bar and live log. The first build takes 10–15 minutes.

Then sign in with your Apple ID (and 2FA code) right below. ALAC options now appear in the download window.

<details>
<summary><b>From the terminal (source checkout)</b></summary>

```bash
./scripts/setup-wrapper.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk
```

The session is kept in `data/wrapper/`. The wrapper only listens on `127.0.0.1:8080` (HTTP) and `127.0.0.1:10020` (decrypt); set `WRAPPER_HTTP_PORT` / `WRAPPER_DECRYPT_PORT` to change them and update the addresses in Settings.
</details>

---

## How to use

<details open>
<summary><b>🔎 Search and browse</b></summary>

- Type a song, album or artist name. After a few letters, **suggestions** and top results appear.
- Use the tabs above the results (All · Songs · Albums · Artists · Playlists · Music videos) to narrow them down.
- **Paste an Apple Music link** to jump straight to its page. Paste several links (one per line) to queue them all at once.
</details>

<details>
<summary><b>⬇️ Download</b></summary>

- Click the red **↓** next to a song → the qualities it actually offers appear → pick one and press **Download**.
- On album and playlist pages, **Download album** grabs everything.
- The **Downloads** tab shows progress, per-track status, logs, retry and **Open folder in Finder** (macOS).
</details>

<details>
<summary><b>▶️ Listen, lyrics and music videos</b></summary>

- Press **▶** to play. A song takes a few seconds the first time, then plays instantly.
- Click the `AAC` badge in the player to switch to **lossless streaming** (requires the wrapper).
- 💬 shows **lyrics**, ☰ shows **up next and history**.
- **▶** on a music video opens the **popup player**: the preview starts first and the full video replaces it when ready.

| Control | Action |
| --- | --- |
| `Space` | Play / pause |
| Right-click a song | Context menu |
| Hover the scrubber | Show times; click or drag to seek |
| Hover the volume icon | Open the volume slider |
| Phone: tap the mini player | Full-screen player (swipe down to close) |
</details>

---

## Settings

Everything important in gamdl can be changed on the Settings page. The file is `~/.gamdl-web/settings.json`.

| Setting | What it does |
| --- | --- |
| Output format | Original (m4a) · FLAC · WAV · MP3 (choose the bitrate); keep the original after converting |
| Codec priority | The order used when you don't pick a quality (e.g. ALAC → AAC) |
| Folder / file names | gamdl templates such as `Albums/{album_artist}/{album}/{track:02d} {title}` |
| Playlist path | Where songs downloaded from a playlist go (default `Playlists/…`) |
| Single song path | Where a song downloaded on its own goes (default `Songs/{artist} - {title}`), so one track doesn't get a one-song album folder |
| Cover | Format (jpg · png · raw), size (up to 10000), save as a file |
| Lyrics | Save synced lyrics (LRC), embed in tags |
| Tags | Choose exactly which tags are written (cover included) |
| Music videos | Max resolution, codec, container |
| Wrapper | Use by default, HTTP / decrypt addresses, container name |

<details>
<summary><b>Environment variables</b></summary>

| Name | Description |
| --- | --- |
| `GAMDL_WEB_HOST`, `GAMDL_WEB_PORT` | Server address (default `127.0.0.1:8765`). Also `--host` / `--port`. |
| `GAMDL_WEB_PASSWORD` | Enables HTTP Basic auth (any username). Required when listening on anything other than `127.0.0.1`. |
| `GAMDL_WEB_ALLOWED_HOSTS` | Extra host names allowed without a password (comma-separated) |
| `GAMDL_WEB_DATA_DIR` | Settings, cookies and caches (default `~/.gamdl-web`) |
| `GAMDL_WEB_UMASK` | Permissions for downloaded files (`000` on a NAS keeps them editable over SMB) |
| `GAMDL_WEB_<SETTING>` | Default for a setting when no settings file exists (e.g. `GAMDL_WEB_OUTPUT_PATH`) |
</details>

---

## Docker and Synology NAS

### Everything in containers on this machine

```bash
GAMDL_WEB_PASSWORD='a-long-password' docker compose --profile web up -d --build
```

Downloads go to `./downloads` (change with `GAMDL_WEB_DOWNLOADS=/path`), settings and cookies to `./data/web`. The port is only published on `127.0.0.1:8765`.

### Synology NAS (Intel / AMD models)

Runs in **Container Manager** on x86 Synology models such as the DS220+, DS920+ and DS923+. Build the images on your computer with your own APK, then upload them to the NAS.

```bash
./scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk
# → dist/synology/  papple-music-<version>.tar · wrapper-v2.tar · docker-compose.yml (with a web password)
```

Apple sign-in and cookies start empty. Step-by-step instructions: **[deploy/synology/README.md](deploy/synology/README.md)**.

> [!IMPORTANT]
> `wrapper-v2.tar` contains the Apple libraries extracted from your APK. **Never upload it anywhere public.**

---

## FAQ

<details>
<summary><b>I don't see ALAC options</b></summary>

Check the Wrapper tab: the wrapper must be running and signed in, and the sidebar should say "Wrapper · Signed in". Without the wrapper, only Apple's catalog data is available, so Hi-Res above 48 kHz may be missing.
</details>

<details>
<summary><b>Downloads fail or ask for cookies</b></summary>

Re-upload `cookies.txt` or paste a fresh `media-user-token` in Settings. Tokens expire after a few months. Also make sure your subscription is active.
</details>

<details>
<summary><b>The first play is slow</b></summary>

Browsers can't play Apple's encrypted streams, so the server downloads and decrypts a song the first time you play it: about 3–8 s for AAC, ~10 s for lossless and ~20 s for a music video. After that it plays from the cache (`~/.gamdl-web/stream/`).
</details>

<details>
<summary><b>The wrapper build fails the hash check</b></summary>

Make sure the APK is exactly version `3.6.0-beta-1109`. `.apkm` bundles are supported.
</details>

<details>
<summary><b>The AirPlay button doesn't work</b></summary>

Web pages can only open the AirPlay picker in Safari. In Chrome, use Cast instead.
</details>

<details>
<summary><b>"Too many requests to Apple Music"</b></summary>

Apple briefly rate-limits bursts of requests. Wait a minute and try again.
</details>

---

## Credits, disclaimer and license

**Built on**
- [glomatico/gamdl](https://github.com/glomatico/gamdl) — the download engine
- [glomatico/wrapper-v2](https://github.com/glomatico/wrapper-v2) — ALAC decryption container
- [FastAPI](https://fastapi.tiangolo.com) · [mutagen](https://github.com/quodlibet/mutagen) · [ffmpeg](https://ffmpeg.org) · [hls.js](https://github.com/video-dev/hls.js) (Apache-2.0)

**Disclaimer**

Papple Music is not affiliated with, endorsed by or sponsored by Apple Inc. Apple Music, AirPlay and Apple Digital Master are trademarks of Apple Inc.; Dolby Atmos is a trademark of Dolby Laboratories. "Papple" is the name of a pear–apple hybrid fruit. 🍐🍎

**Use it only with your own subscription and for personal use.** Don't distribute or share downloaded music. You are responsible for following the copyright laws where you live and the Apple Media Services Terms and Conditions.

**License** — [MIT](LICENSE)
