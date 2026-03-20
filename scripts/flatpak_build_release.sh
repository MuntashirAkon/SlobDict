#!/bin/bash
set -e

# Necessary to update constants.py
meson setup builddir --wipe
meson configure builddir -Dprefix="$(pwd)/builddir" -Dbuildtype=debug
VERSION=$(grep version builddir/slobdict/constants.py | awk -F'"' '{print $2}')

# Build the actual flatpak
flatpak-builder --repo=repo build/ --force-clean dev.muntashir.SlobDictGTK.yaml
flatpak build-bundle repo/ SlobDictGTK-${VERSION}.flatpak dev.muntashir.SlobDictGTK
echo "Created SlobDictGTK-${VERSION}.flatpak"
