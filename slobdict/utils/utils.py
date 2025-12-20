# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path
import os

from ..constants import app_id

def load_dark_mode_css():
    """Load dark mode CSS file."""
    css_path = Path(__file__).parent / "dark-mode.css"
    try:
        with open(css_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Dark mode CSS not found at {css_path}")
        return ""

def get_config_dir():
    """Use Flatpak sandbox directory when available."""    
    # Check if running in Flatpak
    if os.path.exists('/.flatpak-info'):
        config_dir = Path.home() / '.var' / 'app' / app_id
    else:
        config_dir = Path.home() / '.config' / 'slobdict'
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
