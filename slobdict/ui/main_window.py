# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")

from gi.repository import Gtk, Adw, WebKit, Gio, GLib, Gdk
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from ..backend.slob_client import SlobClient
from ..backend.http_server import HTTPServer_
from ..backend.history_db import HistoryDB
from ..constants import app_label


class MainWindow(Adw.ApplicationWindow):
    """Main dictionary window with sidebar, search, and webview."""

    def __init__(self, application, settings_manager):
        super().__init__(application=application)
        self.set_title(app_label)
        self.set_default_size(1200, 700)
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

        # Initialize slob backend
        self.slob_client = SlobClient(self._on_dictionary_updated)

        # Initialize history manager
        self.history_db = HistoryDB()

        # Initialize HTTP server
        self.http_server = HTTPServer_(self.slob_client, port=8080)
        self.http_server.start()
        # Store the actual port
        self.http_port = self.http_server.get_port()
        self.connect("close-request", self._on_close)

        # Thread pool executor for background tasks
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Track pending tasks for cancellation
        self.pending_search_task = None
        self.pending_lookup_task = None
        # Request ID tracking for cancellation
        self.request_counter = 0
        self.current_search_request_id = None
        self.current_lookup_request_id = None

        # State
        self.current_view = "lookup"  # "lookup" or "history"
        self.search_query = ""
        self.current_result = None
        self.row_to_result = {}

        # Main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header bar
        header = self._create_header()
        vbox.append(header)

        # Split view: sidebar icons + main content
        split_view = self._create_split_view()
        vbox.append(split_view)

        self.set_content(vbox)

        self.connect("show", self.on_window_shown)

        # Register for settings changes
        self.settings_manager.register_callback('force_dark_mode', self._on_force_dark_changed)
        self.settings_manager.register_callback('enable_javascript', self._on_javascript_changed)
        self.settings_manager.register_callback('load_remote_content', self._on_remote_content_changed)

    def on_window_shown(self, widget):
        """Focus search entry when window is shown."""
        self.search_entry.grab_focus()

    def _create_header(self):
        """Create header bar with menu."""
        header = Adw.HeaderBar()

        # Menu button (hamburger)
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(self._create_menu_model())
        header.pack_end(menu_button)

        return header

    def _create_menu_model(self):
        """Create main menu model."""
        menu = Gio.Menu()

        # Menu items
        menu.append(_("Dictionaries"), "app.dictionaries")
        menu.append(_("Preferences"), "app.preferences")
        menu.append(_("Keyboard Shortcuts"), "app.shortcuts")
        menu.append(_("About %s") % app_label, "app.about")
        menu.append_section(None, Gio.Menu.new())
        menu.append(_("Quit"), "app.quit")

        return menu

    def _create_split_view(self):
        """Create AdwOverlaySplitView: sidebar + content."""
        split_view = Adw.OverlaySplitView()
        split_view.set_max_sidebar_width(50)
        split_view.set_min_sidebar_width(48)
        
        # Sidebar: Icon buttons
        sidebar = self._create_icon_sidebar()
        split_view.set_sidebar(sidebar)

        # Content: Paned split (search/history column + webview)
        content_pane = self._create_content_pane()
        split_view.set_content(content_pane)

        return split_view

    def _create_icon_sidebar(self):
        """Create icon button sidebar with square buttons and styling."""
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_spacing(8)
        sidebar_box.set_margin_top(8)
        sidebar_box.set_margin_bottom(8)
        sidebar_box.set_margin_start(4)
        sidebar_box.set_margin_end(4)
        sidebar_box.set_size_request(48, -1) 

        # Lookup icon
        self.lookup_btn = Gtk.Button()
        self.lookup_btn.set_icon_name("system-search-symbolic")
        self.lookup_btn.set_tooltip_text(_("Lookup Dictionary"))
        self.lookup_btn.set_has_frame(False)
        self.lookup_btn.set_size_request(40, 40)
        self.lookup_btn.add_css_class("flat")
        self.lookup_btn.connect("clicked", self._on_lookup_clicked)
        sidebar_box.append(self.lookup_btn)

        # History icon
        self.history_btn = Gtk.Button()
        self.history_btn.set_icon_name("document-open-recent-symbolic")
        self.history_btn.set_tooltip_text(_("View History"))
        self.history_btn.set_has_frame(False)
        self.history_btn.set_size_request(40, 40)
        self.history_btn.add_css_class("flat")
        self.history_btn.connect("clicked", self._on_history_clicked)
        sidebar_box.append(self.history_btn)

        # Set lookup as initially active
        self._set_active_button(self.lookup_btn)

        return sidebar_box

    def _set_active_button(self, button):
        """Set button as active and update others."""
        # Remove active class from all buttons
        self.lookup_btn.remove_css_class("active-nav-btn")
        self.history_btn.remove_css_class("active-nav-btn")
        
        # Add active class to current button
        button.add_css_class("active-nav-btn")

    def _create_content_pane(self):
        """Create main content: resizable paned split."""
        # Paned widget (horizontal, left/right resizable)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(400)  # Initial position

        # Left pane: Search/History column
        left_pane = self._create_left_pane()
        paned.set_start_child(left_pane)

        # Right pane: Webview
        right_pane = self._create_webview_pane()
        paned.set_end_child(right_pane)

        # Make resizable and give focus to right pane
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        paned.set_resize_end_child(True)
        paned.set_shrink_end_child(False)

        return paned

    def _create_left_pane(self):
        """Create left pane: search/history column."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Toolbar for search
        toolbar_view = Adw.ToolbarView()

        # Search bar (shown in "lookup" mode)
        self.search_bar = self._create_search_bar()
        toolbar_view.add_top_bar(self.search_bar)

        # History search bar (shown in history mode)
        self.history_search_bar = self._create_history_search_bar()
        self.history_search_bar.set_visible(False)
        toolbar_view.add_top_bar(self.history_search_bar)

        # Results/History list
        self.results_list = Gtk.ListBox()
        self.results_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.results_list.set_css_classes(["navigation-sidebar"])
        self.results_list.connect("row-selected", self._on_result_selected)

        # Scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.results_list)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        toolbar_view.set_content(scrolled)
        return toolbar_view

    def _create_search_bar(self):
        """Create search entry."""
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hbox.set_spacing(8)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        hbox.set_margin_start(8)
        hbox.set_margin_end(8)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(_("Lookup"))
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        hbox.append(self.search_entry)

        return hbox

    def _create_history_search_bar(self):
        """Create history search entry."""
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hbox.set_spacing(8)
        hbox.set_margin_top(8)
        hbox.set_margin_bottom(8)
        hbox.set_margin_start(8)
        hbox.set_margin_end(8)

        self.history_search_entry = Gtk.SearchEntry()
        self.history_search_entry.set_placeholder_text(_("Filter history..."))
        self.history_search_entry.set_hexpand(True)
        self.history_search_entry.connect("search-changed", self._on_history_search_changed)
        hbox.append(self.history_search_entry)

        return hbox

    def _create_webview_pane(self):
        """Create webview pane for rendering dictionary content."""
        try:
            self.webview = WebKit.WebView()
            # Apply user preferences
            self._apply_webview_settings()

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_child(self.webview)
            scrolled.set_hexpand(True)
            scrolled.set_vexpand(True)
            return scrolled
        except Exception as e:
            label = Gtk.Label()
            label.set_markup(_("WebKit unavailable: %s") % str(e))
            label.set_hexpand(True)
            label.set_vexpand(True)
            return label

    def _apply_webview_settings(self):
        """Apply user preferences to WebView."""
        settings = self.webview.get_settings()
        
        # Force dark mode
        force_dark = self.settings_manager.get('force_dark_mode', True)
        self.http_server.set_dark_mode(force_dark)

        if force_dark:
            from ..utils.utils import load_dark_mode_css
            self.webview.load_html(f"<html><body><style>{load_dark_mode_css()}</style></body></html>")
        else: self.webview.load_html("<html></html>")
        
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
            
            return False  # Prevent default menu
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
            
            # Get current URI and extract base path
            current_uri = self.webview.get_uri()
            if not current_uri or current_uri == "about:blank":
                return
            
            # Parse URL to get base path
            from urllib.parse import urlparse
            parsed = urlparse(current_uri)
            
            # Get the base path (everything except the last part)
            path_parts = parsed.path.rstrip('/').rsplit('/', 1)
            if len(path_parts) == 2:
                base_path = path_parts[0]
            else:
                base_path = parsed.path.rstrip('/')
            
            # Build new URL
            new_path = f"{base_path}/{selected_text.strip()}"
            new_uri = f"{parsed.scheme}://{parsed.netloc}{new_path}"
            
            # Load the new URL
            self.webview.load_uri(new_uri)
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
                else: self.webview.load_html("<html></html>")
            else:
                print(f"URL: {self.webview.get_uri()}")
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

    def _on_lookup_clicked(self, button):
        """Switch to lookup view."""
        self._set_active_button(button)
        self.current_view = "lookup"
        self.search_bar.set_visible(True)
        self.history_search_bar.set_visible(False)
        self.search_entry.grab_focus()
        self._populate_results([])
        self._on_dictionary_updated()

    def _on_history_clicked(self, button):
        """Switch to history view."""
        self._set_active_button(button)
        self.current_view = "history"
        self.search_bar.set_visible(False)
        self.history_search_bar.set_visible(True)
        self.history_search_entry.grab_focus()
        self._populate_history()
        self._on_dictionary_updated()

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
        """Handle history search text changes."""
        # Only filter in history mode
        if self.current_view != "history":
            return
        
        text = entry.get_text()
        self._populate_history(text)

    def _search_task(self, query: str, request_id: int):
        """Search task with cancellation support."""
        # Mark this as current request in slob client
        self.slob_client.set_current_request(request_id)
        results = self.slob_client.search(query, limit=50, request_id=request_id)
        
        # Only update UI if this request is still current
        if request_id == self.current_search_request_id:
            GLib.idle_add(self._populate_results, results)

    def _lookup_task(self, query: str, request_id: int):
        """Lookup task with cancellation support."""
        self.slob_client.set_current_request(request_id)
        results = self.slob_client.search(query, limit=1, request_id=request_id)
        
        if results and request_id == self.current_lookup_request_id:
            result = results[0]
            entry = self.slob_client.get_entry(
                result["title"], result["source"], request_id=request_id
            )
            if entry:
                GLib.idle_add(self._render_entry, entry)
    
    def _populate_results(self, results: List[Dict]):
        """Populate results list."""
        # Disconnect signal temporarily to avoid triggering row-selected
        self.results_list.disconnect_by_func(self._on_result_selected)

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
            title_label.set_wrap(True)
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            source_label = Gtk.Label(label=result.get("source", ""))
            source_label.set_css_classes(["dim-label"])
            source_label.set_halign(Gtk.Align.START)
            box.append(source_label)

            row.set_child(box)
            
            # Store result by row object directly
            self.row_to_result[row] = result
            
            self.results_list.append(row)

        # Reconnect signal after populating
        self.results_list.connect("row-selected", self._on_result_selected)

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
            title_label.set_wrap(True)
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            # Source and date
            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.set_spacing(8)
            
            source_label = Gtk.Label(label=history_item.get("source", ""))
            source_label.set_css_classes(["dim-label"])
            source_label.set_halign(Gtk.Align.START)
            info_box.append(source_label)

            date_label = Gtk.Label(
                label=self.history_db.format_timestamp(history_item.get("timestamp", ""))
            )
            date_label.set_css_classes(["dim-label"])
            date_label.set_halign(Gtk.Align.END)
            date_label.set_hexpand(True)
            info_box.append(date_label)
            
            box.append(info_box)

            row.set_child(box)
            self.row_to_result[row] = {
                "title": history_item["key"],
                "source": history_item["source"]
            }
            self.results_list.append(row)

    def _on_result_selected(self, listbox, row):
        """Handle result selection."""        
        if row is None:
            return

        # Get result directly from row object
        result = self.row_to_result.get(row)
        
        if result:            
            # Increment request counter
            self.request_counter += 1
            self.current_lookup_request_id = self.request_counter

            # Cancel previous lookup
            if self.pending_lookup_task:
                self.pending_lookup_task.cancel()

            self.pending_lookup_task = self.executor.submit(
                self._load_entry_task,
                result["title"],
                result["source"],
                self.current_lookup_request_id
            )

    def _load_entry_task(self, key: str, source: str, request_id: int):
        """Load entry task with cancellation support."""        
        self.slob_client.set_current_request(request_id)
        entry = self.slob_client.get_entry(key, source, request_id=request_id)
        
        if entry and request_id == self.current_lookup_request_id:
            self.current_result = entry
            GLib.idle_add(self._render_entry, entry)
            # Add to history manager
            self.history_db.add_entry(key, source)

    def _render_entry(self, entry: Dict):
        """Render entry in webview."""
        if not hasattr(self, 'webview'):
            return

        key = quote(entry.get('key', ''), safe='')
        source = quote(entry.get('source', ''), safe='')
        
        url = f"http://127.0.0.1:{self.http_port}/slob/{source}/{key}"
        print(f"Loading: {url}")
        self.webview.load_uri(url)

    def _on_close(self, window):
        """Handle window close."""
        self.http_server.stop()
        self.slob_client.close()
        return False
        