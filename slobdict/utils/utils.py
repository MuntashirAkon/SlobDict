# SPDX-License-Identifier: AGPL-3.0-or-later

from gi.repository import Adw, Gtk, Gdk
from pathlib import Path
import os
from ..constants import app_id


def is_dark_mode() -> bool:
    """Check if the app is in dark mode."""
    style_manager = Adw.StyleManager.get_default()
    return style_manager.get_dark()

def invert_color(color_str: str, hue_rotate_deg: int = 180) -> str:
    """Invert a color"""
    # Parse using GTK
    rgba = Gdk.RGBA()
    if not rgba.parse(color_str):
        rgba.parse('#000000')
    
    r, g, b = rgba.red, rgba.green, rgba.blue
    
    # Invert RGB
    r, g, b = 1 - r, 1 - g, 1 - b

    # Return as hex
    return '#{:02x}{:02x}{:02x}'.format(
        int(r * 255),
        int(g * 255),
        int(b * 255)
    )

def load_dark_mode_css() -> str:
    """Load dark mode CSS file."""
    css_path = Path(__file__).parent / "dark-mode.css"
    try:
        bg_color = invert_color(get_theme_colors()['--color-bg'])
        with open(css_path, 'r') as f:
            return str(f.read()).replace('.ROOT_CSS {}', f':root {{ --color-bg-inverted: {bg_color}; }}')
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

def get_init_html(force_dark: bool) -> str:
    html_path = Path(__file__).parent / "intro.html"
    theme_colors = get_theme_colors()
    if is_dark_mode() and force_dark: # Force dark => color inversion
        css_vars = '; '.join([f"{k}: {invert_color(v)}" for k,v in theme_colors.items()])
    else:
        css_vars = '; '.join([f"{k}: {v}" for k,v in theme_colors.items()])
    try:
        replacements = {
            '.ROOT_CSS {}': f':root {{ {css_vars} }}',
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

def get_theme_colors():
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
        # Text colors
        '--color-text': get_color('theme_fg_color', '#e5e5e5'),
        '--color-text-secondary': get_color('theme_unfocused_fg_color', '#a8a8a8'),
        
        # Backgrounds  
        '--color-bg': get_color('theme_base_color', '#1f1f1f'),
        '--color-bg-alt': get_color('theme_bg_color', '#2a2a2a'),
        '--card-bg': get_color('theme_selected_bg_color', 'rgba(255,255,255,0.85)'),
        
        # Primary/Accent (GTK blue)
        '--color-primary-bg': get_color('accent_bg_color', '#3584e4'),  
        '--color-primary': get_color('accent_fg_color', '#ffffff'),
        '--color-accent': get_color('accent_color', '#3dd5f3'),
        
        # Links (no direct GTK equiv, use accent variant)
        '--color-link-visited': get_color('link_visited_color', '#d78ef0'),
        
        # Borders
        '--color-border': get_color('borders', '#424242'),
        
        # Shadows
        '--shadow': get_color('shadow', 'rgba(0,0,0,0.1)'),
    }
    
    return colors
