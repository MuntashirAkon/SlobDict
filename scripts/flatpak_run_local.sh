#!/usr/bin/bash
set -e

rm -rf build
flatpak-builder --user --install build/ app/dev.muntashir.SlobDictGTK.yaml
flatpak run dev.muntashir.SlobDictGTK
