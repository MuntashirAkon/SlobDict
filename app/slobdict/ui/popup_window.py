# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")

from gi.repository import Gdk, Gio, GLib, Gtk, WebKit
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from ..backend.http_server import HTTPServer_
from ..utils.i18n import _

POPUP_WIDTH = 540


class LookupPopupWindow(Gtk.ApplicationWindow):
    """Compact WebKit window for a lookup requested by the GNOME extension."""

    def __init__(self, app, search_term: str, slob_client, open_main_window) -> None:
        super().__init__(application=app)
        self.search_term = search_term
        self.slob_client = slob_client
        self.open_main_window = open_main_window
        self.entries = []
        self.selected_index = 0
        self.server = HTTPServer_(slob_client, port=0)
        self.server.start()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._focus_timeout_id = None
        self._has_been_active = False

        self.set_title("SlobDict Lookup")
        self.set_default_size(POPUP_WIDTH, 420)
        self.set_resizable(False)
        self.set_decorated(True)
        header_bar = Gtk.HeaderBar()
        header_bar.set_show_title_buttons(False)
        header_bar.set_title_widget(Gtk.Box())
        header_bar.set_visible(False)
        self.set_titlebar(header_bar)

        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(b"""
            .lookup-popup-card {
                background-color: @theme_base_color;
                border-radius: 12px;
            }
            button.dictionary-tab {
                background-color: transparent;
                box-shadow: none;
                border-color: transparent;
            }
            button.dictionary-tab:checked {
                background-color: color-mix(in srgb, currentColor 10%, transparent);
            }
            button.dictionary-tab:hover:not(:checked) {
                background-color: color-mix(in srgb, currentColor 7%, transparent);
            }
            button.dictionary-tab:active:not(:checked) {
                background-color: color-mix(in srgb, currentColor 16%, transparent);
            }
            button.dictionary-tab:checked:hover {
                background-color: color-mix(in srgb, currentColor 13%, transparent);
            }
            button.dictionary-tab:checked:active {
                background-color: color-mix(in srgb, currentColor 19%, transparent);
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("lookup-popup-card")
        root.set_overflow(Gtk.Overflow.HIDDEN)
        root.set_hexpand(True)
        self.set_child(root)

        manager = WebKit.UserContentManager()
        self.webview = WebKit.WebView(user_content_manager=manager)
        web_settings = self.webview.get_settings()
        web_settings.set_property("enable-javascript", app.settings_manager.enable_javascript)
        self.webview.set_zoom_level(app.settings_manager.zoom_level)
        if app.settings_manager.force_dark:
            from ..utils.utils import load_dark_mode_css
            manager.add_style_sheet(WebKit.UserStyleSheet(
                load_dark_mode_css(),
                WebKit.UserContentInjectedFrames.ALL_FRAMES,
                WebKit.UserStyleLevel.USER,
                None,
                None
            ))
        self.webview.connect("resource-load-started", self._on_resource_load_started)
        self.webview.set_hexpand(True)
        self.webview.set_vexpand(True)
        self.webview.connect("decide-policy", self._on_decide_policy)
        content_scroll = Gtk.ScrolledWindow()
        content_scroll.set_child(self.webview)
        content_scroll.set_hexpand(True)
        content_scroll.set_vexpand(True)
        # Keep the WebKit surface below the rounded top edge without adding
        # horizontal inset to the definition content.
        content_scroll.set_margin_top(12)
        root.append(content_scroll)

        root.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        open_button = Gtk.Button(label=_("Open in Slob Dictionary"))
        open_button.add_css_class("flat")
        open_button.connect("clicked", self._on_open_main)
        root.append(open_button)

        root.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        dictionary_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dictionary_row.set_margin_start(6)
        dictionary_row.set_margin_end(6)
        dictionary_row.set_margin_top(4)
        dictionary_row.set_margin_bottom(4)
        root.append(dictionary_row)

        self.previous_button = Gtk.Button.new_from_icon_name("pan-start-symbolic")
        self.previous_button.add_css_class("flat")
        self.previous_button.connect("clicked", lambda *_: self._navigate_dictionary(-1))
        dictionary_row.append(self.previous_button)

        self.dictionary_scroll = Gtk.ScrolledWindow()
        self.dictionary_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.dictionary_scroll.set_hexpand(True)
        self.dictionary_scroll.set_size_request(1, -1)
        self.dictionary_scroll.set_min_content_width(1)
        self.dictionary_scroll.set_propagate_natural_width(False)
        dictionary_row.append(self.dictionary_scroll)

        self.dictionary_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.dictionary_buttons.set_hexpand(True)
        self.dictionary_scroll.set_child(self.dictionary_buttons)

        self.next_button = Gtk.Button.new_from_icon_name("pan-end-symbolic")
        self.next_button.add_css_class("flat")
        self.next_button.connect("clicked", lambda *_: self._navigate_dictionary(1))
        dictionary_row.append(self.next_button)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)
        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request", self._on_close)

        self._set_status(_("Looking up…"))
        self.executor.submit(self._find_entries)

    def _find_entries(self) -> None:
        try:
            matches = self.slob_client.search(self.search_term, limit=100)
            exact = [entry for entry in matches if entry.term.casefold() == self.search_term.casefold()]
            selected = exact or matches
            # Show one matching entry per dictionary, preferring the exact spelling.
            unique = {}
            for entry in selected:
                unique.setdefault(entry.dict_id, entry)
            GLib.idle_add(self._set_entries, list(unique.values()))
        except Exception:
            GLib.idle_add(self._set_status, _("No definition found"))

    def _set_entries(self, entries) -> bool:
        self.entries = entries
        while child := self.dictionary_buttons.get_first_child():
            self.dictionary_buttons.remove(child)

        for index, entry in enumerate(entries):
            button = Gtk.ToggleButton(label=entry.dict_name)
            button.add_css_class("dictionary-tab")
            if index:
                button.set_group(self.dictionary_buttons.get_first_child())
            button.connect("toggled", self._on_dictionary_toggled, index)
            self.dictionary_buttons.append(button)

        if not entries:
            self._update_dictionary_navigation()
            self._set_status(_("No definition found"))
            return GLib.SOURCE_REMOVE

        self._update_dictionary_navigation()
        self._select_dictionary(0)
        return GLib.SOURCE_REMOVE

    def _select_dictionary(self, index: int) -> None:
        if not self.entries:
            return
        self.selected_index = index
        entry = self.entries[index]
        button = self.dictionary_buttons.get_first_child()
        for _ in range(index):
            button = button.get_next_sibling()
        if button and not button.get_active():
            button.set_active(True)
        self._update_dictionary_navigation()
        self._scroll_dictionary_into_view(button)

        key = quote(entry.term, safe="")
        source = quote(entry.dict_id, safe="")
        url = f"http://127.0.0.1:{self.server.get_port()}/slob/{source}/{key}?blob={entry.term_id}"
        self.webview.load_uri(url)

    def _on_dictionary_toggled(self, button, index: int) -> None:
        if button.get_active() and index != self.selected_index:
            self._select_dictionary(index)

    def _navigate_dictionary(self, direction: int) -> None:
        index = self.selected_index + direction
        if 0 <= index < len(self.entries):
            self._select_dictionary(index)

    def _update_dictionary_navigation(self) -> None:
        self.previous_button.set_sensitive(self.selected_index > 0)
        self.next_button.set_sensitive(self.selected_index < len(self.entries) - 1)

    def _scroll_dictionary_into_view(self, button) -> None:
        if not button:
            return
        success, bounds = button.compute_bounds(self.dictionary_buttons)
        if not success:
            return

        adjustment = self.dictionary_scroll.get_hadjustment()
        left = bounds.origin.x
        right = left + bounds.size.width
        value = adjustment.get_value()
        page_size = adjustment.get_page_size()
        if left < value:
            adjustment.set_value(left)
        elif right > value + page_size:
            adjustment.set_value(right - page_size)

    def _set_status(self, message: str) -> None:
        html = f"<html><body style='font: 1.1em sans-serif; padding: 24px'>{message}</body></html>"
        self.webview.load_html(html, "about:blank")

    def _on_open_main(self, button) -> None:
        if self.entries:
            self.open_main_window(self.entries[self.selected_index])
        self.close()

    def _on_decide_policy(self, webview, decision, decision_type) -> bool:
        if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            request = decision.get_navigation_action().get_request()
            uri = request.get_uri()
            if uri and not uri.startswith("http://127.0.0.1:") and not uri.startswith("about:"):
                Gio.AppInfo.launch_default_for_uri(uri, None)
                decision.ignore()
                return True
        return False

    def _on_resource_load_started(self, webview, resource, request) -> None:
        uri = request.get_uri()
        if not self.get_application().settings_manager.load_remote_content and uri and not (
            uri.startswith("http://127.0.0.1") or
            uri.startswith("data:") or
            uri.startswith("about:")
        ):
            request.set_uri("about:blank")

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_active_changed(self, window, pspec) -> None:
        if self.get_property("is-active"):
            self._has_been_active = True
            if self._focus_timeout_id:
                GLib.Source.remove(self._focus_timeout_id)
                self._focus_timeout_id = None
            return

        if self._has_been_active and not self._focus_timeout_id:
            self._focus_timeout_id = GLib.timeout_add(
                180,
                self._close_if_inactive
            )

    def _close_if_inactive(self) -> bool:
        self._focus_timeout_id = None
        if not self.get_property("is-active"):
            self.close()
        return GLib.SOURCE_REMOVE

    def _on_close(self, window) -> bool:
        if self._focus_timeout_id:
            GLib.Source.remove(self._focus_timeout_id)
            self._focus_timeout_id = None
        self.server.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        Gtk.StyleContext.remove_provider_for_display(
            Gdk.Display.get_default(),
            self._css_provider
        )
        return False
