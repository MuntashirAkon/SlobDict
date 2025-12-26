#!/usr/bin/bash
set -e

meson setup builddir --wipe
meson compile slobdict-pot -C builddir
meson configure builddir -Dprefix="$(pwd)/builddir" -Dbuildtype=debug
meson compile -C builddir mypy
ninja -C builddir install

pkill -f "python3 /app/bin/slobdict"
pkill -f "python /app/bin/slobdict"
ninja -C builddir run