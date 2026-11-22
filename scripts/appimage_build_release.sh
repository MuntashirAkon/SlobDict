#!/bin/bash
set -e

# Setup Directories & Environment
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export WORKSPACE="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$WORKSPACE"
export APPDIR="${WORKSPACE}/SlobDictGTK.AppDir"
export BUILD_DIR="${WORKSPACE}/builddir"
export SOURCE_DIR="${WORKSPACE}/.appimage-sources"
export APP_PREFIX="/usr"
ICU_VERSION="79.1"
LZO_VERSION="2.10"
XAPIAN_VERSION="1.4.32"
LIBZIM_VERSION="9.8.2"
BLUEPRINT_VERSION="v0.22.2"
LIBADWAITA_VERSION="1.10.0"

# Clean up previous builds
rm -rf "$APPDIR" "$BUILD_DIR" "$SOURCE_DIR"
mkdir -p "$APPDIR$APP_PREFIX"
mkdir -p "$SOURCE_DIR"

# Tell compilers/pkg-config to look inside our AppDir for newly built dependencies
export PKG_CONFIG_PATH="${APPDIR}${APP_PREFIX}/lib64/pkgconfig:${APPDIR}${APP_PREFIX}/lib/pkgconfig:${APPDIR}${APP_PREFIX}/share/pkgconfig:${PKG_CONFIG_PATH}"
export CFLAGS="-I${APPDIR}${APP_PREFIX}/include ${CFLAGS}"
export CXXFLAGS="-I${APPDIR}${APP_PREFIX}/include ${CXXFLAGS}"
export LDFLAGS="-L${APPDIR}${APP_PREFIX}/lib64 -L${APPDIR}${APP_PREFIX}/lib ${LDFLAGS}"

# Tell the dynamic linker where to find the freshly built .so files during the build
export LD_LIBRARY_PATH="${APPDIR}${APP_PREFIX}/lib64:${APPDIR}${APP_PREFIX}/lib:${LD_LIBRARY_PATH}"

# Ensure binaries like blueprint-compiler are found
export PATH="${APPDIR}${APP_PREFIX}/bin:$PATH"

echo "=== Building Dependencies ==="

download_if_missing() {
  local url="$1"
  local file="${url##*/}"
  if [ ! -f "$SOURCE_DIR/$file" ]; then
    wget -O "$SOURCE_DIR/$file" "$url"
  fi
}

# ICU
echo "Building ICU..."
download_if_missing "https://github.com/unicode-org/icu/releases/download/release-${ICU_VERSION}/icu4c-${ICU_VERSION}-sources.tgz"
tar -xf "$SOURCE_DIR/icu4c-${ICU_VERSION}-sources.tgz" -C "$SOURCE_DIR"
cd "$SOURCE_DIR/icu/source"
./configure --prefix=$APP_PREFIX --disable-samples --disable-tests --enable-shared --disable-static
make -j$(nproc)
make install DESTDIR="$APPDIR"
cd "$WORKSPACE"

# LZO
echo "Building LZO..."
download_if_missing "https://www.oberhumer.com/opensource/lzo/download/lzo-${LZO_VERSION}.tar.gz"
mkdir -p "$SOURCE_DIR/lzo"
tar -xf "$SOURCE_DIR/lzo-${LZO_VERSION}.tar.gz" -C "$SOURCE_DIR/lzo"
cd "$SOURCE_DIR/lzo/lzo-${LZO_VERSION}"
./configure --prefix=$APP_PREFIX --enable-shared --disable-static
make -j$(nproc)
make install DESTDIR="$APPDIR"
cd "$WORKSPACE"

# Xapian-core
echo "Building Xapian..."
download_if_missing "https://oligarchy.co.uk/xapian/${XAPIAN_VERSION}/xapian-core-${XAPIAN_VERSION}.tar.xz"
mkdir -p "$SOURCE_DIR/xapian"
tar -xf "$SOURCE_DIR/xapian-core-${XAPIAN_VERSION}.tar.xz" -C "$SOURCE_DIR/xapian"
cd "$SOURCE_DIR/xapian/xapian-core-${XAPIAN_VERSION}"
./configure --prefix=$APP_PREFIX --disable-sse --disable-backend-chert --disable-backend-remote --disable-documentation
make -j$(nproc)
make install DESTDIR="$APPDIR"
cd "$WORKSPACE"

# Libzim
echo "Building Libzim..."
if [ ! -d "libzim" ]; then
  git clone --branch "$LIBZIM_VERSION" --depth 1 https://github.com/openzim/libzim.git
fi
git -C libzim fetch --tags --force
git -C libzim checkout --detach "$LIBZIM_VERSION"
cd libzim
# Meson needs to be told about the custom LDFLAGS from the Flatpak manifest (Updated for lib64)
export LDFLAGS="-L${APPDIR}${APP_PREFIX}/lib64 -L${APPDIR}${APP_PREFIX}/lib -licui18n -licuuc -licudata"
meson setup "$BUILD_DIR/libzim" --prefix="$APP_PREFIX" --wrap-mode=nodownload -Dtest_data_dir=none
meson compile -C "$BUILD_DIR/libzim"
DESTDIR="$APPDIR" meson install -C "$BUILD_DIR/libzim"
cd "$WORKSPACE"

