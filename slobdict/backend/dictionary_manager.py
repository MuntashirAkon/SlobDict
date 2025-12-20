# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
import json

try:
    import slob
except ImportError:
    slob = None


class DictionaryManager:
    """Manages dictionary files and metadata."""

    def __init__(self):
        """Initialize dictionary manager."""
        from ..utils.utils import get_config_dir
        self.config_dir = get_config_dir()
        self.dicts_dir = self.config_dir / "dictionaries"
        self.metadata_file = self.config_dir / "dictionaries.json"
        
        # Create directories if they don't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dicts_dir.mkdir(parents=True, exist_ok=True)
        
        # Load metadata
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Load dictionary metadata from file."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_metadata(self) -> None:
        """Save dictionary metadata to file."""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def import_dictionary(self, source_path: str) -> Optional[str]:
        """
        Import a dictionary file.
        
        Args:
            source_path: Path to the .slob file to import
            
        Returns:
            Dictionary filename if successful, None otherwise
        """
        try:
            source = Path(source_path)
            if not source.exists() or source.suffix != '.slob':
                return None
            
            # Copy to dictionaries directory
            dest = self.dicts_dir / source.name
            shutil.copy2(source, dest)
            
            # Extract metadata
            metadata = self._extract_metadata(str(dest))
            if metadata:
                self.metadata[source.name] = metadata
                self.metadata[source.name]['enabled'] = True
                self._save_metadata()
                return source.name
            
            return None
        except Exception as e:
            print(f"Error importing dictionary: {e}")
            return None

    def _extract_metadata(self, dict_path: str) -> Optional[Dict[str, Any]]:
        """
        Extract metadata from a slob file.
        
        Args:
            dict_path: Path to the .slob file
            
        Returns:
            Dictionary containing metadata
        """
        if not slob:
            return self._extract_metadata_fallback(dict_path)
        
        try:
            with slob.open(dict_path) as dictionary:
                metadata = {
                    'item_count': len(dictionary),
                    'copyright': dictionary.copyright or '',
                    'license': dictionary.license or '',
                    'description': dictionary.description or '',
                    'source': dictionary.source or '',
                    'version': str(dictionary.version) if dictionary.version else '',
                    'tags': dictionary.tags or {},
                }
                return metadata
        except Exception as e:
            print(f"Error extracting metadata: {e}")
            return self._extract_metadata_fallback(dict_path)

    def _extract_metadata_fallback(self, dict_path: str) -> Dict[str, Any]:
        """
        Fallback metadata extraction when slob library is unavailable.
        
        Args:
            dict_path: Path to the .slob file
            
        Returns:
            Dictionary containing basic metadata
        """
        try:
            file_size = os.path.getsize(dict_path)
            return {
                'item_count': 0,
                'copyright': '',
                'license': '',
                'description': '',
                'source': '',
                'version': '',
                'tags': {},
                'file_size': file_size,
            }
        except Exception:
            return {}

    def delete_dictionary(self, filename: str) -> bool:
        """
        Delete a dictionary.
        
        Args:
            filename: Name of the dictionary file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            dict_path = self.dicts_dir / filename
            if dict_path.exists():
                dict_path.unlink()
            
            if filename in self.metadata:
                del self.metadata[filename]
                self._save_metadata()
            
            return True
        except Exception as e:
            print(f"Error deleting dictionary: {e}")
            return False

    def set_dictionary_enabled(self, filename: str, enabled: bool) -> bool:
        """
        Enable or disable a dictionary.
        
        Args:
            filename: Name of the dictionary file
            enabled: True to enable, False to disable
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if filename in self.metadata:
                self.metadata[filename]['enabled'] = enabled
                self._save_metadata()
                return True
            return False
        except Exception as e:
            print(f"Error updating dictionary status: {e}")
            return False

    def get_dictionaries(self) -> List[Dict[str, Any]]:
        """
        Get list of all dictionaries with their metadata.
        
        Returns:
            List of dictionaries with metadata
        """
        dictionaries = []
        for filename, meta in self.metadata.items():
            dict_path = self.dicts_dir / filename
            if dict_path.exists():
                meta['filename'] = filename
                meta['path'] = str(dict_path)
                dictionaries.append(meta)
        
        return dictionaries

    def get_dictionary_info(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific dictionary.
        
        Args:
            filename: Name of the dictionary file
            
        Returns:
            Dictionary metadata or None
        """
        return self.metadata.get(filename)
