#!/usr/bin/env bash
set -e

UUID="slobdict@muntashir.dev"

echo "Packing and Installing GNOME Extension..."

# Compile schemas locally first
glib-compile-schemas schemas/

# Pack the extension into a zip file
gnome-extensions pack --force --extra-source=schemas/

# Force-install the zip
gnome-extensions install --force "${UUID}.shell-extension.zip"

# Enable it
gnome-extensions enable "$UUID"

echo "Installation complete!"
echo "Wayland users must log out and log back in."