# SPDX-License-Identifier: AGPL-3.0-or-later

from gi.repository import Adw, Gtk, Gdk
from pathlib import Path
from typing import Callable, Optional
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

def html_to_text(html_content: str) -> str:
    """
    Extract clean plain text from HTML.
    
    Removes tags, normalizes whitespace, preserves readability.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove unwanted elements (scripts, styles, navigation)
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()
        
        # Get all text content
        text = soup.get_text(separator=' ', strip=True)
        
        # Clean up excessive whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk).strip()
        
        return text
    except Exception as e:
        print(f"HTML parsing error: {e}")
        # Fallback: remove tags with regex
        import re
        return re.sub(r'<[^>]+>', '', html_content).strip()

def inline_stylesheets(
    html: str,
    *,
    extra_css: str = None,
    on_css: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """
    Replace <link rel="stylesheet" href="..."> tags with <style> blocks.
    Then inline them to their corresponding tags.

    Parameters
    ----------
    html : str
        Original HTML content.
    on_css : callable, optional
        Callback invoked for each external stylesheet href.
        Signature: on_css(href: str) -> Optional[str]
        - href: the href attribute value from the <link> tag
        - Returns: CSS text to embed, or None to skip this stylesheet
        If not provided, all external CSS is ignored.

    Returns
    -------
    str
        Modified HTML with embedded <style> blocks instead of <link>.
    """
    from bs4 import BeautifulSoup
    from premailer import transform

    soup = BeautifulSoup(html, "lxml")

    for link in list(soup.find_all("link", rel=lambda v: v and "stylesheet" in v)):
        href = link.get("href")
        if not href:
            continue

        # Invoke callback
        if on_css is None:
            link.decompose()
            continue

        css_text = on_css(href)
        if css_text is None:
            link.decompose()
            continue

        # Embed the CSS
        style_tag = soup.new_tag("style", type="text/css")
        style_tag.string = css_text

        link.insert_before(style_tag)
        link.decompose()

    return transform(str(soup), remove_classes=True, allow_network=False)

def transform_css_to_semantic_html(html: str) -> str:
    """
    Transform elements based on their CSS property.
    """
    from bs4 import BeautifulSoup
    import cssutils
    import logging

    cssutils.log.setLevel(logging.CRITICAL)

    soup = BeautifulSoup(html, "lxml")
    
    # Structural tags that should not be turned into div/span
    protected_tags = {'table', 'tr', 'td', 'th', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    for elem in list(soup.find_all(True)):
        style_str = elem.get("style", "")
        if not style_str:
            continue
            
        style = cssutils.parseStyle(style_str)
        
        # 1. Handle Visibility (Highest Priority)
        display = style.getPropertyValue("display").lower()
        if display == "none":
            elem.decompose()
            continue

        # 2. Handle Semantic Styles (Apply to ALL tags, including protected ones)
        # Handle Bold
        weight = style.getPropertyValue("font-weight").lower()
        if weight in ('bold', 'bolder') or (weight.isdigit() and int(weight) >= 600):
            elem.wrap(soup.new_tag("strong"))

        # Handle Italics
        font_style = style.getPropertyValue("font-style").lower()
        if font_style in ('italic', 'oblique'):
            elem.wrap(soup.new_tag("em"))

        # Handle Text Decoration (underline, line-through)
        text_decoration = style.getPropertyValue("text-decoration").lower()
        if "underline" in text_decoration:
            elem.wrap(soup.new_tag("u"))
        if "line-through" in text_decoration:
            elem.wrap(soup.new_tag("s"))

        # 3. Handle Display-based Renaming (Skip if tag is protected)
        if elem.name not in protected_tags:
            if display in ("block", "flex", "grid", "inline-block"):
                elem.name = "div"
            elif display == "inline":
                elem.name = "span"

    return str(soup)

def html_to_markdown(html_str: str) -> str:
    """
    Convert HTML to markdown
    """
    from markdownify import markdownify as md
    return md(transform_css_to_semantic_html(html_str))
