# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")

from gi.repository import Gtk, Adw, WebKit, Gio, GLib, Gdk
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse
from ..backend.slob_client import SlobClient
from ..backend.http_server import HTTPServer_
from ..backend.bookmarks_db import BookmarksDB
from ..backend.history_db import HistoryDB
from ..constants import app_label, rootdir


@Gtk.Template(resource_path=rootdir + "/ui/window.ui")
class MainWindow(Adw.ApplicationWindow):
    """Main dictionary window with sidebar, search, and webview."""

    __gtype_name__ = "MainWindow"

    # Template child bindings
    sidebar_toolbar_view = Gtk.Template.Child()
    sidebar_header = Gtk.Template.Child()
    sidebar_menu_button = Gtk.Template.Child()
    content_toolbar_view = Gtk.Template.Child()
    content_header = Gtk.Template.Child()
    bookmark_button = Gtk.Template.Child()
    back_button = Gtk.Template.Child()
    forward_button = Gtk.Template.Child()
    nav_buttons_box = Gtk.Template.Child()
    search_entry = Gtk.Template.Child()
    history_search_entry = Gtk.Template.Child()
    results_list = Gtk.Template.Child()
    webview_container = Gtk.Template.Child()

    def __init__(self, application, settings_manager):
        super().__init__(application=application)
        
        self.settings_manager = settings_manager

        # Load custom CSS
        css_provider = Gtk.CssProvider()
        css_file = Path(__file__).parent / "style.css"
        css_provider.load_from_path(str(css_file))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # State
        self.current_view = "lookup"
        self.search_query = ""
        self.row_to_result = {}
        self.navigation_history = []  # For back/forward
        self.current_history_index = -1
        self.current_entry = None  # Track current entry being displayed

        # Track pending tasks for cancellation
        self.pending_search_task = None
        self.pending_lookup_task = None
        self.request_counter = 0
        self.current_search_request_id = None
        self.current_lookup_request_id = None

        # Initialize slob backend
        self.slob_client = SlobClient(self._on_dictionary_updated)

        # Initialize DB
        self.bookmarks_db = BookmarksDB()
        self.history_db = HistoryDB()

        # Initialize HTTP server
        self.http_server = HTTPServer_(self.slob_client, port=settings_manager.get('port', 8013))
        self.http_server.start()
        # Store the actual port
        self.http_port = self.http_server.get_port()
        self.connect("close-request", self._on_close)

        # Thread pool executor for background tasks
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Setup UI elements
        self._setup_ui()
        
        # Setup menu
        self._setup_menu()

        self.connect("show", self.on_window_shown)

        # Register for settings changes
        self.settings_manager.register_callback('force_dark_mode', self._on_force_dark_changed)
        self.settings_manager.register_callback('enable_javascript', self._on_javascript_changed)
        self.settings_manager.register_callback('load_remote_content', self._on_remote_content_changed)

    def _setup_ui(self):
        """Setup UI elements from template."""
        # Connect button signals
        self.back_button.connect("clicked", self._on_back_clicked)
        self.forward_button.connect("clicked", self._on_forward_clicked)
        self.bookmark_button.connect("clicked", self._on_bookmark_clicked)

        # Connect search signals
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.history_search_entry.connect("search-changed", self._on_history_search_changed)

        # Connect results list
        self.results_list.connect("row-selected", self._on_result_selected)

        # Create and add webview
        try:
            self.webview = WebKit.WebView()
            self._apply_webview_settings()

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_child(self.webview)
            scrolled.set_hexpand(True)
            scrolled.set_vexpand(True)
            
            self.webview_container.append(scrolled)
        except Exception as e:
            label = Gtk.Label(label=_("WebKit unavailable: %s") % str(e))
            label.set_hexpand(True)
            label.set_vexpand(True)
            self.webview_container.append(label)

        # Update next/prev buttons
        self._update_nav_buttons()

    def _setup_menu(self):
        """Setup application menu."""
        if self.sidebar_menu_button:
            self.sidebar_menu_button.set_menu_model(self._create_menu_model())


    def _create_menu_model(self):
        """Create main menu model."""
        menu = Gio.Menu()

        # View mode section
        view_section = Gio.Menu()
        view_section.append(_("Lookup"), "app.lookup")
        view_section.append(_("Bookmarks"), "app.bookmarks")
        view_section.append(_("History"), "app.history")
        menu.append_section(None, view_section)

        # Settings section
        settings_section = Gio.Menu()
        settings_section.append(_("Dictionaries"), "app.dictionaries")
        settings_section.append(_("Preferences"), "app.preferences")
        settings_section.append(_("Keyboard Shortcuts"), "app.shortcuts")
        settings_section.append(_("About %s") % app_label, "app.about")
        menu.append_section(None, settings_section)

        # Actions section
        actions_section = Gio.Menu()
        actions_section.append(_("Quit"), "app.quit")
        menu.append_section(None, actions_section)

        return menu

    def _update_sidebar_title(self):
        """Update sidebar title based on current view."""
        title_widget = self.sidebar_header.get_title_widget()
        if isinstance(title_widget, Adw.WindowTitle):
            if self.current_view == "lookup":
                title_widget.set_title(_("Lookup"))
            elif self.current_view == "bookmarks":
                title_widget.set_title(_("Bookmarks"))
            else:
                title_widget.set_title(_("History"))

    def _apply_webview_settings(self):
        """Apply user preferences to WebView."""
        settings = self.webview.get_settings()
        
        # Force dark mode
        force_dark = self.settings_manager.get('force_dark_mode', True)
        self.http_server.set_dark_mode(force_dark)

        if force_dark:
            from ..utils.utils import load_dark_mode_css
            self.webview.load_html(f"<html><body><style>{load_dark_mode_css()}</style></body></html>")
        else:
            self.webview.load_html("<html></html>")
        
        # Enable/disable JavaScript
        enable_js = self.settings_manager.get('enable_javascript', True)
        settings.set_property("enable-javascript", enable_js)
        
        # Load remote content
        self.load_remote = self.settings_manager.get('load_remote_content', False)
        self.webview.connect("resource-load-started", self._on_resource_load_started)

        # Context menu
        self.webview.connect("context-menu", self._on_context_menu)

    def _on_context_menu(self, webview, context_menu, hit_test_result):
        """Handle WebView context menu customization."""
        try:
            # Add Lookup option
            if hit_test_result.context_is_selection() and self.settings_manager.get('enable_javascript', True):
                lookup_action = Gio.SimpleAction.new("lookup", None)
                lookup_action.connect("activate", self._on_lookup_selected)
                lookup_item = WebKit.ContextMenuItem.new_from_gaction(
                    lookup_action,
                    _("Lookup"),
                    None
                )
                context_menu.append(lookup_item)

            # Add Open Link option
            if hit_test_result.context_is_link():
                open_link_item = WebKit.ContextMenuItem.new_from_gaction(
                    Gio.SimpleAction.new("open-link", None),
                    _("Open Link"),
                    None
                )
                context_menu.append(open_link_item)
            
            return False
        except Exception as e:
            print(f"Error in context menu: {e}")
            return False

    def _on_lookup_selected(self, action, param):
        """Handle Lookup action from context menu."""
        try:
            # Get currently selected text from WebView
            # JavaScript to get selected text as a string
            js_code = "window.getSelection().toString();"
            
            # In WebKit 6.0, evaluate_javascript is the standard
            self.webview.evaluate_javascript(
                js_code, 
                -1,      # Length of string (-1 for null-terminated)
                None,    # World name (None for default)
                None,    # Source URI
                None,    # Cancellable
                self._on_get_selection_for_lookup
            )
        except Exception as e:
            print(f"Error in lookup: {e}")
    
    def _on_get_selection_for_lookup(self, webview, result):
        """Callback to process selected text."""
        try:
            selected_text = webview.evaluate_javascript_finish(result).to_string()
            if not selected_text or selected_text.strip() == "":
                return
            
            # Switch to lookup view and search
            self.current_view = "lookup"
            self._update_sidebar_title()
            self.search_entry.set_visible(True)
            self.history_search_entry.set_visible(False)
            
            # Set search text
            self.search_entry.set_text(selected_text.strip())
        except Exception as e:
            print(f"Error in lookup: {e}")

    def _on_force_dark_changed(self, key, value):
        """Handle force dark mode setting change."""
        force_dark = self.settings_manager.get('force_dark_mode', True)
        self.http_server.set_dark_mode(force_dark)
        if hasattr(self, 'webview'):
            manager = self.webview.get_network_session().get_website_data_manager()
            data_types = WebKit.WebsiteDataTypes.DISK_CACHE | WebKit.WebsiteDataTypes.MEMORY_CACHE
            manager.clear(data_types, 0, None, None, None)
            if self.webview.get_uri() is None or self.webview.get_uri() == "about:blank":
                if force_dark:
                    from ..utils.css_utils import load_dark_mode_css
                    self.webview.load_html(f"<html><body><style>{load_dark_mode_css()}</style></body></html>")
                else:
                    self.webview.load_html("<html></html>")
            else:
                self.webview.reload()

    def _on_javascript_changed(self, key, value):
        """Handle JavaScript setting change."""
        if hasattr(self, 'webview'):
            settings = self.webview.get_settings()
            settings.set_property("enable-javascript", value)

    def _on_remote_content_changed(self, key, value):
        """Handle remote content setting change."""
        self.load_remote = value

    def _on_resource_load_started(self, webview, resource, request):
        uri = request.get_uri()
        if not self.load_remote and uri and not (uri.startswith("http://127.0.0.1")):
            print(f"Blocking remote resource: {uri}")
            # Blocks remote resources by redirecting them
            request.set_uri("about:blank")

    def _on_dictionary_updated(self):
        if hasattr(self, 'search_entry'):
            self._on_search_changed(self.search_entry)
        if hasattr(self, 'history_search_entry'):
            self._on_history_search_changed(self.history_search_entry)

    def on_window_shown(self, widget):
        """Focus search entry when window is shown."""
        self.search_entry.grab_focus()

    def _on_back_clicked(self, button):
        """Navigate to previous entry in history."""
        if hasattr(self, 'webview'):
            self.webview.go_back()
            subtitle = ""
            if self.current_history_index > 0:
                self.current_history_index -= 1
                entry = self.navigation_history[self.current_history_index]
                subtitle = entry.get('title', '')
                self.current_entry = entry
                self._update_bookmark_button()
            self._update_content_subtitle(subtitle)
            self._update_nav_buttons()

    def _on_forward_clicked(self, button):
        """Navigate to next entry in history."""
        if hasattr(self, 'webview'):
            self.webview.go_forward()
            subtitle = ""
            if self.current_history_index < len(self.navigation_history) - 1:
                self.current_history_index += 1
                entry = self.navigation_history[self.current_history_index]
                subtitle = entry.get('title', '')
                self.current_entry = entry
                self._update_bookmark_button()
            self._update_content_subtitle(subtitle)
            self._update_nav_buttons()
    
    def _on_bookmark_clicked(self, button):
        """Toggle bookmark for current entry."""
        entry = self.current_entry
        if not entry:
            return
        
        key_id = entry.get('id', '')
        source = entry.get('source', '')
        key = entry.get('title', '')
        dictionary = entry.get('dictionary', '')
        
        if self.bookmarks_db.is_bookmarked(key_id, source):
            # Remove bookmark
            self.bookmarks_db.remove_bookmark(key_id, source)
            self.bookmark_button.set_icon_name("non-starred-symbolic")
        else:
            # Add bookmark
            self.bookmarks_db.add_bookmark(key_id, key, source, dictionary)
            self.bookmark_button.set_icon_name("starred-symbolic")
        self._on_history_search_changed(self.history_search_entry)

    def _update_bookmark_button(self):
        """Update bookmark button appearance based on current entry."""
        entry = self.current_entry
        if not entry:
            # No entry displayed, disable button
            self.bookmark_button.set_sensitive(False)
            self.bookmark_button.set_icon_name("non-starred-symbolic")
            return
        
        self.bookmark_button.set_sensitive(True)
        key_id = entry.get('id', '')
        source = entry.get('source', '')
        
        if self.bookmarks_db.is_bookmarked(key_id, source):
            self.bookmark_button.set_icon_name("starred-symbolic")
        else:
            self.bookmark_button.set_icon_name("non-starred-symbolic")

    def _update_nav_buttons(self):
        """Update back/forward button visibility and sensitivity."""
        can_go_back = False
        can_go_forward = False
        if hasattr(self, 'webview'):
            can_go_back = self.webview.can_go_back()
            can_go_forward = self.webview.can_go_forward()

        self.back_button.set_sensitive(can_go_back)
        self.forward_button.set_sensitive(can_go_forward)

    def _on_search_changed(self, entry):
        """Handle search text changes."""
        # Only search in lookup mode
        if self.current_view != "lookup":
            return

        text = entry.get_text()
        
        # Increment request counter to invalidate previous request
        self.request_counter += 1
        self.current_search_request_id = self.request_counter

        if text:
            # Submit new search task
            self.pending_search_task = self.executor.submit(
                self._search_task, text, self.current_search_request_id
            )
        else:
            self._populate_results([])

    def _on_history_search_changed(self, entry):
        """Handle history/bookmarks search text changes."""
        if self.current_view not in ("history", "bookmarks"):
            return
        
        text = entry.get_text()
        if self.current_view == "history":
            self._populate_history(text)
        else:
            self._populate_bookmarks(text)

    def _search_task(self, query: str, request_id: int):
        """Search task with cancellation support."""
        # Mark this as current request in slob client
        self.slob_client.set_current_request(request_id)
        results = self.slob_client.search(query, limit=150, request_id=request_id)
        
        # Only update UI if this request is still current
        if request_id == self.current_search_request_id:
            GLib.idle_add(self._populate_results, results)
    
    def _populate_results(self, results: List[Dict]):
        """Populate results list."""
        # Only disconnect if signal is already connected
        try:
            self.results_list.disconnect_by_func(self._on_result_selected)
        except TypeError:
            # Signal not connected yet, that's fine
            pass
        
        self.row_to_result.clear()

        # Clear existing rows
        while True:
            row = self.results_list.get_first_child()
            if row is None:
                break
            self.results_list.remove(row)

        # Add new rows
        for result in results:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_spacing(4)

            title_label = Gtk.Label(label=result.get("title", ""))
            title_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            source_label = Gtk.Label(label=result.get("dictionary", ""))
            source_label.set_css_classes(["dim-label"])
            source_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            source_label.set_halign(Gtk.Align.START)
            box.append(source_label)

            row.set_child(box)
            
            # Store result by row object directly
            self.row_to_result[row] = result
            
            self.results_list.append(row)

        # Reconnect signal after populating
        self.results_list.connect("row-selected", self._on_result_selected)

    def _populate_bookmarks(self, filter_query: str = ""):
        """Populate bookmarks list with optional filtering."""
        bookmark_items = self.bookmarks_db.get_bookmarks(filter_query)
        
        self.row_to_result.clear()

        # Clear existing rows
        while True:
            row = self.results_list.get_first_child()
            if row is None:
                break
            self.results_list.remove(row)

        if not bookmark_items:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_halign(Gtk.Align.CENTER)
            box.set_valign(Gtk.Align.CENTER)
            box.set_vexpand(True)
            box.set_hexpand(True)
            box.set_spacing(10)

            label = Gtk.Label(label=_("No bookmarks"))
            label.set_css_classes(["dim-label"])
            label.set_wrap(True)
            box.append(label)

            row.set_child(box)
            self.results_list.append(row)
            return

        # Add bookmark items
        for bookmark_item in bookmark_items:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_spacing(4)

            # Title
            title_label = Gtk.Label(label=bookmark_item.get("key", ""))
            title_label.set_ellipsize(3)
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            # Source and date
            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.set_spacing(8)
            
            source_label = Gtk.Label(label=bookmark_item.get("dictionary", ""))
            source_label.set_css_classes(["dim-label"])
            source_label.set_ellipsize(3)
            source_label.set_halign(Gtk.Align.START)
            info_box.append(source_label)

            date_label = Gtk.Label(
                label=self.bookmarks_db.format_timestamp(bookmark_item.get("created_at", ""))
            )
            date_label.set_css_classes(["dim-label"])
            date_label.set_ellipsize(3)
            date_label.set_halign(Gtk.Align.START)
            date_label.set_hexpand(True)
            info_box.append(date_label)
            
            box.append(info_box)

            row.set_child(box)
            self.row_to_result[row] = {
                "id": bookmark_item["key_id"],
                "title": bookmark_item["key"],
                "source": bookmark_item["source"],
                "dictionary": bookmark_item["dictionary"]
            }
            self.results_list.append(row)

    def _populate_history(self, filter_query: str = ""):
        """Populate history list with optional filtering."""
        history_items = self.history_db.get_history(filter_query)
        
        self.row_to_result.clear()

        # Clear existing rows
        while True:
            row = self.results_list.get_first_child()
            if row is None:
                break
            self.results_list.remove(row)

        if not history_items:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_halign(Gtk.Align.CENTER)
            box.set_valign(Gtk.Align.CENTER)
            box.set_vexpand(True)
            box.set_hexpand(True)
            box.set_spacing(10)

            label = Gtk.Label(label=_("No history"))
            label.set_css_classes(["dim-label"])
            label.set_wrap(True)
            box.append(label)

            row.set_child(box)
            self.results_list.append(row)
            return

        # Add history items
        for history_item in history_items:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_spacing(4)

            # Title
            title_label = Gtk.Label(label=history_item.get("key", ""))
            title_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            # Source and date
            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.set_spacing(8)
            
            source_label = Gtk.Label(label=history_item.get("dictionary", ""))
            source_label.set_css_classes(["dim-label"])
            source_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            source_label.set_halign(Gtk.Align.START)
            info_box.append(source_label)

            date_label = Gtk.Label(
                label=self.history_db.format_timestamp(history_item.get("timestamp", ""))
            )
            date_label.set_css_classes(["dim-label"])
            date_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            date_label.set_halign(Gtk.Align.START)
            date_label.set_hexpand(True)
            info_box.append(date_label)
            
            box.append(info_box)

            row.set_child(box)
            self.row_to_result[row] = {
                "id": history_item["key_id"],
                "title": history_item["key"],
                "source": history_item["source"],
                "dictionary": history_item["dictionary"]
            }
            self.results_list.append(row)

    def _on_result_selected(self, listbox, row):
        """Handle result selection."""        
        if row is None:
            return

        # Get result directly from row object
        result = self.row_to_result.get(row)
        
        if result:
            # Cancel previous lookup
            if self.pending_lookup_task:
                self.pending_lookup_task.cancel()

            self.pending_lookup_task = self.executor.submit(
                self._load_entry_task,
                result
            )

    def _load_entry_task(self, entry: dict):
        """Load entry task with cancellation support."""            
        key_id = entry['id']
        key = entry['title']
        source = entry['source']
        dictionary = entry['dictionary']
        GLib.idle_add(self._render_entry, entry)
        # Add to history
        if self.settings_manager.get('enable_history', True):
            self.history_db.add_entry(key_id, key, source, dictionary)

    def _render_entry(self, entry: Dict, update_history: bool = True):
        """Render entry in webview."""
        if not hasattr(self, 'webview'):
            return

        key = quote(entry.get('title', ''), safe='')
        key_id = quote(entry.get('id', ''), safe='')
        source = quote(entry.get('source', ''), safe='')
        
        url = f"http://127.0.0.1:{self.http_port}/slob/{source}/{key}?blob={key_id}"
        print(f"Loading: {url}")
        
        # Update navigation history if this is a new entry (not from back/forward)
        if update_history:
            # Remove any forward history if we're adding a new entry
            if self.current_history_index < len(self.navigation_history) - 1:
                self.navigation_history = self.navigation_history[:self.current_history_index + 1]
            
            self.navigation_history.append(entry)
            self.current_history_index = len(self.navigation_history) - 1
            self._update_nav_buttons()
        
        # Update header bar subtitle with current key
        self._update_content_subtitle(entry.get('title', ''))
        
        self.current_entry = entry
        self._update_bookmark_button()
        self.webview.load_uri(url)

    def _update_content_subtitle(self, subtitle: str):
        """Update content subtitle"""
        title_widget = self.content_header.get_title_widget()
        if isinstance(title_widget, Adw.WindowTitle):
            title_widget.set_subtitle(subtitle)

    def _on_close(self, window):
        """Handle window close."""
        self.http_server.stop()
        self.slob_client.close()
        return False

    # These methods should be registered as actions in your application class
    def action_lookup(self, action, param):
        """Switch to lookup view - register as app.lookup action."""
        self.current_view = "lookup"
        self._update_sidebar_title()
        self.search_entry.set_visible(True)
        self.history_search_entry.set_visible(False)
        self.search_entry.grab_focus()
        self._populate_results([])
        self._on_dictionary_updated()

    def action_bookmarks(self, action, param):
        """Switch to bookmarks view - register as app.bookmarks action."""
        self.current_view = "bookmarks"
        self._update_sidebar_title()
        self.search_entry.set_visible(False)
        self.history_search_entry.set_visible(False)
        # Reuse history_search_entry for bookmarks filtering
        self.history_search_entry.set_placeholder_text(_("Filter bookmarks..."))
        self.history_search_entry.set_visible(True)
        self.history_search_entry.grab_focus()
        self._populate_bookmarks()

    def action_history(self, action, param):
        """Switch to history view - register as app.history action."""
        self.current_view = "history"
        self._update_sidebar_title()
        self.search_entry.set_visible(False)
        self.history_search_entry.set_placeholder_text(_("Filter history..."))
        self.history_search_entry.set_visible(True)
        self.history_search_entry.grab_focus()
        self._populate_history()
        self._on_dictionary_updated()
