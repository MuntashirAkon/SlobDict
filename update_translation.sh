#!/usr/bin/bash

# 1. Extract strings
meson compile slobdict-pot

# 2. Update all .po files
for po_file in po/*.po; do
    msgmerge -U "$po_file" po/slobdict.pot
done

# 3. Verify each translation
for po_file in po/*.po; do
    echo "=== $po_file ==="
    msgfmt --statistics -c "$po_file"
done
