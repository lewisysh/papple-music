# Running on Synology (x86_64)

How to run Papple Music in **Container Manager** on an Intel / AMD Synology NAS (e.g. DS220+, DS920+, DS923+, DS1522+).
ARM-based models (DS223j, DS124, …) are not supported.

## 1. Build the images (once, on your computer)

The wrapper image has to contain the Apple Music app libraries, so there is no prebuilt public image.
Build it yourself from your own APK on a Mac or Linux machine with Docker.

```bash
git clone https://github.com/lewisysh/papple-music.git
cd papple-music
./scripts/build-synology.sh ~/Downloads/AppleMusic_3.6.0-beta-1109.apk
```

When it finishes, `dist/synology/` contains three files:

| File | What it is |
| --- | --- |
| `papple-music.tar` | Web UI image |
| `wrapper-v2.tar` | Wrapper image (contains the Apple libraries from your APK — **never upload it anywhere public**) |
| `docker-compose.yml` | Ready-to-use project file with a freshly generated web password |

## 2. Put it on the NAS

1. In **File Station**, create a `papple-music` folder inside the `docker` shared folder and upload the three files.
2. **Container Manager → Image → Add → Add from file**: import `papple-music.tar` and `wrapper-v2.tar`.
3. **Container Manager → Project → Create**
   - Project name: `papple-music`
   - Path: the folder from step 1
   - Source: **Use existing docker-compose.yml**
   - Skip the web portal settings and finish
4. Open `http://NAS-IP:8765` in a browser. Use any username; the password is the `GAMDL_WEB_PASSWORD` value in `docker-compose.yml`.

## 3. First-time setup

Apple sign-in and cookies start empty.

1. On the **Wrapper** tab, sign in with your Apple ID and enter the 2FA code (needed for ALAC lossless).
2. Optionally upload `cookies.txt` or paste a `media-user-token` in **Settings → Apple Music cookies**.
3. Check the download location: by default it's the project's `downloads/` folder.

## Changing the download location

Change this line in `docker-compose.yml` to the shared folder you want, then rebuild the project (stop → build).

```yaml
      - /volume1/music/AppleMusic:/downloads
```

Thanks to `GAMDL_WEB_UMASK: "000"`, downloaded files can be renamed or deleted right away from File Station / SMB.

## Where things are stored

| Folder | Contents |
| --- | --- |
| `data/wrapper/` | Apple sign-in session (delete to sign out) |
| `data/web/` | Settings, cookies, playback cache |
| `downloads/` | Your music |

## Your own logo (optional)

Put logo files in the project's `data/web/brand/` folder to change the logo on your NAS only. See "Custom branding" in the main README for file names.

## Notes

- The container start/stop buttons on the **Docker** tab don't work inside a container. Use Container Manager instead.
- For access from outside your home, don't open the port directly — use Synology's **reverse proxy + HTTPS** or a VPN such as Tailscale.
- Updating: `git pull` on your computer, repeat step 1, import the new tar files and rebuild the project. Keep the `data/` folder to keep your sign-in and settings.
- If the wrapper doesn't start, check the `papple-wrapper` container log in Container Manager.