# Reset LDFLAGS back to normal for the rest of the build
export LDFLAGS="-L${APPDIR}${APP_PREFIX}/lib64 -L${APPDIR}${APP_PREFIX}/lib"

#  Blueprint Compiler
echo "Building Blueprint Compiler..."
# Use the system Python: its PyGObject installation is available to the
# blueprint-compiler launcher, unlike the separate Homebrew Python.
export PATH="/usr/bin:$PATH"
if [ ! -d "blueprint-compiler" ]; then
  git clone --branch "$BLUEPRINT_VERSION" --depth 1 https://gitlab.gnome.org/jwestman/blueprint-compiler.git
fi
git -C blueprint-compiler fetch --tags --force
git -C blueprint-compiler checkout --detach "$BLUEPRINT_VERSION"
cd blueprint-compiler
meson setup "$BUILD_DIR/blueprint-compiler" --prefix="$APP_PREFIX"
meson compile -C "$BUILD_DIR/blueprint-compiler"
# Blueprint Compiler is a build-time tool. Use the build-tree launcher and
# source package, rather than installing it into the AppDir with the host
# Python's absolute site-packages path.
export PYTHONPATH="$WORKSPACE/blueprint-compiler:$BUILD_DIR/blueprint-compiler${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$BUILD_DIR/blueprint-compiler:$PATH"
cd "$WORKSPACE"

# Main App
echo "Building Slob Dictionary..."
# Ensure blueprint-compiler is explicitly accessible to Meson
meson setup "${BUILD_DIR}/slobdict" "$WORKSPACE/app" \
  --prefix=$APP_PREFIX \
  -Dbuildtype=release \
  --wrap-mode=nodownload

meson compile -C "${BUILD_DIR}/slobdict"
DESTDIR="$APPDIR" meson install -C "${BUILD_DIR}/slobdict"

chmod +x "$APPDIR/usr/bin/slobdict"

# Normalize Library Paths for AppImage
echo "Merging lib64 into lib..."
if [ -d "$APPDIR/usr/lib64" ]; then
    # Move everything to the standard AppImage lib folder before removing lib64.
    mkdir -p "$APPDIR/usr/lib"
    cp -a "$APPDIR/usr/lib64/." "$APPDIR/usr/lib/"
    rm -rf "$APPDIR/usr/lib64"
fi

# LinuxDeploy & GTK and Conda Plugin
echo "Preparing AppDir with linuxdeploy..."
unset LD_LIBRARY_PATH
unset PYTHONPATH
export PATH=$(pwd):$PATH
APPIMAGE_PIP_REQUIREMENTS="$SOURCE_DIR/appimage-requirements.txt"
sed '/^[[:space:]]*pyicu[[:space:]]*$/Id' "$WORKSPACE/app/requirements.txt" > "$APPIMAGE_PIP_REQUIREMENTS"
export PIP_REQUIREMENTS="-r $APPIMAGE_PIP_REQUIREMENTS -r $WORKSPACE/app/pyglossary-plugins.txt"
# linuxdeploy-plugin-conda adds conda-forge itself. Avoid adding it a second
# time, which can move it behind defaults in Conda's channel list.
unset CONDA_CHANNELS
export CONDA_CHANNEL_PRIORITY=strict
# Install PyICU from the same Conda environment as its ICU runtime. Building
# PyICU with pip here can pick up ICU headers from the AppDir while linking to
# Conda's different ICU SONAME, causing an undefined symbol at startup.
export CONDA_PACKAGES="glib;gtk4;pygobject;pyicu"
export CONDA_PLUGINS_AUTO_ACCEPT_TOS=true

# slobdict is a python script which LinuxDeploy hates
# So, use a dummy ELF binary (i.e., true) temporarily
mv "$APPDIR/usr/bin/slobdict" "$APPDIR/usr/bin/slobdict.py"
cp $(which true) "$APPDIR/usr/bin/slobdict"
export NO_STRIP=1

# Deploy the Conda runtime without linuxdeploy's separate GTK runtime.
LD_LIBRARY_PATH="$APPDIR/usr/lib" ./linuxdeploy-x86_64.AppImage \
  --appdir="$APPDIR" \
  --executable="$APPDIR/usr/bin/slobdict" \
  --deploy-deps-only="$APPDIR/usr/lib" \
  --desktop-file="$APPDIR/usr/share/applications/dev.muntashir.SlobDictGTK.desktop" \
  --icon-file="$APPDIR/usr/share/icons/hicolor/scalable/apps/dev.muntashir.SlobDictGTK.svg" \
  --plugin conda

