import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gtk from 'gi://Gtk';

import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const SHORTCUT_KEY = 'lookup-shortcut';

export default class SlobDictPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage();
        const group = new Adw.PreferencesGroup({
            title: 'Keyboard shortcut',
            description: 'Set the shortcut that looks up the primary selection in Slob Dictionary.',
        });
        const row = new Adw.ActionRow({
            title: 'Lookup selected text',
        });
        const shortcutLabel = new Gtk.ShortcutLabel({
            disabled_text: 'Disabled',
            valign: Gtk.Align.CENTER,
        });
        const setButton = new Gtk.Button({
            label: 'Set…',
            valign: Gtk.Align.CENTER,
        });
        const clearButton = new Gtk.Button({
            label: 'Clear',
            valign: Gtk.Align.CENTER,
        });

        row.add_suffix(shortcutLabel);
        row.add_suffix(setButton);
        row.add_suffix(clearButton);
        row.activatable_widget = setButton;
        group.add(row);
        page.add(group);
        window.add(page);

        let keyController = null;

        const updateShortcut = () => {
            const [accelerator = ''] = settings.get_strv(SHORTCUT_KEY);
            shortcutLabel.accelerator = accelerator;
        };

        const stopCapture = () => {
            if (keyController) {
                window.remove_controller(keyController);
                keyController = null;
            }
            setButton.label = 'Set…';
        };

        const settingsChangedId = settings.connect(
            `changed::${SHORTCUT_KEY}`,
            updateShortcut
        );
        updateShortcut();

        setButton.connect('clicked', () => {
            if (keyController)
                return;

            setButton.label = 'Press a key combination…';
            keyController = new Gtk.EventControllerKey();
            keyController.connect('key-pressed', (_controller, keyval, _keycode, state) => {
                if (keyval === Gdk.KEY_Escape) {
                    stopCapture();
                    return true;
                }

                if (keyval === Gdk.KEY_BackSpace || keyval === Gdk.KEY_Delete) {
                    settings.set_strv(SHORTCUT_KEY, []);
                    stopCapture();
                    return true;
                }

                const modifiers = state & Gtk.accelerator_get_default_mod_mask();
                if (!Gtk.accelerator_valid(keyval, modifiers))
                    return true;

                settings.set_strv(SHORTCUT_KEY, [
                    Gtk.accelerator_name(keyval, modifiers),
                ]);
                stopCapture();
                return true;
            });

            window.add_controller(keyController);
        });

        clearButton.connect('clicked', () => {
            stopCapture();
            settings.set_strv(SHORTCUT_KEY, []);
        });

        window.connect('close-request', () => {
            stopCapture();
            settings.disconnect(settingsChangedId);
            return false;
        });
    }
}
