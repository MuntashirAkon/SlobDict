#!/bin/bash
VERSION="0.1.0"
flatpak-builder --repo=repo build/ dev.muntashir.SlobDictGTK.yaml && \
flatpak build-bundle repo/ SlobDictGTK-${VERSION}.flatpak dev.muntashir.SlobDictGTK && \
echo "Created SlobDictGTK-${VERSION}.flatpak"
