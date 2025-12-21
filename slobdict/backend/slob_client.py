# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path
from typing import List, Dict, Optional, Callable
from .dictionary_manager import DictionaryManager

class SlobClient:
    """Client for querying slob dictionaries."""

    def __init__(self, on_dictionaries_changed: Optional[Callable] = None):
        """Initialize slob client with dictionary manager."""
        self.dict_manager = DictionaryManager()
        self.data_dir = Path(__file__).parent.parent.parent / "data"
        self.dictionaries: Dict[str, any] = {}
        self.current_request_id = None  # Track current request for cancellation
        self.on_dictionaries_changed = on_dictionaries_changed  # Callback for UI updates
        self.load_dictionaries()

    def load_dictionaries(self):
        """Load dictionaries from config directory."""
        from .slob_wrapper import SlobWrapper
        
        # Clear existing dictionaries
        self.close()
        self.dictionaries = {}

        # Load enabled dictionaries from manager
        for dict_info in self.dict_manager.get_dictionaries():
            if not dict_info.get('enabled', True):
                continue
            
            display_name = dict_info['label']
            dict_path = Path(dict_info['path'])
            
            if dict_path.exists():
                try:
                    self.dictionaries[dict_info['id']] = {
                        'label': display_name,
                        'slob': SlobWrapper(dict_path),
                    }
                    print(f"✓ Loaded: {display_name}")
                except Exception as e:
                    import traceback
                    print(f"✗ Failed to load {display_name}: {e}")
                    traceback.print_exc()
            else:
                print(f"⚠ Not found: {dict_path}")

        if not self.dictionaries:
            print("⚠ No dictionaries loaded. Add dictionaries in the Dictionaries manager")
        
        # Notify UI of changes
        if self.on_dictionaries_changed:
            self.on_dictionaries_changed()

    def import_dictionary(self, source_path: str) -> Optional[str]:
        """
        Import a new dictionary and reload.
        
        Args:
            source_path: Path to the .slob file to import
            
        Returns:
            Dictionary filename if successful, None otherwise
        """
        result = self.dict_manager.import_dictionary(source_path)
        if result:
            self.load_dictionaries()  # Reload all dictionaries
        return result

    def delete_dictionary(self, filename: str) -> bool:
        """
        Delete a dictionary and reload.
        
        Args:
            filename: Name of the dictionary file
            
        Returns:
            True if successful, False otherwise
        """
        result = self.dict_manager.delete_dictionary(filename)
        if result:
            self.load_dictionaries()  # Reload all dictionaries
        return result

    def set_dictionary_enabled(self, filename: str, enabled: bool) -> bool:
        """
        Enable or disable a dictionary and reload.
        
        Args:
            filename: Name of the dictionary file
            enabled: True to enable, False to disable
            
        Returns:
            True if successful, False otherwise
        """
        result = self.dict_manager.set_dictionary_enabled(filename, enabled)
        if result:
            self.load_dictionaries()  # Reload all dictionaries
        return result

    def search(self, query: str, limit: int = 50, request_id: int = None) -> List[Dict[str, str]]:
        """
        Search all dictionaries for matching terms.
        
        Args:
            query: Search query string
            limit: Maximum results to return
            request_id: Request ID for cancellation tracking
        
        Returns:
            List of dicts with 'title' and 'source' keys
        """
        results = []
        
        for dict_id, dictionary in self.dictionaries.items():
            # Check if this request has been cancelled
            if request_id and request_id != self.current_request_id:
                print(f"Search cancelled (request {request_id})")
                return []
            
            try:
                matches = self._find_in_slob(dictionary['slob'], query, limit, request_id)
                for match in matches:
                    results.append({
                        "title": match,
                        "source": dict_id,
                        "dictionary": dictionary['label']
                    })
            except Exception as e:
                print(f"Error searching {dict_name}: {e}")

        return results[:limit]

    def _find_in_slob(self, dictionary, query: str, limit: int, request_id: int = None) -> List[str]:
        """Find entries in a slob dictionary with cancellation support."""
        results = []
        try:
            count = 0
            for entry in dictionary:
                # Check cancellation frequently
                if request_id and request_id != self.current_request_id:
                    print(f"Search cancelled during iteration (request {request_id})")
                    return []
                
                if query.lower() in entry.key.lower():
                    results.append(entry.key)
                    count += 1
                    if count >= limit:
                        break
        except Exception as e:
            print(f"Error in _find_in_slob: {e}")
        return results

    def get_entry(self, key: str, source: str, request_id: int = None) -> Optional[Dict[str, str]]:
        """
        Get full entry content from a dictionary.
        
        Args:
            key: Entry key/title
            source: Dictionary source file name
            request_id: Request ID for cancellation tracking
            
        Returns:
            Dict with 'content', 'key', 'source' or None if not found
        """
        # Check if this request has been cancelled
        if request_id and request_id != self.current_request_id:
            return None
        
        if source not in self.dictionaries:
            return None

        try:
            dictionary = self.dictionaries[source]
            content = self._get_from_slob(dictionary['slob'], key, request_id)
            if content:
                return {
                    "key": key,
                    "content": content,
                    "source": source,
                    "dictionary": dictionary['label'],
                }
        except Exception as e:
            print(f"Error getting entry {key} from {source}: {e}")

        return None

    def _get_from_slob(self, dictionary, key: str, request_id: int = None) -> Optional[str]:
        """Get entry content from slob with cancellation support."""
        try:
            for entry in dictionary:
                # Check cancellation
                if request_id and request_id != self.current_request_id:
                    return None
                
                if entry.key.lower() == key.lower():
                    content = entry.content
                    if isinstance(content, bytes):
                        return content.decode('utf-8')
                    return content
        except Exception as e:
            print(f"Error in _get_from_slob: {e}")
        
        return None

    def cancel_request(self, request_id: int):
        """Cancel a search/lookup request."""
        self.current_request_id = request_id
        print(f"Request {request_id} marked for cancellation")

    def set_current_request(self, request_id: int):
        """Mark a request as current."""
        self.current_request_id = request_id

    def close(self):
        """Close all open dictionaries."""
        for dictionary in self.dictionaries.values():
            try:
                dictionary['slob'].close()
            except Exception:
                pass
