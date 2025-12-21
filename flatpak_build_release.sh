#!/bin/bash
VERSION=$(grep version slobdict/constants.py | awk -F'"' '{print $2}')
flatpak-builder --repo=repo build/ dev.muntashir.SlobDictGTK.yaml && \
flatpak build-bundle repo/ SlobDictGTK-${VERSION}.flatpak dev.muntashir.SlobDictGTK && \
echo "Created SlobDictGTK-${VERSION}.flatpak"
