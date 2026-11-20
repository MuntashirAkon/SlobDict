#!/usr/bin/env bash
set -e

CALLER_DIR="$(pwd -P)"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
trap 'cd -- "$CALLER_DIR"' EXIT
cd "$SCRIPT_DIR"

UUID="slobdict@muntashir.dev"

echo "Packing GNOME Extension..."

# Compile schemas locally first
glib-compile-schemas schemas/

# Pack the extension into a zip file
gnome-extensions pack --force --out-dir="$CALLER_DIR" --extra-source=schemas/

echo "Saved to ${CALLER_DIR}/${UUID}.shell-extension.zip"
