# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")

import os
from gi.repository import Gtk, Adw, Gio, GLib
from .ui.main_window import MainWindow
from .constants import app_id
from .search_provider import SlobDictSearchProvider


class SlobDictApplication(Adw.Application):
    """Main GNOME application."""

    def __init__(self):
        super().__init__(
            application_id=app_id,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )

        from .backend.settings_manager import SettingsManager
        self.settings_manager = SettingsManager()

        # Initialize dictionary backend early
        # This allows search provider to work even when no window is open
        self.slob_client = self._init_slob_client()

        # D-Bus search provider
        self.search_provider = None
        self.search_provider_registration = None
        self.dbus_connection = None

        # Application actions
        self._setup_actions()
        self._setup_shortcuts()
        self.connect('activate', self.on_activate)

        self._apply_appearance()
        self.settings_manager.register_callback('appearance', self._on_appearance_changed)

    def _init_slob_client(self):
        """
        Initialize the dictionary backend without needing a window.
        
        This runs at app startup so that:
        1. Search provider can access it immediately
        2. Dictionary works before any window is created
        3. No UI overhead in search operations
        
        Returns:
            SlobManager instance or None if initialization fails
        """
        try:
            from .backend.slob_client import SlobClient
            return SlobClient(self._on_dictionary_updated)
        except Exception as e:
            print(f"Failed to initialize slob_client: {e}")
            return None

    def do_dbus_register(self, connection, object_path):
        """
        Override to register D-Bus SearchProvider2 interface.
        Called when the application is registered on D-Bus.
        
        Note: In Python GObject bindings, this method receives connection and object_path
        as positional arguments, different from the C signature.
        """
        try:
            # Store connection for later use in do_dbus_unregister
            self.dbus_connection = connection
            
            # Only register search provider on GNOME
            desktop = os.environ.get('XDG_CURRENT_DESKTOP', '')
            if 'GNOME' not in desktop:
                return True

            # Create search provider
            self.search_provider = SlobDictSearchProvider(self)

            # Register the interface
            provider_path = f"{object_path}/SearchProvider"
            self.search_provider_registration = connection.register_object(
                provider_path,
                self.search_provider.interface_info,
                self.search_provider.handle_method_call,
                None,
                None
            )

            print(f"SearchProvider2 interface registered at {provider_path}")
            return True

        except Exception as e:
            print(f"Failed to register SearchProvider2: {e}")
            return False

    def do_dbus_unregister(self, connection, object_path):
        """
        Override to unregister D-Bus SearchProvider2 interface.
        Called when the application is unregistered from D-Bus.
        
        Note: In Python GObject bindings, this method receives connection and object_path
        as positional arguments, different from the C signature.
        """
        if self.search_provider_registration is not None:
            try:
                connection.unregister_object(self.search_provider_registration)
                self.search_provider_registration = None
            except Exception as e:
                print(f"Failed to unregister SearchProvider2: {e}")

        self.search_provider = None
        self.dbus_connection = None

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
        window = MainWindow(application=self, settings_manager=self.settings_manager, slob_client=self.slob_client)
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
    
    def _on_dictionary_updated(self):
        window = self.get_active_window()
        if window:
            window.on_dictionary_updated()

    def on_dictionaries(self, action, param):
        """Open dictionaries manager."""
        from .ui.dictionaries_dialog import DictionariesDialog
        window = self.get_active_window()
        dialog = DictionariesDialog(window, self.slob_client)
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
        from .constants import version
        about = Adw.AboutWindow(transient_for=self.get_active_window())
        about.set_application_name("Slob Dictionary")
        about.set_application_icon(app_id)
        about.set_version(version)
        about.set_developer_name("Muntashir Al-Islam")
        about.set_developers(["Muntashir Al-Islam"])
        about.set_designers(["Muntashir Al-Islam"])
        about.set_copyright("© 2025 Muntashir Al-Islam")
        about.set_license_type(Gtk.License.AGPL_3_0)
        about.set_website("https://github.com/MuntashirAkon/SlobDict")
        about.set_issue_url("https://github.com/MuntashirAkon/SlobDict/issues")

        about.set_visible(True)
