#!/usr/bin/env bash
set -e

CALLER_DIR="$(pwd -P)"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
trap 'cd -- "$CALLER_DIR"' EXIT
cd "$SCRIPT_DIR"

UUID="slobdict@muntashir.dev"

echo "Packing and Installing GNOME Extension..."

# Compile schemas locally first
glib-compile-schemas schemas/

# Pack the extension into a zip file
gnome-extensions pack --force --out-dir="$CALLER_DIR" --extra-source=schemas/

# Force-install the zip
gnome-extensions install --force "$CALLER_DIR/${UUID}.shell-extension.zip"

# Enable it
gnome-extensions enable "$UUID"

echo "Installation complete!"
echo "Wayland users must log out and log back in."
