#!/bin/bash
# Build the Linux Island packages into dist/:
#   linux-island_<version>_amd64.deb      Debian, Ubuntu (22.04+), Mint, Pop!_OS, elementary, Zorin, ...
#   linux-island-<version>-x86_64.tar.gz  any distribution: Fedora, Arch, openSUSE, ... (./install.sh)
#
# Qt (PySide6 6.12: Python >= 3.10, glibc >= 2.34), shiboken6 and jeepney are copied from this
# project's .venv (no network needed). They are version-independent (abi3), so the packages run
# with whatever Python 3.10 - 3.15 the system has; nothing is tied to one distribution release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_SITE="${SRC_SITE:-$(echo "$ROOT"/.venv/lib/python3*/site-packages)}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/linux_island/__init__.py")"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
[ -d "$SRC_SITE/PySide6" ] || { echo "PySide6 not found in $SRC_SITE (create .venv first, see README)"; exit 1; }
echo "building linux-island $VERSION"

# --- the bundle: lib/ with Qt, jeepney and the island ------------------------------------------
LIB="$STAGE/lib"
mkdir -p "$LIB"
for item in PySide6 shiboken6 jeepney; do cp -a "$SRC_SITE/$item" "$LIB/"; done
rsync -a --exclude __pycache__ "$ROOT/linux_island" "$LIB/"
P="$LIB/PySide6"
# leave out what the island never uses: Qt's developer tools, translations, headers, stubs
rm -rf "$P"/{assistant,designer,linguist,lrelease,lupdate,qmlformat,qmllint,qmlls,qmltyperegistrar,qmlimportscanner,qmlcachegen,rcc,uic,balsam,balsamui,svgtoqml,androiddeployqt} \
       "$P"/{include,scripts,typesystems,glue,doc,examples} "$P"/*.pyi "$P"/py.typed \
       "$P"/Qt/{translations,metatypes,libexec,mkspecs,include} \
       "$P"/QtDesigner.abi3.so "$P"/QtHelp.abi3.so "$P"/QtUiTools.abi3.so \
       "$P"/Qt/lib/libQt6Designer* "$P"/Qt/lib/libQt6Help.* "$P"/Qt/lib/libQt6UiTools.* \
       "$P"/Qt/lib/libQt6WaylandCompositor* "$P"/Qt/lib/libQt6WaylandEglCompositor* \
       "$P"/Qt/qml/QtWayland "$P"/Qt/plugins/designer "$P"/Qt/plugins/wayland-graphics-integration-server
find "$LIB" -name __pycache__ -prune -exec rm -rf {} +
find "$LIB" -type d -exec chmod 755 {} +
find "$LIB" -type f ! -perm -u+x -exec chmod 644 {} +
mkdir -p "$OUT"

# --- .deb ---------------------------------------------------------------------------------------
PKG="$STAGE/deb"
mkdir -p "$PKG/opt/linux-island"
cp -a "$LIB" "$PKG/opt/linux-island/"
install -d "$PKG/usr/bin"
sed "s|@APP@|/opt/linux-island|" "$ROOT/packaging/linux-island.sh" > "$PKG/usr/bin/linux-island"
chmod 755 "$PKG/usr/bin/linux-island"
install -Dm644 "$ROOT/packaging/linux-island.desktop" "$PKG/usr/share/applications/linux-island.desktop"
install -Dm644 "$ROOT/packaging/linux-island-settings.desktop" "$PKG/usr/share/applications/linux-island-settings.desktop"
install -Dm644 "$ROOT/packaging/linux-island-autostart.desktop" "$PKG/etc/xdg/autostart/linux-island.desktop"
install -Dm644 "$ROOT/linux_island/data/linux-island.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/linux-island.svg"
# GNOME Shell helper extension (window information in Wayland sessions); each user turns it on in Settings
EXT_UUID="$(sed -n 's/.*"uuid": "\(.*\)".*/\1/p' "$ROOT/gnome-extension/"*/metadata.json)"
install -d "$PKG/usr/share/gnome-shell/extensions/$EXT_UUID"
install -m644 "$ROOT/gnome-extension/$EXT_UUID/"{metadata.json,extension.js} "$PKG/usr/share/gnome-shell/extensions/$EXT_UUID/"
DOC="$PKG/usr/share/doc/linux-island"
install -Dm644 "$ROOT/packaging/copyright" "$DOC/copyright"
install -Dm644 "$ROOT/README.md" "$DOC/README.md"
sed "s/@VERSION@/$VERSION/" "$ROOT/packaging/changelog" | gzip -9n > "$DOC/changelog.Debian.gz"
mkdir -p "$PKG/DEBIAN"
SIZE="$(du -sk "$PKG" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" "$ROOT/packaging/control.in" > "$PKG/DEBIAN/control"
echo "/etc/xdg/autostart/linux-island.desktop" > "$PKG/DEBIAN/conffiles"
install -m755 "$ROOT/packaging/postinst" "$PKG/DEBIAN/postinst"
install -m755 "$ROOT/packaging/prerm" "$PKG/DEBIAN/prerm"
find "$PKG" -type d -exec chmod 755 {} +
DEB="$OUT/linux-island_${VERSION}_amd64.deb"
rm -f "$DEB"
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$DEB" >/dev/null
echo "built $DEB ($(du -h "$DEB" | cut -f1))"

# --- universal tarball --------------------------------------------------------------------------------
NAME="linux-island-${VERSION}-x86_64"
TAR="$STAGE/$NAME"
mkdir -p "$TAR"
cp -a "$LIB" "$TAR/"
install -m755 "$ROOT/packaging/install.sh" "$TAR/install.sh"
install -m755 "$ROOT/packaging/linux-island.sh" "$TAR/linux-island.sh"
install -m644 "$ROOT/packaging/"{linux-island.desktop,linux-island-settings.desktop,linux-island-autostart.desktop} "$TAR/"
install -m644 "$ROOT/linux_island/data/linux-island.svg" "$TAR/"
cp -a "$ROOT/gnome-extension" "$TAR/gnome-extension"
install -m644 "$ROOT/README.md" "$TAR/README.md"
install -m644 "$ROOT/packaging/copyright" "$TAR/COPYING"
TGZ="$OUT/$NAME.tar.gz"
tar -C "$STAGE" --owner=0 --group=0 -czf "$TGZ" "$NAME"
echo "built $TGZ ($(du -h "$TGZ" | cut -f1))"
(cd "$OUT" && sha256sum "$(basename "$DEB")" "$(basename "$TGZ")" > SHA256SUMS)
