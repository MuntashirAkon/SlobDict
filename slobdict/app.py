# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio
from .ui.main_window import MainWindow

class SlobDictApplication(Adw.Application):
    """Main GNOME application."""

    def __init__(self):
        super().__init__(
            application_id='dev.muntashir.SlobDictGTK',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

        from .backend.settings_manager import SettingsManager
        self.settings_manager = SettingsManager()

        # Application actions
        self._setup_actions()
        self._setup_shortcuts()
        self.connect('activate', self.on_activate)

        self._apply_appearance()
        self.settings_manager.register_callback('appearance', self._on_appearance_changed)

    def _setup_actions(self):
        """Set up application menu actions."""
        actions = [
            ('dictionaries', self.on_dictionaries),
            ('preferences', self.on_preferences),
            ('about', self.on_about),
            ('quit', lambda *_: self.quit()),
            ('lookup', self.on_search),
            ('bookmarks', self.on_bookmarks),
            ('history', self.on_history),
        ]

        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _setup_shortcuts(self):
        """Register all keyboard shortcuts."""
        self.set_accels_for_action('app.dictionaries', ['<primary>d'])
        self.set_accels_for_action('app.lookup', ['<primary>l'])
        self.set_accels_for_action('app.bookmarks', ['<primary>b'])
        self.set_accels_for_action('app.history', ['<primary>h'])
        self.set_accels_for_action('app.preferences', ['<primary>comma'])
        self.set_accels_for_action('app.quit', ['<primary>q'])

    def on_activate(self, app):
        """Callback for application activation."""
        window = MainWindow(application=self, settings_manager=self.settings_manager)
        window.present()

    def _apply_appearance(self):
        """Apply the current appearance setting."""
        appearance = self.settings_manager.get('appearance', 'system')
        
        if appearance == 'light':
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif appearance == 'dark':
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)

    def _on_appearance_changed(self, key, value):
        """Handle appearance setting change."""
        self._apply_appearance()


    def on_dictionaries(self, action, param):
        """Open dictionaries manager."""
        from .ui.dictionaries_dialog import DictionariesDialog
        window = self.get_active_window()
        dialog = DictionariesDialog(window, window.slob_client)
        dialog.set_visible(True)

    def on_preferences(self, action, param):
        """Open preferences dialog."""
        from .ui.preferences_dialog import PreferencesDialog
        dialog = PreferencesDialog(self.get_active_window(), self.settings_manager)
        dialog.set_visible(True)

    def on_search(self, action, param):
        """Handle search action (Ctrl+L)."""
        window = self.get_active_window()
        window.action_lookup(action, param)

    def on_bookmarks(self, action, param):
        """Handle history action (Ctrl+B)."""
        window = self.get_active_window()
        window.action_bookmarks(action, param)

    def on_history(self, action, param):
        """Handle history action (Ctrl+H)."""
        window = self.get_active_window()
        window.action_history(action, param)

    def on_about(self, action, param):
        """Open about dialog."""
        from .constants import version, app_id
        about = Adw.AboutWindow(transient_for=self.get_active_window())
        about.set_application_name("Slob Dictionary")
        about.set_application_icon(app_id)
        about.set_version(version)
        about.set_developer_name("Muntashir Al-Islam")
        about.set_developers(["Muntashir Al-Islam"])
        about.set_designers(["Muntashir Al-Islam"])
        about.set_copyright("© 2025 Muntashir Al-Islam")
        about.set_license_type(Gtk.License.AGPL_3_0)
        about.set_website("https://github.com/MuntashirAkon/slob-dict-gtk")
        about.set_issue_url("https://github.com/MuntashirAkon/slob-dict-gtk/issues")

        about.set_visible(True)
