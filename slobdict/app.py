# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")

import os
import sys
from argparse import ArgumentParser, Namespace
from gi.repository import Gtk, Adw, Gio, GLib
from typing import List, Optional
from .backend.slob_client import SlobClient
from .constants import app_id
from .search_provider import SlobDictSearchProvider
from .ui.main_window import MainWindow
from .utils.i18n import _


class SlobDictApplication(Adw.Application):
    """Main application."""

    def __init__(self) -> None:
        super().__init__(
            application_id=app_id,
            flags=Gio.ApplicationFlags.HANDLES_OPEN |
                Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )

        from .backend.settings_manager import SettingsManager
        self.settings_manager = SettingsManager()

        # Initialize dictionary backend early
        # This allows search provider to work even when no window is open
        self.slob_client = SlobClient(self._on_dictionary_updated)

        # D-Bus search provider
        self.search_provider: Optional[SlobDictSearchProvider] = None
        self.search_provider_registration: Optional[int] = None
        self.dbus_connection: Optional[Gio.DBusConnection] = None

        # Application actions
        self._setup_actions()
        self._setup_shortcuts()
        self.connect('activate', self.on_activate)

        self._apply_appearance()
        self.settings_manager.register_callback('appearance', self._on_appearance_changed)
    
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

    def do_open(self, files: List[Gio.File], hint: str) -> None:
        """
        Handle custom URI: slobdict://
        """
        window = self.get_active_window()
        if not window:
            self.activate()
            window = self.get_active_window()

        if window:
            window.present()
        
        # Convert Gio.File objects to URIs
        uri_list = []
        for file in files:
            uri = file.get_uri()
            print(f"do_open: File URI: {uri}")
            if uri.startswith("slobdict://"):
                uri_list.append(uri)
        
        # Process URIs after window is ready
        if uri_list:
            # Use idle_add to ensure window is fully created
            GLib.idle_add(self._process_uris, uri_list, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """
        Handle command-line arguments.
        
        Usage:
        slobdict search <search_term> [--cli-only] [--dictionary dict1,dict2]
        slobdict lookup <term> [--cli-only] [--dictionary dict1,dict2] [--search search_text]
        """
        args = command_line.get_arguments()
        
        # If no arguments provided, just activate GUI normally
        if len(args) <= 1:
            self.activate()
            return 0

        try:
            # Parse arguments
            namespace = self._parse_cli_args(args[1:])
            
            if namespace.cli_only:
                # CLI mode - don't activate GUI
                result = self._handle_cli_mode(namespace)
                return result
            else:
                # GUI mode - activate and process
                self.activate()
                GLib.idle_add(self._handle_gui_mode, namespace)
                return 0
                
        except SystemExit:
            # argparse calls sys.exit() on error
            return 1
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def do_dbus_register(self, connection: Gio.DBusConnection, object_path: str) -> bool:
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

    def do_dbus_unregister(self, connection: Gio.DBusConnection, object_path: str) -> None:
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

    def _setup_actions(self) -> None:
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

    def _setup_shortcuts(self) -> None:
        """Register all keyboard shortcuts."""
        self.set_accels_for_action('app.dictionaries', ['<primary>d'])
        self.set_accels_for_action('app.lookup', ['<primary>l'])
        self.set_accels_for_action('app.bookmarks', ['<primary>b'])
        self.set_accels_for_action('app.history', ['<primary>h'])
        self.set_accels_for_action('app.preferences', ['<primary>comma'])
        self.set_accels_for_action('app.quit', ['<primary>q'])

        self.set_accels_for_action('win.zoom-in', ["<primary>plus", "<primary>equal"])
        self.set_accels_for_action('win.zoom-out', ['<primary>minus'])
        self.set_accels_for_action('win.zoom-reset', ['<primary>0'])
        self.set_accels_for_action('win.find-in-page', ['<primary>f'])
        self.set_accels_for_action('win.print', ['<primary>p'])

    def on_activate(self, app: Gio.Application) -> None:
        """Callback for application activation."""
        window = MainWindow(app=self, settings_manager=self.settings_manager, slob_client=self.slob_client)
        window.present()

    def _apply_appearance(self) -> None:
        """Apply the current appearance setting."""
        appearance = self.settings_manager.appearance
        
        if appearance == 'light':
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif appearance == 'dark':
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)

    def _on_appearance_changed(self, key: str, value: bool) -> None:
        """Handle appearance setting change."""
        self._apply_appearance()
    
    def _on_dictionary_updated(self) -> None:
        window = self.get_active_window()
        if window:
            window.on_dictionary_updated()

    def on_dictionaries(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Open dictionaries manager."""
        from .ui.dictionaries_dialog import DictionariesDialog
        window = self.get_active_window()
        dialog = DictionariesDialog(window, self.slob_client)
        dialog.set_visible(True)

    def on_preferences(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Open preferences dialog."""
        from .ui.preferences_dialog import PreferencesDialog
        dialog = PreferencesDialog(self.get_active_window(), self.settings_manager)
        dialog.set_visible(True)

    def on_search(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Handle search action (Ctrl+L)."""
        window: MainWindow = self.get_active_window()
        window.action_lookup(action, param)

    def on_bookmarks(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Handle history action (Ctrl+B)."""
        window: MainWindow = self.get_active_window()
        window.action_bookmarks(action, param)

    def on_history(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
        """Handle history action (Ctrl+H)."""
        window: MainWindow = self.get_active_window()
        window.action_history(action, param)

    def on_about(self, action: Gio.SimpleAction, param: GLib.Variant) -> None:
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

    def _process_uris(self, uri_list: List[str]) -> bool:
        """
        Process URIs after window is created and ready.
        """
        window = self.get_active_window()
        if not window:
            print("_process_uris: Window not ready yet, retrying...")
            return True  # Retry
        
        print(f"_process_uris: Window ready, processing {len(uri_list)} URIs")
        
        for uri in uri_list:
            self._handle_uri(uri)
        
        return False  # Don't retry

    def _handle_uri(self, uri: str) -> bool:
        """
        Handle slobdict:// URI schemes.
        
        Supported formats:
        - slobdict://search/{search_term}
        - slobdict://lookup/{word}
        - slobdict://lookup/{search_term}/{word}
        """
        try:
            from urllib.parse import urlparse, unquote
            from pathlib import PurePosixPath
            
            parsed = urlparse(uri)
            if parsed.scheme != 'slobdict':
                print(f"URI: Invalid scheme {parsed.scheme}")
                return False

            action = parsed.netloc
            if action not in ('lookup', 'search'):
                print(f"URI: Invalid action {action}")
                return False
            
            path_parts = [unquote(part) for part in PurePosixPath(parsed.path).parts]
            if not path_parts:
                return False
                        
            if action == 'search':
                # slobdict://search/{search_term}
                if len(path_parts) == 2:
                    search_term = path_parts[1]
                    GLib.idle_add(self._perform_search, search_term)
                    print(f"URI: search '{search_term}'")
                else:
                    print("URI: Invalid search format, expects exactly 1 argument: search_term")
            elif action == 'lookup':
                # slobdict://lookup/{word} OR slobdict://lookup/{search_term}/{word}
                if len(path_parts) == 2:
                    # slobdict://lookup/{word}
                    word = path_parts[1]
                    GLib.idle_add(self._perform_lookup, word)
                    print(f"URI: lookup '{word}'")
                elif len(path_parts) >= 3:
                    # slobdict://lookup/{search_term}/{word}
                    search_term = path_parts[1]
                    word = path_parts[2]
                    GLib.idle_add(self._perform_lookup_with_search, search_term, word)
                    print(f"URI: lookup search='{search_term}' word='{word}'")
                else:
                    print("URI: Invalid lookup format, expects 1 or 2 arguments: word and search_term")
        except Exception as e:
            print(f"URI Handler error: {e}")
            import traceback
            traceback.print_exc()
        return False

    def _parse_cli_args(self, args: List[str]) -> Namespace:
        """Parse command-line arguments."""
        parser = ArgumentParser(prog='slobdict', description='Slob Dictionary')
        subparsers = parser.add_subparsers(dest='action', required=True)
        
        # search action
        search_parser = subparsers.add_parser('search', help=_('Look for terms'))
        search_parser.add_argument('search_term', help=_('Term to look for'))
        search_parser.add_argument('--cli-only', '-k', action='store_true', help=_('Print results to console only'))
        search_parser.add_argument('--dictionary', '-d', type=str, help=_('Comma-separated list of dictionaries'))
        
        # lookup action
        lookup_parser = subparsers.add_parser('lookup', help=_('Lookup a term'))
        lookup_parser.add_argument('term', help=_('Term to lookup'))
        lookup_parser.add_argument('--cli-only', '-k', action='store_true', help=_('Print definition to console only'))
        lookup_parser.add_argument('--dictionary', '-d', type=str, help=_('Comma-separated list of dictionaries'))
        lookup_parser.add_argument('--search', '-s', type=str, help=_('Search text to display in GUI'))
    
        namespace = parser.parse_args(args)
        return namespace

    def _handle_cli_mode(self, namespace: Namespace) -> int:
        """Handle CLI-only mode (no GUI)."""
        try:
            dict_filter = None
            if hasattr(namespace, 'dictionary') and namespace.dictionary:
                dict_filter = set(d.strip() for d in namespace.dictionary.split(','))
            
            if namespace.action == 'search':
                return self._cli_search(namespace.search_term, dict_filter)
            elif namespace.action == 'lookup':
                return self._cli_lookup(namespace.term, dict_filter)
            
            return 1
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def _handle_gui_mode(self, namespace: Namespace) -> bool:
        """Handle GUI mode - activate window and process arguments."""
        try:
            window: MainWindow = self.get_active_window()
            if not window:
                self.activate()
                window = self.get_active_window()
            if not window:
                print("Error: Failed to create window")
                return False
            
            window.present()
            
            if namespace.action == 'search':
                window.perform_lookup(namespace.search_term)
                print(f"GUI: Search for '{namespace.search_term}'")
                return False
            elif namespace.action == 'lookup':
                is_search_term_different = hasattr(namespace, 'search') and namespace.search
                search_term = namespace.search if is_search_term_different else namespace.term
                if is_search_term_different:
                    entry = MainWindow.LookupEntry(term=namespace.term)
                    window.perform_lookup(search_term, selected_entry=entry)
                else:
                    window.perform_lookup(search_term, select_first=True)
                print(f"GUI: Lookup '{namespace.term}'")
                return False
            return False
        except Exception as e:
            print(f"Error in GUI mode: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _perform_search(self, search_term: str) -> None:
        """Perform regular search."""
        window: MainWindow = self.get_active_window()
        if not window:
            self.activate()
            window = self.get_active_window()
        
        if window:
            window.perform_lookup(search_term)

    def _perform_lookup(self, word: str) -> None:
        """Lookup and open first matched word."""
        window: MainWindow = self.get_active_window()
        if not window:
            self.activate()
            window = self.get_active_window()
        
        if window:
            window.perform_lookup(word, select_first=True)

    def _perform_lookup_with_search(self, search_term: str, word: str) -> None:
        """Search for term, then select specific word."""
        window: MainWindow = self.get_active_window()
        if not window:
            self.activate()
            window = self.get_active_window()
        
        if window:
            entry = MainWindow.LookupEntry(term=word)
            window.perform_lookup(search_term, selected_entry=entry)

    def _cli_search(self, search_term: str, dict_filter: Optional[set] = None) -> int:
        """CLI search - print matching terms. Format: {key} {dictionary_name}"""
        try:
            matches = self.slob_client.search(search_term)
            
            if not matches:
                print(_("No matches found for '%s'") % search_term, file=sys.stderr)
                return 1
            
            found_count = 0
            for match in matches:
                try:
                    dict_name = match.dict_name
                    if dict_filter and dict_name not in dict_filter:
                        continue
                    
                    line = f"\033[1m{match.term}\033[0m \033[4min\033[0m \033[3m{dict_name}\033[0m"
                    print(line)
                    found_count += 1
                except Exception as e:
                    print(f"Error processing match: {e}", file=sys.stderr)
            return 0 if found_count > 0 else 1
        except Exception as e:
            print(f"Search error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1
    
    def _cli_lookup(self, term: str, dict_filter: Optional[set] = None) -> int:
        """CLI lookup - print definitions."""
        try:
            definitions = self._get_definitions(term, dict_filter)
            
            if not definitions:
                print(_("No definition found for '%s'") % term, file=sys.stderr)
                return 1
            
            from rich.console import Console
            from rich.markdown import Markdown
            
            for dict_name, definition in definitions:
                title = "\033[1;4m" + (_("From %s:") % dict_name) + "\033[0m"
                print(title)
                console = Console()
                console.print(Markdown(definition))
                print()
            
            return 0
        except Exception as e:
            print(f"Lookup error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def _get_definitions(self, term: str, dict_filter: Optional[set] = None) -> List[tuple]:
        """Get definitions from slob_client for a term."""
        definitions = []
        try:
            matches = self.slob_client.search(term)
            for match in matches:
                if match.term != term:
                    continue
                
                dict_name = match.dict_name
                if dict_filter and dict_name not in dict_filter:
                    continue

                entry = self.slob_client.get_entry(match.term, match.term_id, match.dict_id)

                if not entry:
                    continue

                content = entry.content
                content_type = entry.content_type

                if content_type.startswith('text/html'):
                    # Convert HTML to plain text
                    from .utils.utils import html_to_markdown, inline_stylesheets

                    self.last_source = match.dict_id
                    content = content.decode('utf-8') if isinstance(content, bytes) else content
                    content = inline_stylesheets(content, on_css=self.external_css_handler)
                    text = html_to_markdown(content)
                    definitions.append((dict_name, text))
                elif content_type.startswith('text/'):
                    # Plain text content
                    definitions.append((dict_name, content))
                elif content_type.startswith('image/'):
                    # For images, show metadata/placeholder
                    image_info = f"[Image: {content_type}]"
                    definitions.append((dict_name, image_info))
                else:
                    # Unsupported content type
                    definitions.append((dict_name, f"[{content_type}]"))
        except Exception as e:
            print(f"Error getting definitions: {e}", file=sys.stderr)
        
        return definitions

    def external_css_handler(self, href: str) -> Optional[str]:
        if not hasattr(self, 'last_source'):
            return None

        entry = self.slob_client.get_entry(href, None, self.last_source)
        if not entry:
            return None

        content = entry.content
        return content.decode('utf-8') if isinstance(content, bytes) else content
