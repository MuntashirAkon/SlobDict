#!/usr/bin/bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
APP_DIR="$REPO_DIR/app"
BUILD_DIR="$REPO_DIR/builddir"

meson setup "$BUILD_DIR" "$APP_DIR" --wipe
meson compile slobdict-pot -C "$BUILD_DIR"
meson configure "$BUILD_DIR" -Dprefix="$BUILD_DIR" -Dbuildtype=debug
meson compile -C "$BUILD_DIR" mypy
ninja -C "$BUILD_DIR" install

pkill -f "python3 /app/bin/slobdict"
pkill -f "python /app/bin/slobdict"
ninja -C "$BUILD_DIR" run
