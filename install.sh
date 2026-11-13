#!/bin/bash
# Copies the script into Ableton's User Library, where Live looks for custom control surfaces.
# Live lists it by its folder name, shown as "Launchkey Seq".
#
#   ./install.sh               normal install
#   ./install.sh --dev-bridge  also adds the hook the in-Live tests (tests/live) drive it through
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$HERE/Launchkey_MK3_Step"
TARGET="$HOME/Music/Ableton/User Library/Remote Scripts/Launchkey_Seq"

mkdir -p "$TARGET"
rsync -a --delete --exclude '__pycache__' "$SOURCE/" "$TARGET/"
if [ "${1:-}" = "--dev-bridge" ]; then
    cp "$HERE/tests/live/dev_bridge.py" "$TARGET/"
    echo "Dev bridge added (for tests only; run ./install.sh again to remove it)."
fi
echo "Installed to: $TARGET"
echo "Restart Live, then pick 'Launchkey Seq' as the control surface."
