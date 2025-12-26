#!/usr/bin/bash
set -e

rm -rf build
flatpak-builder --user --install build/ dev.muntashir.SlobDictGTK.yaml
flatpak run dev.muntashir.SlobDictGTK