# Build libadwaita against the GTK/GLib libraries in the Conda prefix. This
# avoids mixing Conda's PyGObject with a second GTK stack from linuxdeploy.
echo "Building Libadwaita against Conda GTK..."
if [ ! -d "libadwaita" ]; then
  git clone --branch "$LIBADWAITA_VERSION" --depth 1 https://gitlab.gnome.org/GNOME/libadwaita.git
fi
git -C libadwaita fetch --tags --force
git -C libadwaita checkout --detach "$LIBADWAITA_VERSION"
cd libadwaita
CONDA_PREFIX="$APPDIR/usr/conda"
export PKG_CONFIG_PATH="$CONDA_PREFIX/lib/pkgconfig:$CONDA_PREFIX/share/pkgconfig:$PKG_CONFIG_PATH"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$APPDIR/usr/lib"
export PATH="$CONDA_PREFIX/bin:/usr/bin:$PATH"
meson setup "$BUILD_DIR/libadwaita" --prefix=/usr/conda --libdir=lib \
  -Dtests=false -Dexamples=false -Dvapi=false
meson compile -C "$BUILD_DIR/libadwaita"
DESTDIR="$APPDIR" meson install -C "$BUILD_DIR/libadwaita"
cd "$WORKSPACE"

# Make the app's schema visible alongside the Conda GTK schemas.
CONDA_SCHEMA_DIR="$APPDIR/usr/conda/share/glib-2.0/schemas"
cp "$APPDIR/usr/share/glib-2.0/schemas/dev.muntashir.SlobDictGTK.gschema.xml" \
  "$CONDA_SCHEMA_DIR/"
"$APPDIR/usr/conda/bin/glib-compile-schemas" "$CONDA_SCHEMA_DIR"

# Drop build-only GTK/Adwaita development files and demo executables from the
# runtime bundle. Keep typelibs and runtime libraries used by PyGObject.
rm -rf "$APPDIR/usr/conda/include" \
  "$APPDIR/usr/conda/share/gir-1.0" \
  "$APPDIR/usr/conda/lib/pkgconfig" \
  "$APPDIR/usr/conda/share/pkgconfig" \
  "$APPDIR/usr/conda/lib/cmake"
for gtk_tool in gtk4-builder-tool gtk4-demo gtk4-demo-application gtk4-image-tool \
  gtk4-launch gtk4-node-editor gtk4-path-tool gtk4-print-editor \
  gtk4-query-settings gtk4-rendernode-tool gtk4-update-icon-cache \
  gtk4-widget-factory; do
  rm -f "$APPDIR/usr/conda/bin/$gtk_tool" "$APPDIR/usr/bin/$gtk_tool"
done

# Run the bundled GTK/GLib stack without linuxdeploy's separate GTK runtime.
# linuxdeploy leaves AppRun as a symlink to the selected executable, so remove
# it before writing the shell wrapper below.
rm -f "$APPDIR/AppRun"
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
set -e

APPDIR="${APPDIR:-$(dirname "$(readlink -f "$0")")}"
export APPDIR
export PATH="$APPDIR/usr/bin:$APPDIR/usr/conda/bin:${PATH:-/usr/bin:/bin}"
export XDG_DATA_DIRS="$APPDIR/usr/conda/share:$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export GSETTINGS_SCHEMA_DIR="$APPDIR/usr/conda/share/glib-2.0/schemas"
export GTK_DATA_PREFIX="$APPDIR/usr/conda"
export GTK_EXE_PREFIX="$APPDIR/usr/conda"
GI_TYPELIB_PATH="$APPDIR/usr/conda/lib/girepository-1.0"
for typelib_dir in /usr/lib/girepository-1.0 /usr/lib64/girepository-1.0 /usr/lib/*/girepository-1.0; do
  if [ -d "$typelib_dir" ]; then
    GI_TYPELIB_PATH="$GI_TYPELIB_PATH:$typelib_dir"
  fi
done
export GI_TYPELIB_PATH
export XCURSOR_PATH="/usr/share/icons:/usr/share/pixmaps:${HOME:+$HOME/.icons:$HOME/.local/share/icons}"
export PYTHONNOUSERSITE=1
unset GTK_THEME

exec "$APPDIR/usr/bin/slobdict" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Restore the actual Python script
rm "$APPDIR/usr/bin/slobdict"
mv "$APPDIR/usr/bin/slobdict.py" "$APPDIR/usr/bin/slobdict"
chmod +x "$APPDIR/usr/bin/slobdict"

# Prevent the IBus segfault if an input method package provides this module.
rm -f "$APPDIR/usr/conda/lib/gtk-4.0/4.0.0/immodules/libim-ibus.so"

# Final AppImage Generation
echo "Bundling the final AppImage..."
# We use appimagetool natively here because it doesn't parse ELF files,
# it just packages the prepared directory perfectly.

if [ ! -f "appimagetool-x86_64.AppImage" ]; then
  wget -nc https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x appimagetool-x86_64.AppImage
fi

APPIMAGE_EXTRACT_AND_RUN=1 ./appimagetool-x86_64.AppImage "$APPDIR"
