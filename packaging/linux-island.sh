#!/bin/sh
# Linux Island launcher. Works with any Python 3.10 - 3.15 on the system; Qt (PySide6) is bundled.
APP="${LINUX_ISLAND_HOME:-@APP@}"

PY=""
for candidate in python3 python3.15 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] < (3, 16)))' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "linux-island needs Python 3.10 to 3.15 (python3)" >&2
    exit 1
fi

# X11 for now: in a Wayland session, run through XWayland
if [ -n "$WAYLAND_DISPLAY" ] && [ -z "$QT_QPA_PLATFORM" ]; then
    export QT_QPA_PLATFORM=xcb
fi

export LINUX_ISLAND_LAUNCHER="$(readlink -f "$0" 2>/dev/null || echo "$0")"
export PYTHONPATH="$APP/lib${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -s -m linux_island "$@"
