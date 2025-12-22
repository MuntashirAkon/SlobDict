# SPDX-License-Identifier: AGPL-3.0-or-later

from gi.repository import Gtk, Gdk
from pathlib import Path
import os
from ..constants import app_id

def load_dark_mode_css() -> str:
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

def get_init_html() -> str:
    html_path = Path(__file__).parent / "intro.html"
    theme_colors = get_theme_colors()
    css_vars = '; '.join([f"{k}: {v}" for k,v in theme_colors.items()])
    try:
        replacements = {
            '.ROOT_CSS{}': f':root {{ {css_vars} }}',
            '{SUBTITLE}': _('Start typing a word in the search field to see its definitions here.'),
            '{HINT}': _('Focus lookup field')
        }
        with open(html_path, 'r') as f:
            text = str(f.read())
            for old, new in replacements.items():
                text = text.replace(old, new)
            return text
    except Exception:
        print(f"intro.html not found at {html_path}")
        return f"<html><body><style>:root {{ {css_vars} }}</style></body></html>"

from gi.repository import Gtk

def get_theme_colors(webview=None):
    # Get realized style context
    temp = Gtk.Window()
    temp.realize()
    style_context = temp.get_style_context()
    temp.destroy()
    
    def get_color(name, fallback):
        try:
            color = style_context.lookup_color(name)[1]
            return color.to_string()
        except:
            return fallback
    
    # Core GTK theme colors
    colors = {
        # Backgrounds
        '--window-bg': get_color('theme_base_color', '#ffffff'),
        '--window-bg-alt': get_color('theme_bg_color', '#f6f6f6'),
        '--card-bg': get_color('theme_selected_bg_color', 'rgba(255,255,255,0.85)'),
        
        # Text
        '--fg-color': get_color('theme_fg_color', '#000000'),
        '--muted-color': get_color('theme_unfocused_fg_color', '#666666'),
        
        # Accents (libadwaita primary blues)
        '--accent-bg': get_color('accent_bg_color', '#3584e4'),
        '--accent-fg': get_color('accent_fg_color', '#ffffff'),
        '--accent-subtle': get_color('accent_color', '#2398f2'),
        
        # Borders & Shadows
        '--border-color': get_color('borders', '#ddd'),
        '--shadow': get_color('shadow', 'rgba(0,0,0,0.1)'),
    }
    
    return colors
