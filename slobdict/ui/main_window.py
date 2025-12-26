# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")

from gi.repository import Gtk, Adw, WebKit, Gio, GLib, Gdk
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, Future
from urllib.parse import quote, urlparse
from ..backend.slob_client import SlobClient
from ..backend.http_server import HTTPServer_
from ..backend.bookmarks_db import BookmarksDB
from ..backend.history_db import HistoryDB
from ..backend.settings_manager import SettingsManager
from ..constants import app_label, rootdir
from ..utils.structs import DictEntry
from ..utils.i18n import _


@Gtk.Template(resource_path=rootdir + "/ui/window.ui")
class MainWindow(Adw.ApplicationWindow):
    """Main dictionary window with sidebar, search, and webview."""

    class LookupEntry(object):
        def __init__(self,
            term: str,
            *,
            dict_id: Optional[str] = None,
            term_id: Optional[int] = None
        ):
            self._term: str = term
            self._dict_id = dict_id
            self._term_id  = term_id

        @property
        def dict_id(self) -> Optional[str]:
            return self._dict_id

        @property
        def term_id(self) -> Optional[int]:
            return self._term_id

        @property
        def term(self) -> str:
            return self._term

        def __str__(self) -> str:
            return self.term

    class NavigationHistory:
        history: List[DictEntry] = []
        current_index: int = 0

        def __init__(self) -> None:
            pass

        def has_next(self) -> bool:
            return self.current_index < len(self.history) - 1

        def has_prev(self) -> bool:
            return self.current_index > 0
        
        def next(self) -> Optional[DictEntry]:
            if self.has_next():
                self.current_index += 1
                return self.history[self.current_index]
            return None

        def prev(self) -> Optional[DictEntry]:
            if self.has_prev():
                self.current_index -= 1
                return self.history[self.current_index]
            return None

        def add(self, entry: DictEntry) -> None:
            # Remove any forward history if we're adding a new entry
            if self.has_next():
                self.history = self.history[:self.current_index + 1]
            
            self.history.append(entry)
            self.current_index = len(self.history) - 1


    __gtype_name__ = "MainWindow"

    # Template child bindings
    sidebar_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    sidebar_header: Adw.HeaderBar = Gtk.Template.Child()
    sidebar_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    content_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    content_header: Adw.HeaderBar = Gtk.Template.Child()
    bookmark_button: Gtk.Button = Gtk.Template.Child()
    back_button: Gtk.Button = Gtk.Template.Child()
    forward_button: Gtk.Button = Gtk.Template.Child()
    find_button: Gtk.Button = Gtk.Template.Child()
    nav_buttons_box: Gtk.Box = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    history_search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    results_list: Gtk.ListBox = Gtk.Template.Child()
    webview_container: Gtk.Box = Gtk.Template.Child()
    find_bar: Gtk.Box = Gtk.Template.Child()
    find_entry: Gtk.SearchEntry = Gtk.Template.Child()
    find_prev_button: Gtk.Button = Gtk.Template.Child()
    find_next_button: Gtk.Button = Gtk.Template.Child()
    find_close_button: Gtk.Button = Gtk.Template.Child()

    def __init__(self, app: Gio.Application, settings_manager: SettingsManager, slob_client: SlobClient) -> None:
        super().__init__(application=app)
        
        self.settings_manager = settings_manager
        self.slob_client = slob_client

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
        self.row_to_result: Dict[Gtk.ListBoxRow, DictEntry] = {}
        self.navigation_history = MainWindow.NavigationHistory()
        self.current_entry: Optional[DictEntry] = None  # Track current entry being displayed
        self.current_style: Optional[str] = None  # Stylesheet tracking
        self.zoom_level = self.settings_manager.zoom_level
        self.load_remote = self.settings_manager.load_remote_content
        self.remote_reload_pending: bool = False    # Tracks if reload is in progress

        # Track pending tasks for cancellation
        self.pending_search_task: Optional[Future] = None
        self.pending_lookup_task: Optional[Future] = None
        self.request_counter = 0
        self.current_search_request_id: Optional[int] = None
        self.scheduled_selected_lookup_item: Optional[MainWindow.LookupEntry] = None
        self.scheduled_select_first_lookup_item: bool = False

        # Initialize DB
        self.bookmarks_db = BookmarksDB()
        self.history_db = HistoryDB()

        # Initialize HTTP server
        self.http_server = HTTPServer_(self.slob_client, port=settings_manager.port)
        self.http_server.start()
        # Store the actual port
        self.http_port: Optional[int] = self.http_server.get_port()
        self.connect("close-request", self._on_close)

        # Thread pool executor for background tasks
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Setup UI elements
        self._setup_ui()
        
        # Setup menu
        self._setup_menu()
        self._setup_actions()

        self.connect("show", self.on_window_shown)

        # Register for settings changes
        self.settings_manager.register_callback('appearance', self._on_force_dark_changed)
        self.settings_manager.register_callback('force_dark_mode', self._on_force_dark_changed)
        self.settings_manager.register_callback('enable_javascript', self._on_javascript_changed)
        self.settings_manager.register_callback('load_remote_content', self._on_remote_content_changed)

    def _setup_ui(self) -> None:
        """Setup UI elements from template."""
        # Connect search signals
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.history_search_entry.connect("search-changed", self._on_history_search_changed)

        # Connect results list
        self.results_list.connect("row-selected", self._on_result_selected)

        # Connect find bar signal
        self.find_entry.connect("search-changed", self._on_find_text_changed)
        self.find_entry.connect("activate", self._on_find_activate)
        self.find_entry.connect("stop-search", self._on_find_close)
        self.find_prev_button.connect("clicked", self._on_find_prev)
        self.find_next_button.connect("clicked", self._on_find_next)
        self.find_close_button.connect("clicked", self._on_find_close)
        # Hide find bar by default
        self.find_bar.set_visible(False)

        # Create and add webview
        try:
            self.manager = WebKit.UserContentManager()
            self.webview = WebKit.WebView(user_content_manager=self.manager)

            self.find_controller = self.webview.get_find_controller()
            self.find_controller.connect("found-text", self._on_found_text)
            self.find_controller.connect("failed-to-find-text", self._on_failed_to_find_text)

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

    def _setup_menu(self) -> None:
        """Setup application menu."""
        if self.sidebar_menu_button:
            self.sidebar_menu_button.set_menu_model(self._create_menu_model())


    def _create_menu_model(self) -> Gio.Menu:
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

    def _setup_actions(self) -> None:
        """Set up window menu actions."""
        actions = [
            ("nav-backward", self._on_nav_backward),
            ("nav-forward", self._on_nav_forward),
            ("find-in-page", self._on_find),
            ("bookmark", self._on_bookmark),
            ("zoom-in", self._on_zoom_in),
            ("zoom-out", self._on_zoom_out),
            ("zoom-reset", self._on_zoom_reset),
            ("load-remote", self._on_load_remote),
            ("print", self._on_print),
        ]

        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _update_sidebar_title(self) -> None:
        """Update sidebar title based on current view."""
        title_widget: Adw.WindowTitle = self.sidebar_header.get_title_widget()
        if self.current_view == "lookup":
            title_widget.set_title(_("Lookup"))
        elif self.current_view == "bookmarks":
            title_widget.set_title(_("Bookmarks"))
        else:
            title_widget.set_title(_("History"))

    def _apply_webview_settings(self) -> None:
        """Apply user preferences to WebView."""
        settings: WebKit.Settings = self.webview.get_settings()

        # Apply zoom level
        self.webview.set_zoom_level(self.zoom_level)
        
        # Force dark mode
        force_dark: bool = self.settings_manager.force_dark
        self._apply_dark_mode_css(force_dark)

        from ..utils.utils import get_init_html
        self.webview.load_html(get_init_html(force_dark))
        
        # Enable/disable JavaScript
        enable_js: bool = self.settings_manager.enable_javascript
        settings.set_property("enable-javascript", enable_js)

        self.webview.connect("resource-load-started", self._on_resource_load_started)
        self.webview.connect("load-changed", self._on_load_changed)
        self.webview.connect("context-menu", self._on_context_menu)

    def _apply_dark_mode_css(self, force_dark: bool) -> None:
        """Apply force-dark CSS when enabled"""
        if not hasattr(self, "manager"):
            return

        if self.current_style:
            self.manager.remove_style_sheet(self.current_style)

        if force_dark:
            from ..utils.utils import load_dark_mode_css
            self.current_style = WebKit.UserStyleSheet(
                load_dark_mode_css(),
                WebKit.UserContentInjectedFrames.ALL_FRAMES, 
                WebKit.UserStyleLevel.USER, 
                None, 
                None
            )
            self.manager.add_style_sheet(self.current_style)

    def _on_context_menu(self,
        webview: WebKit.WebView,
        context_menu: WebKit.ContextMenu,
        hit_test_result: WebKit.HitTestResult
    ) -> bool:
        """Handle WebView context menu customization."""
        try:
            # Add Lookup option
            if hit_test_result.context_is_selection() and self.settings_manager.enable_javascript:
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

    def _on_lookup_selected(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
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
    
    def _on_get_selection_for_lookup(self, webview: WebKit.WebView, result: Gio.AsyncResult) -> None:
        """Callback to process selected text."""
        try:
            selected_text = webview.evaluate_javascript_finish(result).to_string()
            if not selected_text or selected_text.strip() == "":
                return
            
            self.perform_lookup(selected_text.strip())
        except Exception as e:
            print(f"Error in lookup: {e}")

    def _on_force_dark_changed(self, key: str, value: bool) -> None:
        """Handle force dark mode setting change."""
        self._apply_dark_mode_css(value)
        if hasattr(self, 'webview'):
            if self.webview.get_uri() is None or self.webview.get_uri() == "about:blank":
                from ..utils.utils import get_init_html
                self.webview.load_html(get_init_html(value))

    def _on_javascript_changed(self, key: str, value: bool) -> None:
        """Handle JavaScript setting change."""
        if hasattr(self, 'webview'):
            settings: WebKit.Settings = self.webview.get_settings()
            settings.set_property("enable-javascript", value)

    def _on_remote_content_changed(self, key: str, value: bool) -> None:
        """Handle remote content setting change."""
        self.load_remote = value

    def _on_resource_load_started(self,
        webview: WebKit.WebView,
        resource: WebKit.WebResource,
        request: WebKit.URIRequest
    ) -> None:
        uri = request.get_uri()
        if not self.load_remote and uri and not (uri.startswith("http://127.0.0.1") or uri.startswith("data:") or uri.startswith("about:")):
            print(f"Blocking remote resource: {uri}")
            # Blocks remote resources by redirecting them
            request.set_uri("about:blank")

    def _on_load_changed(self, webview: WebKit.WebView, event: WebKit.LoadEvent) -> None:
        """Handle page load events.
        
        Events:
        - WEBKIT_LOAD_STARTED: Page load has started
        - WEBKIT_LOAD_REDIRECTED: Page load has been redirected
        - WEBKIT_LOAD_COMMITTED: Page load has been committed
        - WEBKIT_LOAD_FINISHED: Page load has finished
        """
        if event == WebKit.LoadEvent.FINISHED:
            # Page finished loading
            if self.remote_reload_pending:
                self.load_remote = self.settings_manager.load_remote_content
                self.remote_reload_pending = False

    def on_dictionary_updated(self) -> None:
        if hasattr(self, 'search_entry'):
            self._on_search_changed(self.search_entry)
        if hasattr(self, 'history_search_entry'):
            self._on_history_search_changed(self.history_search_entry)

    def on_window_shown(self, widget) -> None:
        """Focus search entry when window is shown."""
        self.search_entry.grab_focus()

    def _on_nav_backward(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Navigate to previous entry in navigation history."""
        if hasattr(self, 'webview'):
            entry = self.navigation_history.prev()
            if not entry:
                return
            GLib.idle_add(self._render_entry, entry, False)
            self.current_entry = entry
            self._update_bookmark_button()
            self._update_content_subtitle(entry.term)
            self._update_nav_buttons()

    def _on_nav_forward(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Navigate to next entry in navigation history."""
        if hasattr(self, 'webview'):
            entry = self.navigation_history.next()
            if not entry:
                return
            GLib.idle_add(self._render_entry, entry, False)
            self.current_entry = entry
            self._update_bookmark_button()
            self._update_content_subtitle(entry.term)
            self._update_nav_buttons()

    def _on_find(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Open find bar for searching page content."""
        self.find_bar.set_visible(True)
        self.find_entry.grab_focus()

    def _on_bookmark(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Toggle bookmark for current entry."""
        entry = self.current_entry
        if not entry:
            return
                
        if self.bookmarks_db.is_bookmarked(entry):
            # Remove bookmark
            self.bookmarks_db.remove_bookmark(entry)
            self.bookmark_button.set_icon_name("non-starred-symbolic")
        else:
            # Add bookmark
            self.bookmarks_db.add_bookmark(entry)
            self.bookmark_button.set_icon_name("starred-symbolic")
        self._on_history_search_changed(self.history_search_entry)

    def _on_zoom_in(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Increase zoom level by 10% up to 300%."""
        if hasattr(self, 'webview'):
            self.zoom_level = min(self.zoom_level + 0.1, 3.0)  # Max 300%
            self.webview.set_zoom_level(self.zoom_level)
    
    def _on_zoom_out(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Decrease zoom level by 10% up to 50%."""
        if hasattr(self, 'webview'):
            self.zoom_level = max(self.zoom_level - 0.1, 0.5)  # Min 50%
            self.webview.set_zoom_level(self.zoom_level)
    
    def _on_zoom_reset(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Reset zoom to 100%."""
        if hasattr(self, 'webview'):
            self.zoom_level = 1.0
            self.webview.set_zoom_level(self.zoom_level)
    
    def _on_print(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Open print dialog for the current page."""
        if hasattr(self, 'webview'):
            print_operation = WebKit.PrintOperation.new(self.webview)
            print_operation.run_dialog(self)
    
    def _on_load_remote(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        if self.remote_reload_pending:
            return
        
        self.load_remote = True
        self.remote_reload_pending = True
        self.webview.reload()

    def _update_bookmark_button(self) -> None:
        """Update bookmark button appearance based on current entry."""
        entry = self.current_entry
        if not entry:
            # No entry displayed, disable button
            self.bookmark_button.set_sensitive(False)
            self.bookmark_button.set_icon_name("non-starred-symbolic")
            return
        
        self.bookmark_button.set_sensitive(True)

        if self.bookmarks_db.is_bookmarked(entry):
            self.bookmark_button.set_icon_name("starred-symbolic")
        else:
            self.bookmark_button.set_icon_name("non-starred-symbolic")

    def _update_nav_buttons(self) -> None:
        """Update back/forward button visibility and sensitivity."""
        self.back_button.set_sensitive(self.navigation_history.has_prev())
        self.forward_button.set_sensitive(self.navigation_history.has_next())

    def _on_search_changed(self, search_entry: Gtk.SearchEntry) -> None:
        """Handle search text changes."""
        # Only search in lookup mode
        if self.current_view != "lookup":
            return

        text = search_entry.get_text()
        
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

    def _on_history_search_changed(self, search_entry: Gtk.SearchEntry) -> None:
        """Handle history/bookmarks search text changes."""
        if self.current_view not in ("history", "bookmarks"):
            return
        
        text = search_entry.get_text()
        if self.current_view == "history":
            self._populate_history(text)
        else:
            self._populate_bookmarks(text)

    def _search_task(self, query: str, request_id: int) -> None:
        """Search task with cancellation support."""
        # Mark this as current request in slob client
        self.slob_client.set_current_request(request_id)
        results = self.slob_client.search(query, limit=150, request_id=request_id)
        
        # Only update UI if this request is still current
        if request_id == self.current_search_request_id:
            GLib.idle_add(self._populate_results, results, request_id)
    
    def _populate_results(self, results: List[DictEntry], request_id: Optional[int] = None) -> None:
        """Populate results list."""
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

            title_label = Gtk.Label(label=result.term)
            title_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            source_label = Gtk.Label(label=result.dict_name)
            source_label.set_css_classes(["dim-label"])
            source_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            source_label.set_halign(Gtk.Align.START)
            box.append(source_label)

            row.set_child(box)
            
            # Store result by row object directly
            self.row_to_result[row] = result
            
            self.results_list.append(row)

        # Select an item if requested
        if request_id == self.current_search_request_id:
            if self.scheduled_select_first_lookup_item:
                self.scheduled_select_first_lookup_item = False
                first_child = self.results_list.get_first_child()
                if first_child:
                    self.results_list.select_row(first_child)
            elif self.scheduled_selected_lookup_item:
                print(f"Opening {self.scheduled_selected_lookup_item}")
                entry = self.scheduled_selected_lookup_item
                self.scheduled_selected_lookup_item = None
                self._activate_row_by_entry(entry)

    def _populate_bookmarks(self, filter_query: str = "") -> None:
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
            title_label = Gtk.Label(label=bookmark_item.term)
            title_label.set_ellipsize(3)
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            # Source and date
            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.set_spacing(8)
            
            source_label = Gtk.Label(label=bookmark_item.dict_name)
            source_label.set_css_classes(["dim-label"])
            source_label.set_ellipsize(3)
            source_label.set_halign(Gtk.Align.START)
            info_box.append(source_label)

            date_label = Gtk.Label(
                label=bookmark_item.created_at_formatted()
            )
            date_label.set_css_classes(["dim-label"])
            date_label.set_ellipsize(3)
            date_label.set_halign(Gtk.Align.START)
            date_label.set_hexpand(True)
            info_box.append(date_label)
            
            box.append(info_box)

            row.set_child(box)
            self.row_to_result[row] = bookmark_item
            self.results_list.append(row)

    def _populate_history(self, filter_query: str = "") -> None:
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
            title_label = Gtk.Label(label=history_item.term)
            title_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            title_label.set_halign(Gtk.Align.START)
            box.append(title_label)

            # Source and date
            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.set_spacing(8)
            
            source_label = Gtk.Label(label=history_item.dict_name)
            source_label.set_css_classes(["dim-label"])
            source_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            source_label.set_halign(Gtk.Align.START)
            info_box.append(source_label)

            date_label = Gtk.Label(
                label=history_item.created_at_formatted()
            )
            date_label.set_css_classes(["dim-label"])
            date_label.set_ellipsize(3)  # Gtk.EllipsizeMode.END
            date_label.set_halign(Gtk.Align.START)
            date_label.set_hexpand(True)
            info_box.append(date_label)
            
            box.append(info_box)

            row.set_child(box)
            self.row_to_result[row] = history_item
            self.results_list.append(row)

    def _on_result_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
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

    def _load_entry_task(self, entry: DictEntry) -> None:
        """Load entry task with cancellation support."""
        GLib.idle_add(self._render_entry, entry)
        # Add to history
        if self.settings_manager.enable_history:
            self.history_db.add_entry(entry)

    def _render_entry(self, entry: DictEntry, update_history: bool = True) -> None:
        """Render entry in webview."""
        if not hasattr(self, 'webview'):
            return

        key = quote(entry.term, safe='')
        key_id = quote(str(entry.term_id), safe='')
        source = quote(entry.dict_id, safe='')
        
        url = f"http://127.0.0.1:{self.http_port}/slob/{source}/{key}?blob={key_id}"
        print(f"Loading: {url}")
        
        # Update navigation history if this is a new entry (not from back/forward)
        if update_history:
            self.navigation_history.add(entry)
            self._update_nav_buttons()
        
        # Update header bar subtitle with current key
        self._update_content_subtitle(entry.term)
        
        self.current_entry = entry
        self._update_bookmark_button()
        self.webview.load_uri(url)

    def _update_content_subtitle(self, subtitle: str) -> None:
        """Update content subtitle"""
        title_widget: Adw.WindowTitle = self.content_header.get_title_widget()
        title_widget.set_subtitle(subtitle)

    def _on_close(self, window) -> bool:
        """Handle window close."""
        self.http_server.stop()
        self.slob_client.close() # FIXME: Move to app level
        self.settings_manager.zoom_level = self.zoom_level
        return False

    def action_lookup(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Switch to lookup view - register as app.lookup action."""
        self.current_view = "lookup"
        self._update_sidebar_title()
        self.search_entry.set_visible(True)
        self.history_search_entry.set_visible(False)
        self.search_entry.grab_focus()
        self._populate_results([])
        self.on_dictionary_updated()

    def action_bookmarks(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
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

    def action_history(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Switch to history view - register as app.history action."""
        self.current_view = "history"
        self._update_sidebar_title()
        self.search_entry.set_visible(False)
        self.history_search_entry.set_placeholder_text(_("Filter history..."))
        self.history_search_entry.set_visible(True)
        self.history_search_entry.grab_focus()
        self._populate_history()
        self.on_dictionary_updated()

    def perform_lookup(self,
        search: str,
        *,
        selected_entry: Optional[LookupEntry] = None,
        select_first: bool = False
    ) -> None:
        self.current_view = "lookup"
        self._update_sidebar_title()
        self.search_entry.set_visible(True)
        self.history_search_entry.set_visible(False)
        self.scheduled_selected_lookup_item = selected_entry
        self.scheduled_select_first_lookup_item = select_first
        self.search_entry.set_text(search)
        self.search_entry.grab_focus()

    def _activate_row_by_entry(self, entry: LookupEntry) -> Gtk.ListBoxRow:
        """
        Find and activate Gtk.ListBoxRow by key or (source and key_id).
        
        Args:
            key: Dictionary entry
            key_id: Key identifier within dictionary
            source: Dictionary identifier
        """
        if not hasattr(self, 'results_list'):
            return None
                
        # Search through row_to_result mapping
        target_row = None
        if entry.term_id and entry.dict_id:
            for row, result_data in self.row_to_result.items():
                if (result_data.dict_id == entry.dict_id and
                    result_data.term_id == entry.term_id):
                    target_row = row
                    break
        else:
            for row, result_data in self.row_to_result.items():
                if result_data.term == entry.term:
                    target_row = row
                    break
        
        if target_row:
            # Select the row
            self.results_list.select_row(target_row)
            GLib.idle_add(self._scroll_to_row, target_row, priority=GLib.PRIORITY_DEFAULT_IDLE)
            print(f"Activated: {entry}")
            return target_row
        
        return None

    def _scroll_to_row(self, target_row: Gtk.ListBoxRow) -> None:
        # Get the vertical adjustment from the ListBox or its parent ScrolledWindow
        adj = self.results_list.get_adjustment()
        # Get the row's position relative to the ListBox
        coordinates = target_row.translate_coordinates(self.results_list, 0, 0)
        if coordinates:
            # Set the scroll value (e.g., center the row)
            x, y = coordinates
            row_height = target_row.get_allocated_height()
            page_size = adj.get_page_size()
            new_value = y - (page_size / 2) + (row_height / 2)
            if row_height == 0 or page_size == 0 or new_value <= 0:
                target_row.grab_focus()
            else: adj.set_value(new_value)
        else: target_row.grab_focus()

    def _on_find_text_changed(self, entry: Gtk.SearchEntry) -> None:
        """Search as user types."""
        text = entry.get_text()
        
        if text:
            self.find_controller.search(
                text,
                WebKit.FindOptions.WRAP_AROUND | WebKit.FindOptions.CASE_INSENSITIVE,
                100  # Max 100 matches
            )
        else:
            self.find_prev_button.set_sensitive(False)
            self.find_next_button.set_sensitive(False)
            self.find_controller.search_finish()

    def _on_find_activate(self, entry: Gtk.SearchEntry) -> None:
        """Find next match on Enter."""
        self.find_controller.search_next()

    def _on_find_next(self, button: Gtk.Button) -> None:
        """Go to next match."""
        self.find_controller.search_next()

    def _on_find_prev(self, button: Gtk.Button) -> None:
        """Go to previous match."""
        self.find_controller.search_previous()

    def _on_find_close(self, *args: Gtk.Widget) -> None:
        """Close find bar."""
        self.find_controller.search_finish()
        if self.find_bar:
            self.find_bar.set_visible(False)
            self.find_entry.set_text("")

    def _on_found_text(self, controller: WebKit.FindController, match_count: int) -> None:
        """Update match count when text is found."""
        self.find_prev_button.set_sensitive(match_count > 0)
        self.find_next_button.set_sensitive(match_count > 0)

    def _on_failed_to_find_text(self, controller: WebKit.FindController) -> None:
        """Handle when search text is not found."""
        self.find_prev_button.set_sensitive(False)
        self.find_next_button.set_sensitive(False)
