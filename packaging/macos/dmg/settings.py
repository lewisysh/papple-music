# dmgbuild settings for the Papple Music disk image (see scripts/build-macapp.sh).
# Defines passed with -D: app (path to the .app), icon (volume .icns), background.
import os.path

application = defines["app"]  # noqa: F821 (provided by dmgbuild)
appname = os.path.basename(application)

format = "ULFO"  # lzfse: smaller and faster to open than zlib; macOS 10.11+
files = [application]
symlinks = {"Applications": "/Applications"}
icon = defines.get("icon")  # noqa: F821
background = defines["background"]  # noqa: F821; background@2x.png is picked up for Retina

window_rect = ((200, 140), (640, 420))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False
include_icon_view_settings = True

arrange_by = None
icon_size = 112
text_size = 13
icon_locations = {
    appname: (165, 205),
    "Applications": (475, 205),
}
