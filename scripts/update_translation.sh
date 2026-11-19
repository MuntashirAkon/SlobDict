#!/usr/bin/bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
APP_DIR="$REPO_DIR/app"
BUILD_DIR="$REPO_DIR/builddir"

# 1. Extract strings
meson compile -C "$BUILD_DIR" slobdict-pot

# 2. Update all .po files
for po_file in "$APP_DIR"/po/*.po; do
    msgmerge -U "$po_file" "$APP_DIR/po/slobdict.pot"
done

# 3. Verify each translation
for po_file in "$APP_DIR"/po/*.po; do
    echo "=== $po_file ==="
    msgfmt --statistics -c "$po_file"
done
