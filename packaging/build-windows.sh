#!/bin/bash
# Build the Windows package on Linux: dist/linux-island-<version>-windows-x64.zip
#
# Nothing is compiled: it is Python's official embeddable build for Windows, the Windows wheels of
# PySide6 / comtypes / WinRT (unpacked, exactly as pip would install them), and the island itself.
# Unzip it on Windows 10 / 11 (x64) and run install.cmd (per user, no administrator needed).
#
# Downloads are cached in build/windows-cache, so later builds need no network.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/linux_island/__init__.py")"
PY_VERSION="3.12.10"   # the embeddable build; the WinRT wheels below are built for this Python (cp312)
PY_TAG="312"
CACHE="$ROOT/build/windows-cache"
OUT="$ROOT/dist"
NAME="linux-island-$VERSION-windows-x64"
ZIP="$OUT/$NAME.zip"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PIP="$ROOT/.venv/bin/pip"
PYTHON="$ROOT/.venv/bin/python"
WHEELS=(
    "PySide6-Essentials==6.12.0" "shiboken6==6.12.0" "jeepney==0.9.0" "comtypes==1.5.0"
    "typing_extensions>=4.12"
    "winrt-runtime==4.2.0"
    "winrt-Windows.Foundation==4!10.0.28000.2957" "winrt-Windows.Foundation.Collections==4!10.0.28000.2957"
    "winrt-Windows.Media.Control==4!10.0.28000.2957" "winrt-Windows.Storage.Streams==4!10.0.28000.2957"
    "winrt-Windows.Devices.Enumeration==4!10.0.28000.2957" "winrt-Windows.Devices.Bluetooth==4!10.0.28000.2957"
)
echo "building linux-island $VERSION for Windows (Python $PY_VERSION)"

# --- downloads (cached) ----------------------------------------------------------------------
mkdir -p "$CACHE/wheels"
EMBED="$CACHE/python-$PY_VERSION-embed-amd64.zip"
if [ ! -f "$EMBED" ]; then
    curl -fL --retry 3 -o "$EMBED.part" "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"
    mv "$EMBED.part" "$EMBED"
fi
"$PIP" download --quiet --only-binary=:all: --platform win_amd64 --python-version "$PY_TAG" --implementation cp \
    --no-deps -d "$CACHE/wheels" "${WHEELS[@]}"

# --- python/: the embeddable Python, with the wheels in its site-packages ---------------------------
APP="$STAGE/$NAME"
PYDIR="$APP/python"
SITE="$PYDIR/Lib/site-packages"
mkdir -p "$SITE" "$APP/app"
unzip -q "$EMBED" -d "$PYDIR"
for wheel in "$CACHE"/wheels/*.whl; do
    unzip -qo "$wheel" -d "$SITE"
done
rm -rf "$SITE"/*.dist-info/RECORD
# the embeddable Python only searches the paths listed here: add site-packages and the island
printf 'python%s.zip\r\n.\r\nLib\\site-packages\r\n..\\app\r\nimport site\r\n' "$PY_TAG" > "$PYDIR/python$PY_TAG._pth"

# leave out what the island never uses: Qt's developer tools, translations, headers, docs, unused modules
P="$SITE/PySide6"
rm -rf "$P"/*.exe "$P"/*.lib "$P"/include "$P"/doc "$P"/metatypes "$P"/translations "$P"/glue "$P"/typesystems \
       "$P"/opengl32sw.dll "$P"/Qt6Designer*.dll "$P"/Qt6Help.dll "$P"/Qt6UiTools.dll "$P"/QtDesigner.pyd \
       "$P"/QtHelp.pyd "$P"/QtUiTools.pyd "$P"/plugins/designer "$P"/qml/QtQuick/Controls/designer
find "$P" -name "*.pyi" -delete
find "$SITE" -name __pycache__ -prune -exec rm -rf {} +
find "$SITE" -path "*/winrt/__pyinstaller" -prune -exec rm -rf {} +

# --- app/: the island -----------------------------------------------------------------------------
rsync -a --exclude __pycache__ "$ROOT/linux_island" "$APP/app/"
for f in install.ps1 install.cmd linux-island.cmd; do cp "$ROOT/packaging/windows/$f" "$APP/"; done
echo "$VERSION" > "$APP/VERSION"
cp "$ROOT/LICENSE" "$APP/LICENSE.txt"
[ -f "$ROOT/WINDOWS-TESTING.md" ] && cp "$ROOT/WINDOWS-TESTING.md" "$APP/"
"$PYTHON" - "$ROOT/linux_island/data/linux-island.svg" "$APP/linux-island.ico" <<'PY'
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication([])
image = QImage(256, 256, QImage.Format_ARGB32)
image.fill(0)
painter = QPainter(image)
QSvgRenderer(sys.argv[1]).render(painter)
painter.end()
assert image.save(sys.argv[2], "ICO"), "could not write the icon"
PY

# --- zip --------------------------------------------------------------------------------------------
mkdir -p "$OUT"
rm -f "$ZIP"
(cd "$STAGE" && zip -qr -9 "$ZIP" "$NAME")
(cd "$OUT" && sha256sum "$(basename "$ZIP")" > "$NAME.zip.sha256")
echo "built $ZIP ($(du -h "$ZIP" | cut -f1); $(du -sh "$APP" | cut -f1) unpacked)"
