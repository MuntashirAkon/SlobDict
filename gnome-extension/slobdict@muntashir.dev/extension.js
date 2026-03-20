import Gio from 'gi://Gio';
import St from 'gi://St';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import Clutter from 'gi://Clutter';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class SlobDictExtension extends Extension {
    enable() {
        // Setup the Keyboard Shortcut
        this._settings = this.getSettings('org.gnome.shell.extensions.slobdict');
        Main.wm.addKeybinding(
            'lookup-shortcut',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            this._triggerLookup.bind(this)
        );

        // Setup the Trackpad Gesture
        this._capturedEventId = global.stage.connect(
            'captured-event',
            this._onCapturedEvent.bind(this)
        );
    }

    disable() {
        // Clean up Keyboard Shortcut
        Main.wm.removeKeybinding('lookup-shortcut');
        this._settings = null;

        // Clean up Trackpad Gesture
        if (this._capturedEventId) {
            global.stage.disconnect(this._capturedEventId);
            this._capturedEventId = null;
        }
    }

    _onCapturedEvent(actor, event) {
        const type = event.type();

        // Listen to SWIPE (for quick taps) and HOLD (for long taps)
        if (type !== Clutter.EventType.TOUCHPAD_HOLD &&
            type !== Clutter.EventType.TOUCHPAD_SWIPE) {
            return Clutter.EVENT_PROPAGATE;
        }

        const fingers = event.get_touchpad_gesture_finger_count();
        if (fingers !== 4) {
            return Clutter.EVENT_PROPAGATE;
        }

        const phase = event.get_gesture_phase();

        // Micro-Swipes
        if (type === Clutter.EventType.TOUCHPAD_SWIPE) {
            if (phase === Clutter.TouchpadGesturePhase.BEGIN) {
                // Record the start time and reset distance trackers
                this._tapStartTime = event.get_time();
                this._totalDx = 0;
                this._totalDy = 0;

                // Let this propagate to avoid breaking GNOME's
                // native 4-finger workspace switching.
                return Clutter.EVENT_PROPAGATE;

            } else if (phase === Clutter.TouchpadGesturePhase.UPDATE) {
                // Accumulate the tiny movements your fingers make
                const [dx, dy] = event.get_gesture_motion_delta();
                this._totalDx += Math.abs(dx);
                this._totalDy += Math.abs(dy);
                return Clutter.EVENT_PROPAGATE;

            } else if (phase === Clutter.TouchpadGesturePhase.END) {
                if (this._tapStartTime) {
                    const duration = event.get_time() - this._tapStartTime;

                    // IF: The gesture was fast (< 250ms) 
                    // AND: The fingers barely moved (< 20 units total)
                    // THEN: It was a quick tap.
                    if (duration > 0 && duration < 250 &&
                        this._totalDx < 20 && this._totalDy < 20) {

                        this._triggerLookup();
                        this._tapStartTime = null;
                        return Clutter.EVENT_STOP; // Stop GNOME from processing the tap
                    }
                }
                this._tapStartTime = null;
                return Clutter.EVENT_PROPAGATE;

            } else if (phase === Clutter.TouchpadGesturePhase.CANCEL) {
                this._tapStartTime = null;
            }
        }

        // Touch and hold fallback
        if (type === Clutter.EventType.TOUCHPAD_HOLD) {
            if (phase === Clutter.TouchpadGesturePhase.BEGIN) {
                return Clutter.EVENT_PROPAGATE;

            } else if (phase === Clutter.TouchpadGesturePhase.END) {
                // Detected a long press without moving
                this._triggerLookup();
                return Clutter.EVENT_STOP;
            }
        }

        return Clutter.EVENT_PROPAGATE;
    }

    _triggerLookup() {
        const clipboard = St.Clipboard.get_default();

        clipboard.get_text(St.ClipboardType.PRIMARY, (clip, text) => {
            if (text && text.trim() !== '') {
                const cleanWord = encodeURIComponent(text.trim());
                const uri = `slobdict://lookup/${cleanWord}/${cleanWord}`;

                try {
                    Gio.AppInfo.launch_default_for_uri(uri, null);
                } catch (error) {
                    console.error(`SlobDict Extension Error: Failed to launch URI. ${error.message}`);
                }
            }
        });
    }
}