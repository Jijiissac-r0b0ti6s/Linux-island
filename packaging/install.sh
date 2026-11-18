#!/bin/sh
# Linux Island installer for any Linux distribution (x86_64, glibc 2.34+, Python 3.10 - 3.15).
#
#   sudo ./install.sh          install for everyone (/opt/linux-island, /usr/local/bin)
#   ./install.sh --user        install just for you, no root (~/.local)
#   ./install.sh --uninstall   (or --user --uninstall) remove it again
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
MODE=system
ACTION=install
for arg in "$@"; do
    case "$arg" in
        --user) MODE=user ;;
        --uninstall) ACTION=uninstall ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [ "$MODE" = system ]; then
    [ "$(id -u)" = 0 ] || { echo "run with sudo for a system install, or use --user" >&2; exit 1; }
    APP=/opt/linux-island
    BIN=/usr/local/bin
    APPS=/usr/local/share/applications
    ICONS=/usr/local/share/icons/hicolor/scalable/apps
    AUTOSTART=/etc/xdg/autostart
else
    DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
    APP="$DATA/linux-island"
    BIN="$HOME/.local/bin"
    APPS="$DATA/applications"
    ICONS="$DATA/icons/hicolor/scalable/apps"
    AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
fi

if [ "$ACTION" = uninstall ]; then
    rm -rf "$APP"
    rm -f "$BIN/linux-island" "$APPS/linux-island.desktop" "$APPS/linux-island-settings.desktop" \
          "$ICONS/linux-island.svg"
    [ "$MODE" = system ] && rm -f "$AUTOSTART/linux-island.desktop"
    echo "Linux Island removed ($MODE). Your settings stay in ~/.config/linux-island."
    exit 0
fi

# checks
PYOK=""
for py in python3 python3.15 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(not ((3,10) <= sys.version_info[:2] < (3,16)))' 2>/dev/null; then
        PYOK="$py"; break
    fi
done
[ -n "$PYOK" ] || { echo "needs Python 3.10 to 3.15 (install python3 first)" >&2; exit 1; }
GLIBC="$(ldd --version 2>/dev/null | head -1 | grep -o '[0-9]*\.[0-9]*$' || echo 0)"
if [ "$(printf '%s\n2.34\n' "$GLIBC" | sort -V | head -1)" != "2.34" ]; then
    echo "needs glibc 2.34 or newer (this system: $GLIBC)" >&2
    exit 1
fi

echo "installing Linux Island ($MODE) into $APP"
rm -rf "$APP"
mkdir -p "$APP" "$BIN" "$APPS" "$ICONS"
cp -a "$HERE/lib" "$APP/"
sed "s|@APP@|$APP|" "$HERE/linux-island.sh" > "$BIN/linux-island"
chmod 755 "$BIN/linux-island"
# menu entries point at the launcher by full path, so they work even if $BIN is not on PATH
for f in linux-island.desktop linux-island-settings.desktop; do
    sed "s|^Exec=linux-island|Exec=$BIN/linux-island|" "$HERE/$f" > "$APPS/$f"
done
cp "$HERE/linux-island.svg" "$ICONS/"
if [ "$MODE" = system ]; then
    mkdir -p "$AUTOSTART"
    sed "s|^Exec=linux-island|Exec=$BIN/linux-island|" "$HERE/linux-island-autostart.desktop" > "$AUTOSTART/linux-island.desktop"
fi
"$PYOK" -m compileall -q "$APP/lib" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$APPS" 2>/dev/null || true

echo
echo "Done. Start it from the app menu (Linux Island), or run: $BIN/linux-island"
[ "$MODE" = user ] && echo "To start it on every login: $BIN/linux-island --autostart on"
echo "Settings: Linux Island Settings in the app menu."
echo
echo "Qt also needs these system libraries (most desktops have them; install if it won't start):"
echo "  Debian/Ubuntu: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0"
echo "  Fedora:        sudo dnf install xcb-util-cursor libxkbcommon-x11 xcb-util-wm xcb-util-keysyms"
echo "  Arch:          sudo pacman -S xcb-util-cursor libxkbcommon-x11 xcb-util-wm xcb-util-keysyms"
echo "  openSUSE:      sudo zypper install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1"
