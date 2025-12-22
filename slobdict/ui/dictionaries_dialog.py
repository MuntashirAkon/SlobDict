# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio


class DictionariesDialog(Adw.Window):
    """Dialog for managing dictionaries."""

    def __init__(self, parent, slob_client):
        """Initialize dictionaries dialog."""
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(700, 500)
        self.set_title(_("Dictionaries"))
        
        self.slob_client = slob_client
        self.dict_manager = slob_client.dict_manager
        
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header_bar = Adw.HeaderBar()
        header_bar.set_css_classes(["flat"])
        main_box.append(header_bar)
        
        # Add button (left)
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.set_tooltip_text(_("Add dictionary"))
        add_button.connect("clicked", self._on_add_clicked)
        header_bar.pack_start(add_button)
        
        # Title (center)
        title_label = Gtk.Label(label=_("Dictionaries"))
        title_label.set_css_classes(["title-2"])
        header_bar.set_title_widget(title_label)
        
        # Scrollable list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)
        
        # List box
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.set_child(self.list_box)
        
        # Empty state
        self.empty_label = Gtk.Label()
        self.empty_label.set_markup(_("<b>No dictionaries</b>\n\nClick \"+\" to import one."))
        self.empty_label.set_justify(Gtk.Justification.CENTER)
        self.empty_label.set_margin_top(40)
        self.empty_label.set_selectable(False)
        
        # Load dictionaries
        self._refresh_list()

    def _refresh_list(self):
        """Refresh the dictionary list."""
        # Clear existing items
        while True:
            child = self.list_box.get_first_child()
            if child is None:
                break
            self.list_box.remove(child)
        
        dictionaries = self.dict_manager.get_dictionaries()
        
        if not dictionaries:
            empty_row = Gtk.ListBoxRow()
            empty_row.set_selectable(False)
            empty_row.set_activatable(False)
            empty_row.set_child(self.empty_label)
            self.list_box.append(empty_row)
        else:
            for dict_info in dictionaries:
                row = self._create_dict_row(dict_info)
                self.list_box.append(row)

    def _create_dict_row(self, dict_info):
        """Create a row for a dictionary."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(12)
        row.set_margin_bottom(12)
        row.set_margin_start(12)
        row.set_margin_end(12)
        
        # Left side: name and info
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        # Name
        name_label = Gtk.Label(label=dict_info['label'])
        name_label.set_css_classes(["heading"])
        name_label.set_halign(Gtk.Align.START)
        left_box.append(name_label)
        
        # Item count
        from gettext import ngettext

        item_count = dict_info.get('blob_count', -1)
        count_text = ngettext("%d item", "%d items", item_count) % item_count if item_count >= 0 else _("Items unknown")
        count_label = Gtk.Label(label=count_text)
        count_label.set_css_classes(["dim-label", "caption"])
        count_label.set_halign(Gtk.Align.START)
        left_box.append(count_label)
        
        row.append(left_box)
        row.set_hexpand(True)

        # Spacer to push controls to the end
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row.append(spacer)
        
        # Right side: controls
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # Enable/disable switch
        enabled = dict_info.get('enabled', True)
        switch = Gtk.Switch()
        switch.set_active(enabled)
        switch.set_halign(Gtk.Align.CENTER)
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect("notify::active", self._on_switch_toggled, dict_info['filename'])
        controls_box.append(switch)
        
        # Info button
        info_button = Gtk.Button()
        info_button.set_icon_name("dialog-information-symbolic")
        info_button.set_has_frame(False)
        info_button.connect("clicked", self._on_info_clicked, dict_info)
        controls_box.append(info_button)
        
        # Delete button
        delete_button = Gtk.Button()
        delete_button.set_icon_name("edit-delete-symbolic")
        delete_button.set_has_frame(False)
        delete_button.set_css_classes(["destructive-action"])
        delete_button.connect("clicked", self._on_delete_clicked, dict_info['filename'])
        controls_box.append(delete_button)
        
        row.append(controls_box)
        
        return row

    def _on_add_clicked(self, button):
        """Handle add dictionary button click."""
        dialog = Gtk.FileChooserNative(
            title=_("Select Dictionary"),
            transient_for=self.get_root(),
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.set_accept_label(_("Open"))
        dialog.set_cancel_label(_("Cancel"))
        
        # Add filter for .slob files
        slob_filter = Gtk.FileFilter()
        slob_filter.set_name(_("Slob Dictionaries (*.slob)"))
        slob_filter.add_pattern("*.slob")
        dialog.add_filter(slob_filter)
        
        all_filter = Gtk.FileFilter()
        all_filter.set_name(_("All Files"))
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)
        
        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    path = file.get_path()
                    # Check if file has .slob extension
                    from pathlib import Path
                    file_path = Path(path)
                    
                    if file_path.suffix.lower() == '.slob':
                        # Direct import for SLOB files
                        self._import_dictionary_with_format(path, source_format=None)
                    else:
                        # Show format selection for non-SLOB files
                        self._show_format_selection_dialog(path)
        
        dialog.connect("response", on_response)
        dialog.show()

    def _show_format_selection_dialog(self, source_path):
        """Show dialog to select the dictionary format."""
        supported_formats = self.dict_manager.get_supported_formats()
        
        if not supported_formats:
            self._show_error(_("Unsupported file format."))
            return
        
        # Create dialog
        dialog = Adw.Window()
        dialog.set_transient_for(self.get_root())
        dialog.set_modal(True)
        dialog.set_default_size(400, 300)
        dialog.set_title(_("Select Dictionary Format"))
        
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)
        dialog.set_content(main_box)
        
        # Info label
        info_label = Gtk.Label()
        info_label.set_markup(_("<b>Select the dictionary format</b>\n\n<i>If unsure, choose 'Auto-detect'</i>"))
        info_label.set_justify(Gtk.Justification.CENTER)
        main_box.append(info_label)
        
        # Scrollable format list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled)
        
        # List box for formats
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled.set_child(list_box)
        
        # Add "Auto-detect" option first
        auto_row = Gtk.ListBoxRow()
        auto_label = Gtk.Label(label=_("Auto-detect"))
        auto_label.set_margin_top(8)
        auto_label.set_margin_bottom(8)
        auto_label.set_margin_start(8)
        auto_label.set_margin_end(8)
        auto_row.set_child(auto_label)
        list_box.append(auto_row)
        list_box.select_row(auto_row)  # Select auto-detect by default
        
        # Add format options
        format_rows = {}
        for fmt_key, fmt_name in sorted(supported_formats.items()):
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=fmt_name)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_halign(Gtk.Align.START)
            row.set_child(label)
            list_box.append(row)
            format_rows[row] = fmt_key
        
        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        main_box.append(button_box)
        
        # Cancel button
        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", lambda btn: dialog.close())
        button_box.append(cancel_button)
        
        # Import button
        import_button = Gtk.Button(label=_("Import"))
        import_button.set_css_classes(["suggested-action"])
        button_box.append(import_button)
        
        def on_import_clicked(button):
            selected_row = list_box.get_selected_row()
            if selected_row is None:
                return
            
            # Determine selected format
            selected_format = None
            if selected_row != auto_row:
                selected_format = format_rows.get(selected_row)
            
            dialog.close()
            self._import_dictionary_with_format(source_path, selected_format)
        
        import_button.connect("clicked", on_import_clicked)
        dialog.present()

    def _import_dictionary_with_format(self, source_path: str, source_format: str = None):
        """Import dictionary with specified format."""
        try:
            result = self.dict_manager.import_dictionary(
                source_path=source_path,
                source_format=source_format
            )
            
            if result:
                self._refresh_list()
                self._show_notification(_("Dictionary imported successfully"))
            else:
                self._show_error(_("Failed to import dictionary"))
        
        except FileNotFoundError:
            self._show_error(_("Dictionary file not found"))
        except PermissionError:
            self._show_error(_("Permission denied accessing dictionary"))
        except ValueError as e:
            self._show_error(_("Invalid dictionary: %s") % str(e))
        except RuntimeError as e:
            self._show_error(_("Conversion failed: %s") % str(e))
        except Exception as e:
            self._show_error(_("Error importing dictionary: %s") % str(e))

    def _on_switch_toggled(self, switch, pspec, filename):
        """Handle enable/disable switch toggle."""
        enabled = switch.get_active()
        self.slob_client.set_dictionary_enabled(filename, enabled)

    def _on_info_clicked(self, button, dict_info):
        """Handle info button click."""
        from ..utils import slob_tags
        dialog = Adw.MessageDialog(transient_for=self.get_root())
        dialog.set_heading(dict_info[slob_tags.TAG_LABEL])
        
        # Build info text
        info_parts = []
        
        if dict_info.get('blob_count'):
            info_parts.append(_("Items: %s") % dict_info['blob_count'])
        
        if slob_tags.TAG_COPYRIGHT in dict_info:
            info_parts.append(_("Copyright: %s") % dict_info[slob_tags.TAG_COPYRIGHT])
        
        if slob_tags.TAG_LICENSE_NAME in dict_info:
            info_parts.append(_("License: %s") % dict_info[slob_tags.TAG_LICENSE_NAME])
        
        if slob_tags.TAG_SOURCE in dict_info:
            info_parts.append(_("Source: %s") % dict_info[slob_tags.TAG_SOURCE])
        
        if not info_parts:
            info_text = _("No metadata available")
        else:
            info_text = "\n".join(info_parts)
        
        dialog.set_body(info_text)
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.present()

    def _on_delete_clicked(self, button, filename):
        """Handle delete button click."""
        dialog = Adw.MessageDialog(transient_for=self.get_root())
        dialog.set_heading(_("Delete Dictionary?"))
        dialog.set_body(_("Are you sure you want to delete '%s'?") % filename)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dialog, response):
            if response == "delete":
                if self.slob_client.delete_dictionary(filename):
                    self._refresh_list()
                    self._show_notification(_("Dictionary deleted"))
                else:
                    self._show_error(_("Failed to delete dictionary"))
        
        dialog.connect("response", on_response)
        dialog.present()

    def _show_notification(self, message):
        """Show a toast notification."""
        parent = self.get_root()
        if isinstance(parent, Adw.ApplicationWindow):
            toast = Adw.Toast(title=message)
            parent.add_toast(toast)

    def _show_error(self, message):
        """Show an error dialog."""
        dialog = Adw.MessageDialog(transient_for=self.get_root())
        dialog.set_heading(_("Error"))
        dialog.set_body(message)
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.present()
