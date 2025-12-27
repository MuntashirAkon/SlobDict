# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple
from .dictionary_manager import DictionaryManager
from .slob import Slob
from ..utils.structs import DictEntry, DictEntryContent


logger = logging.getLogger(__name__)


class SlobClient:
    """Client for querying slob dictionaries."""

    class DictInfoInner(object):
        def __init__(self, dict_id: str, dict_name: str, slob: Slob):
            self._dict_id = dict_id
            self._dict_name = dict_name
            self._slob = slob

        @property
        def id(self) -> str:
            return self._dict_id

        @property
        def name(self) -> str:
            return self._dict_name

        @property
        def slob(self) -> Slob:
            return self._slob


    def __init__(self, on_dictionaries_changed: Optional[Callable] = None):
        """Initialize slob client with dictionary manager."""
        self.dict_manager = DictionaryManager()
        self.data_dir = Path(__file__).parent.parent.parent / "data"
        self.dictionaries: Dict[str, SlobClient.DictInfoInner] = {}
        self.current_request_id: int = -1  # Track current request for cancellation
        self.on_dictionaries_changed = on_dictionaries_changed  # Callback for UI updates
        self.load_dictionaries()

    def load_dictionaries(self) -> None:
        """Load dictionaries from config directory."""        
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
                    slob = Slob(str(dict_path))
                    self.dictionaries[dict_info['id']] = self.DictInfoInner(
                        dict_id=slob.id,
                        dict_name=display_name,
                        slob=slob
                    )
                    logger.debug(f"✓ Loaded: {display_name}")
                except Exception as e:
                    logger.exception(f"✗ Failed to load {display_name}")
            else:
                logger.debug(f"⚠ Not found: {dict_path}")

        if not self.dictionaries:
            logger.debug("⚠ No dictionaries loaded.")
        
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

    def search(self, query: str, limit: int = 50, request_id: Optional[int] = None) -> List[DictEntry]:
        """
        Search all dictionaries for matching terms.
        
        Args:
            query: Search query string
            limit: Maximum results to return
            request_id: Request ID for cancellation tracking
        
        Returns:
            List of DictEntry
        """
        results = []
        
        for dict_id, dict_info in self.dictionaries.items():
            # Check if this request has been cancelled
            if request_id and request_id != self.current_request_id:
                logger.debug(f"Search cancelled (request {request_id})")
                return []
            
            try:
                matches = self._find_in_slob(dict_info.slob, query, limit, request_id)
                for match in matches:
                    results.append(DictEntry(
                        dict_id=dict_id,
                        dict_name=dict_info.name,
                        term_id=int(match[0]),
                        term=match[1]
                    ))
            except Exception as e:
                logger.exception(f"Error searching {dict_info.name}")

        results.sort(key=lambda d: d.term.casefold())
        return results[:limit]

    def _find_in_slob(self, slob: Slob, query: str, limit: int, request_id: Optional[int] = None) -> List[Tuple[int, str]]:
        """Find entries in a slob dictionary with cancellation support."""
        results = []
        try:
            from .slob import find
            for i, item in enumerate(find(query, slob, match_prefix=True)):
                # Check cancellation frequently
                if request_id and request_id != self.current_request_id:
                    logger.debug(f"Search cancelled during iteration (request {request_id})")
                    return []

                _, blob = item
                results.append((blob.id, blob.key))
                if i == limit:
                    break
        except Exception as e:
            logger.exception(f"Error in _find_in_slob")
        return results

    def get_entry(self, key: str, key_id: Optional[int], source: str) -> Optional[DictEntryContent]:
        """
        Get full entry content from a dictionary.
        
        Args:
            key: Entry key
            source: Dictionary source file name
            
        Returns:
            DictEntryContent or None if not found
        """
        if source not in self.dictionaries:
            return None

        try:
            dictionary = self.dictionaries[source]
            slob: Slob = dictionary.slob
            if key_id:
                content_type, content = slob.get(key_id)
                _term_id = key_id
            else:
                from .slob import find, Blob
                for i, item in enumerate(find(key, slob, match_prefix=True)):
                    blob: Blob = item[1]
                    content_type = blob.content_type
                    content = blob.content
                    _term_id = blob.id
                    if key == blob.key or len(key) < len(blob.key):
                        break
                    
            if content:
                return DictEntryContent(
                    dict_id=source,
                    dict_name=dictionary.name,
                    term_id=_term_id,
                    term=key,
                    content_type=content_type,
                    content=content
                )
        except Exception as e:
            logger.exception(f"Error getting entry {key_id} from {source}.")

        return None

    def cancel_request(self, request_id: int) -> None:
        """Cancel a search/lookup request."""
        self.current_request_id = request_id
        logger.debug(f"Request {request_id} marked for cancellation")

    def set_current_request(self, request_id: int) -> None:
        """Mark a request as current."""
        self.current_request_id = request_id

    def close(self) -> None:
        """Close all open dictionaries."""
        for dictionary in self.dictionaries.values():
            try:
                dictionary.slob.close()
            except Exception:
                pass
