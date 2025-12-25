# SPDX-License-Identifier: AGPL-3.0-or-later

import json
from pathlib import Path
from typing import Any, Optional, Callable


class SettingsManager:
    """Manages application settings and preferences."""

    def __init__(self) -> None:
        """Initialize settings manager."""
        from ..utils.utils import get_config_dir
        self.config_dir = get_config_dir()
        self.settings_file = self.config_dir / "settings.json"
        
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default settings
        self.defaults = {
            'appearance': 'system',  # 'system', 'light', 'dark'
            'force_dark_mode': True,
            'load_remote_content': False,
            'enable_history': True,
            'enable_javascript': True,
            'port': 8013,
            'zoom_level': 1.0,
        }
        
        # Callbacks for settings changes
        self.callbacks: dict[str, list[Callable]] = {}
        
        # Load settings
        self.settings = self._load_settings()

    def _load_settings(self) -> dict[str, Any]:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults to handle new settings
                    settings = self.defaults.copy()
                    settings.update(loaded)
                    return settings
            except (json.JSONDecodeError, IOError):
                return self.defaults.copy()
        return self.defaults.copy()

    def _save_settings(self) -> None:
        """Save settings to file."""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except IOError as e:
            print(f"Error saving settings: {e}")

    def _get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key
            default: Default value if key not found
            
        Returns:
            Setting value or default
        """
        return self.settings.get(key, default if default is not None else self.defaults.get(key))

    def _set(self, key: str, value: Any) -> None:
        """
        Set a setting value.
        
        Args:
            key: Setting key
            value: Setting value
        """
        if self.settings.get(key) != value:
            self.settings[key] = value
            self._save_settings()
            self._notify_callbacks(key, value)

    @property
    def appearance(self) -> str:
        """Current appearance: system, light, dark"""
        return str(self._get("appearance"))

    @appearance.setter
    def appearance(self, value: str) -> None:
        """Current appearance: system, light, dark"""
        if value not in ("system", "light", "dark"):
            raise ValueError("appearance must be one of (system, light, dark)")
        self._set("appearance", value)

    @property
    def force_dark(self) -> bool:
        """Use force dark in the browser"""
        return bool(self._get("force_dark_mode"))

    @force_dark.setter
    def force_dark(self, value: bool) -> None:
        """Use force dark in the browser"""
        self._set("force_dark_mode", value)

    @property
    def load_remote_content(self) -> bool:
        """Load remote content in the webview (global setting)"""
        return bool(self._get("load_remote_content"))

    @load_remote_content.setter
    def load_remote_content(self, value: bool) -> None:
        """Load remote content in the webview (global setting)"""
        self._set("load_remote_content", value)

    @property
    def enable_history(self) -> bool:
        """Whether to keep histories"""
        return bool(self._get("enable_history"))

    @enable_history.setter
    def enable_history(self, value: bool) -> None:
        """Whether to keep histories"""
        self._set("enable_history", value)

    @property
    def enable_javascript(self) -> bool:
        """Enable JS in webview"""
        return bool(self._get("enable_javascript"))

    @enable_javascript.setter
    def enable_javascript(self, value: bool) -> None:
        """Enable JS in webview"""
        self._set("enable_javascript", value)

    @property
    def port(self) -> int:
        """Configured port"""
        return int(self._get("port"))

    @port.setter
    def port(self, value: int) -> None:
        """Configured port"""
        if value < 1024 or value > 65535:
            raise ValueError(f"Invalid port {value}")
        self._set("port", value)

    @property
    def zoom_level(self) -> float:
        """Current zoom level"""
        return float(self._get("zoom_level"))

    @zoom_level.setter
    def zoom_level(self, value: float) -> None:
        """Current zoom level"""
        self._set("zoom_level", value)

    def register_callback(self, key: str, callback: Callable) -> None:
        """
        Register a callback for setting changes.
        
        Args:
            key: Setting key to watch
            callback: Callback function(key, value)
        """
        if key not in self.callbacks:
            self.callbacks[key] = []
        self.callbacks[key].append(callback)

    def unregister_callback(self, key: str, callback: Callable) -> None:
        """
        Unregister a callback.
        
        Args:
            key: Setting key
            callback: Callback function to remove
        """
        if key in self.callbacks:
            self.callbacks[key] = [cb for cb in self.callbacks[key] if cb != callback]

    def _notify_callbacks(self, key: str, value: Any) -> None:
        """Notify all registered callbacks for a setting."""
        if key in self.callbacks:
            for callback in self.callbacks[key]:
                try:
                    callback(key, value)
                except Exception as e:
                    print(f"Error in settings callback: {e}")

    def reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        self.settings = self.defaults.copy()
        self._save_settings()
        
        # Notify all callbacks
        for key, value in self.settings.items():
            self._notify_callbacks(key, value)
