#!/usr/bin/bash

if [ -d builddir ]; then
    meson setup builddir --wipe
else
    meson setup builddir
fi
meson compile slobdict-pot -C builddir
meson configure builddir -Dprefix="$(pwd)/builddir" -Dbuildtype=debug
ninja -C builddir install

pkill -f "python3 /app/bin/slobdict"
pkill -f "python /app/bin/slobdict"
ninja -C builddir run