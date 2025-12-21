# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw
from ..backend.settings_manager import SettingsManager
from ..backend.history_db import HistoryDB
from ..backend.bookmarks_db import BookmarksDB


class PreferencesDialog(Adw.PreferencesWindow):
    """Preferences dialog for application settings."""

    def __init__(self, parent, settings_manager):
        """Initialize preferences dialog."""
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Preferences"))
        
        self.settings_manager = settings_manager
        self.history_db = HistoryDB()
        self.bookmarks_db = BookmarksDB()
        
        # Create preferences page
        page = Adw.PreferencesPage()
        page.set_title(_("Preferences"))
        page.set_icon_name("preferences-system-symbolic")
        self.add(page)
        
        # Appearance section
        appearance_group = Adw.PreferencesGroup()
        appearance_group.set_title(_("Appearance"))
        page.add(appearance_group)
        
        # Appearance style selector
        appearance_row = Adw.ComboRow()
        appearance_row.set_title(_("Theme"))
        appearance_row.set_subtitle(_("Choose application theme"))
        
        appearance_model = Gtk.StringList()
        appearance_model.append(_("System"))
        appearance_model.append(_("Light"))
        appearance_model.append(_("Dark"))
        appearance_row.set_model(appearance_model)
        
        # Set current appearance
        current_appearance = self.settings_manager.get('appearance', 'system')
        appearance_map = {'system': 0, 'light': 1, 'dark': 2}
        appearance_row.set_selected(appearance_map.get(current_appearance, 0))
        appearance_row.connect("notify::selected-item", self._on_appearance_changed)
        appearance_group.add(appearance_row)
        
        # Force dark mode switch
        force_dark_row = Adw.SwitchRow()
        force_dark_row.set_title(_("Force Dark Mode"))
        force_dark_row.set_subtitle(_("Apply dark mode to web content"))
        force_dark_enabled = self.settings_manager.get('force_dark_mode', True)
        force_dark_row.set_active(force_dark_enabled)
        force_dark_row.connect("notify::active", self._on_force_dark_changed)
        appearance_group.add(force_dark_row)
        
        # Content section
        content_group = Adw.PreferencesGroup()
        content_group.set_title(_("Content"))
        page.add(content_group)
        
        # Load remote content switch
        remote_content_row = Adw.SwitchRow()
        remote_content_row.set_title(_("Load Remote Content"))
        remote_content_row.set_subtitle(_("Load images and resources from the internet"))
        remote_enabled = self.settings_manager.get('load_remote_content', False)
        remote_content_row.set_active(remote_enabled)
        remote_content_row.connect("notify::active", self._on_remote_content_changed)
        content_group.add(remote_content_row)
        
        # Enable JavaScript switch
        javascript_row = Adw.SwitchRow()
        javascript_row.set_title(_("Enable JavaScript"))
        javascript_row.set_subtitle(_("Allow scripts in web content"))
        javascript_enabled = self.settings_manager.get('enable_javascript', True)
        javascript_row.set_active(javascript_enabled)
        javascript_row.connect("notify::active", self._on_javascript_changed)
        content_group.add(javascript_row)
        
        # History section
        history_group = Adw.PreferencesGroup()
        history_group.set_title(_("History"))
        page.add(history_group)
        
        # Enable history switch
        history_row = Adw.SwitchRow()
        history_row.set_title(_("Enable History"))
        history_row.set_subtitle(_("Save and display search history"))
        history_enabled = self.settings_manager.get('enable_history', True)
        history_row.set_active(history_enabled)
        history_row.connect("notify::active", self._on_history_enabled_changed)
        history_group.add(history_row)
        
        # Clear history button
        clear_history_button = Gtk.Button(label=_("Clear History"))
        clear_history_button.set_css_classes(["destructive-action"])
        clear_history_button.connect("clicked", self._on_clear_history_clicked)
        history_group.add(clear_history_button)
        
        # Bookmarks section
        bookmarks_group = Adw.PreferencesGroup()
        bookmarks_group.set_title(_("Bookmarks"))
        page.add(bookmarks_group)
        
        # Clear bookmarks button
        clear_bookmarks_button = Gtk.Button(label=_("Clear Bookmarks"))
        clear_bookmarks_button.set_css_classes(["destructive-action"])
        clear_bookmarks_button.connect("clicked", self._on_clear_bookmarks_clicked)
        bookmarks_group.add(clear_bookmarks_button)
        
        # Data section
        data_group = Adw.PreferencesGroup()
        data_group.set_title(_("Data"))
        page.add(data_group)
        
        # Clear cache button
        clear_cache_button = Gtk.Button(label=_("Clear Web Cache"))
        clear_cache_button.set_css_classes(["destructive-action"])
        clear_cache_button.connect("clicked", self._on_clear_cache_clicked)
        data_group.add(clear_cache_button)
        
        # Store references to update switches if needed
        self.force_dark_row = force_dark_row
        self.remote_content_row = remote_content_row
        self.javascript_row = javascript_row
        self.history_row = history_row

    def _on_appearance_changed(self, combo_row, param):
        """Handle appearance selection change."""
        selected = combo_row.get_selected()
        appearance_map = {0: 'system', 1: 'light', 2: 'dark'}
        appearance = appearance_map.get(selected, 'system')
        self.settings_manager.set('appearance', appearance)

    def _on_force_dark_changed(self, switch_row, param):
        """Handle force dark mode toggle."""
        enabled = switch_row.get_active()
        self.settings_manager.set('force_dark_mode', enabled)

    def _on_remote_content_changed(self, switch_row, param):
        """Handle remote content toggle."""
        enabled = switch_row.get_active()
        self.settings_manager.set('load_remote_content', enabled)

    def _on_javascript_changed(self, switch_row, param):
        """Handle JavaScript toggle."""
        enabled = switch_row.get_active()
        self.settings_manager.set('enable_javascript', enabled)

    def _on_history_enabled_changed(self, switch_row, param):
        """Handle history enabled toggle."""
        enabled = switch_row.get_active()
        self.settings_manager.set('enable_history', enabled)

    def _on_clear_history_clicked(self, button):
        """Handle clear history button click."""
        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading(_("Clear History?"))
        dialog.set_body(_("Are you sure you want to clear all search history? This action cannot be undone."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "clear":
                try:
                    self.history_db.clear_history()
                    self._show_notification(_("History cleared"))
                except Exception as e:
                    print(f"Error clearing history: {e}")
                    self._show_error(_("Failed to clear history"))
        
        dialog.connect("response", on_response)
        dialog.present()

    def _on_clear_bookmarks_clicked(self, button):
        """Handle clear bookmarks button click."""
        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading(_("Clear Bookmarks?"))
        dialog.set_body(_("Are you sure you want to clear all bookmarks? This action cannot be undone."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "clear":
                try:
                    self.bookmarks_db.clear_bookmarks()
                    self._show_notification(_("Bookmarks cleared"))
                except Exception as e:
                    print(f"Error clearing bookmarks: {e}")
                    self._show_error(_("Failed to clear bookmarks"))
        
        dialog.connect("response", on_response)
        dialog.present()

    def _on_clear_cache_clicked(self, button):
        """Handle clear cache button click."""
        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading(_("Clear Web Cache?"))
        dialog.set_body(_("Are you sure you want to clear the web cache? This will free up disk space."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("clear", _("Clear"))
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "clear":
                if self._clear_webview_cache():
                    self._show_notification(_("Cache cleared"))
                else:
                    self._show_error(_("Failed to clear cache"))
        
        dialog.connect("response", on_response)
        dialog.present()

    def _clear_webview_cache(self) -> bool:
        """Clear WebView cache."""
        try:
            from gi.repository import WebKit
            gi.require_version("WebKit", "6.0")

            webview = WebKit.WebView()
            manager = webview.get_network_session().get_website_data_manager()
            data_types = WebKit.WebsiteDataTypes.DISK_CACHE | WebKit.WebsiteDataTypes.MEMORY_CACHE
            manager.clear(data_types, 0, None, None, None)
            return True
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return False

    def _show_notification(self, message: str):
        """Show a notification."""
        parent = self.get_root()
        if isinstance(parent, Adw.ApplicationWindow):
            toast = Adw.Toast(title=message)
            parent.add_toast(toast)

    def _show_error(self, message: str):
        """Show an error dialog."""
        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading(_("Error"))
        dialog.set_body(message)
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.present()
