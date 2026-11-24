import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import Clutter from 'gi://Clutter';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class SlobDictExtension extends Extension {
    enable() {
        // Setup the Keyboard Shortcut
        this._settings = this.getSettings();
        Main.wm.addKeybinding(
            'lookup-shortcut',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            this._triggerLookup.bind(this)
        );

        // Setup the Trackpad Gesture
        global.stage.connectObject(
            'captured-event',
            this._onCapturedEvent.bind(this),
            this
        );
    }

    disable() {
        // Clean up Keyboard Shortcut
        Main.wm.removeKeybinding('lookup-shortcut');
        this._settings = null;

        // Clean up Trackpad Gesture
        global.stage.disconnectObject(this);

        if (this._positionTimeoutId) {
            GLib.Source.remove(this._positionTimeoutId);
            this._positionTimeoutId = null;
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
        // Save the trigger location before the asynchronous clipboard read.
        this._popupAnchor = global.get_pointer().slice(0, 2);

        clipboard.get_text(St.ClipboardType.PRIMARY, (clip, text) => {
            if (text && text.trim() !== '') {
                const cleanWord = encodeURIComponent(text.trim());
                const uri = `slobdict://popup/${cleanWord}`;
                const existingPopups = new Set(
                    global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null)
                        .filter(w => w.get_title() === 'SlobDict Lookup')
                        .map(w => w.get_stable_sequence())
                );

                try {
                    Gio.AppInfo.launch_default_for_uri(uri, null);
                    this._positionLookupWindow(existingPopups);
                } catch (error) {
                    console.error(`SlobDict Extension Error: Failed to launch URI. ${error.message}`);
                }
            }
        });
    }

    _positionLookupWindow(existingPopups) {
        if (this._positionTimeoutId) {
            GLib.Source.remove(this._positionTimeoutId);
        }

        const [pointerX, pointerY] = this._popupAnchor;
        const startedAt = GLib.get_monotonic_time();

        // URI activation may need to create or present the application window.
        // Retry briefly until Mutter reports its mapped window and frame size.
        this._positionTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
            if (GLib.get_monotonic_time() - startedAt > 10_000_000) {
                this._positionTimeoutId = null;
                return GLib.SOURCE_REMOVE;
            }

            const windows = global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null);
            const window = windows.find(w =>
                w.get_title() === 'SlobDict Lookup' &&
                !existingPopups.has(w.get_stable_sequence()) &&
                w.get_compositor_private()
            );

            if (window) {
                const frame = window.get_frame_rect();
                // A newly launched window can be present in Mutter before it
                // has its final frame geometry. Wait until it is measurable.
                if (frame.width <= 1 || frame.height <= 1) {
                    return GLib.SOURCE_CONTINUE;
                }

                const workArea = window.get_work_area_current_monitor();
                const gap = 12;
                const maxX = workArea.x + workArea.width - frame.width;
                const maxY = workArea.y + workArea.height - frame.height;

                // Prefer the pointer as the popup's top-left anchor, with a
                // small gap; clamp to the current monitor's work area.
                const x = Math.max(workArea.x, Math.min(pointerX + gap, maxX));
                const y = Math.max(workArea.y, Math.min(pointerY + gap, maxY));
                window.move_frame(false, Math.floor(x), Math.floor(y));

                this._positionTimeoutId = null;
                return GLib.SOURCE_REMOVE;
            }

            return GLib.SOURCE_CONTINUE;
        });
    }

}
