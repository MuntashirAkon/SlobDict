#!/usr/bin/env bash
set -e

UUID="slobdict@muntashir.dev"

echo "Packing GNOME Extension..."

# Compile schemas locally first
glib-compile-schemas schemas/

# Pack the extension into a zip file
gnome-extensions pack --force --extra-source=schemas/

echo "Saved to $(pwd)/${UUID}.shell-extension.zip"