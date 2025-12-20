# Slob Dictionary

A `.slob` file viewer (e.g., a dictionary app) for Linux in GTK.

## Building

### Install dependencies

```sh
sudo dnf install gtk4-devel libadwaita-devel python3-gobject
sudo dnf install gcc-c++ libicu-devel python3-devel
sudo dnf install meson ninja-build
```

### Build and Run Locally

```sh
./mason_run_local.sh
```

or

```sh
./flatpak_run_local.sh
```

### Build Flatpak

```sh
./flatpak_build_release.sh
```

## Credits

This project followed a template from https://github.com/timlau/adw_template_app.

## License

AGPL-3.0-or-later
