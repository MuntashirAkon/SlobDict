# SPDX-License-Identifier: AGPL-3.0-or-later

import gi
gi.require_version("Gio", "2.0")
import logging

from gi.repository import Gio, GLib
from typing import List, Dict
from .backend.slob_client import SlobClient
from .utils.i18n import _


logger = logging.getLogger(__name__)
# D-Bus SearchProvider2 interface XML: /usr/share/dbus-1/interfaces/org.gnome.ShellSearchProvider2.xml
SEARCH_PROVIDER_XML = """
<node>
  <interface name="org.gnome.Shell.SearchProvider2">
    <method name="GetInitialResultSet">
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg type="as" name="previous_results" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg type="as" name="results" direction="in"/>
      <arg type="aa{sv}" name="metas" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg type="s" name="result" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
  </interface>
</node>
"""


class SlobDictSearchProvider:
    """D-Bus Search Provider for GNOME Shell SearchProvider2 interface."""

    def __init__(self, app: Gio.Application) -> None:
        """
        Initialize the search provider.
        
        Args:
            app: The SlobDictApplication instance
        """
        self.app = app
        self.node_info = Gio.DBusNodeInfo.new_for_xml(SEARCH_PROVIDER_XML)
        self.interface_info = self.node_info.interfaces[0]
        self.slob_client: SlobClient = app.slob_client

    def handle_method_call(self, connection, sender, object_path, interface_name,
                          method_name, parameters, invocation):
        """
        Handle D-Bus method calls from GNOME Shell.
        """
        try:
            if method_name == 'GetInitialResultSet':
                terms = parameters.unpack()[0]
                results = self._get_initial_result_set(terms)
                invocation.return_value(GLib.Variant('(as)', (results,)))
                logger.debug(f"SearchProvider: GetInitialResultSet returned {len(results)} results for {terms}")
            elif method_name == 'GetSubsearchResultSet':
                previous_results, terms = parameters.unpack()
                results = self._get_subsearch_result_set(previous_results, terms)
                invocation.return_value(GLib.Variant('(as)', (results,)))
                logger.debug(f"SearchProvider: GetSubsearchResultSet returned {len(results)} results")
            elif method_name == 'GetResultMetas':
                results = parameters.unpack()[0]
                metas = self._get_result_metas(results)
                invocation.return_value(GLib.Variant('(aa{sv})', (metas,)))
                logger.debug(f"SearchProvider: GetResultMetas returned {len(metas)} metas")
            elif method_name == 'ActivateResult':
                result, terms, timestamp = parameters.unpack()
                self._activate_result(result, terms, timestamp)
                invocation.return_value(None)
                logger.debug(f"SearchProvider: ActivateResult for {result}")
            elif method_name == 'LaunchSearch':
                terms, timestamp = parameters.unpack()
                self._launch_search(terms, timestamp)
                invocation.return_value(None)
                logger.debug(f"SearchProvider: LaunchSearch for {terms}")
        except Exception as e:
            logger.exception(f"SearchProvider error in {method_name}.")
            invocation.return_error_literal(
                Gio.DBusError.quark(),
                Gio.DBusError.FAILED,
                str(e)
            )

    def _get_initial_result_set(self, terms: List[str]) -> List[str]:
        """
        Search dictionary for terms.
        
        Returns list of result identifiers (e.g., ['word:hello', 'word:help']).
        """
        if not terms or len(terms) == 0:
            logger.debug("SearchProvider: No terms provided")
            return []

        search_term = ' '.join(terms).strip()
        if len(search_term) < 2:
            logger.debug(f"SearchProvider: Search term too short: '{search_term}'")
            return []

        return self._get_search_results(search_term)

    def _get_subsearch_result_set(self, previous_results: List[str], terms: List[str]) -> List[str]:
        """
        Filter previous results based on additional search terms.
        """
        if not terms or len(terms) == 0:
            return previous_results

        search_term = ' '.join(terms).strip()
        if len(search_term) < 2:
            logger.debug(f"SearchProvider: Search term too short: '{search_term}'")
            return []

        if len(search_term) > 2 and len(previous_results) == 0:
            # No further search possible
            return []

        return self._get_search_results(search_term)

    def _get_result_metas(self, results: List[str]) -> List[Dict[str, GLib.Variant]]:
        """
        Return metadata for each result.
        
        Returns list of dicts with 'id', 'name', 'description', 'gicon' keys.
        """
        metas = []

        for result_id in results:
            try:
                source, key_id, key = result_id.split(':', 2)
                definition = self._get_definition(key, int(key_id), source)
                meta = {
                    'id': GLib.Variant('s', result_id),
                    'name': GLib.Variant('s', key.capitalize()),
                    'description': GLib.Variant('s', definition),
                    'gicon': GLib.Variant('s', 'accessories-dictionary'),
                }
                metas.append(meta)
            except Exception as e:
                logger.warning(f"SearchProvider error getting meta for {result_id}: {e}")
                # Continue with next result instead of failing

        return metas

    def _activate_result(self, result: str, terms: List[str], timestamp: int) -> None:
        """
        Activate a result (user clicked on it).
        
        This runs in background, so async is OK here.
        """
        self.app.hold()
        try:
            from .ui.main_window import MainWindow

            source, key_id, key = result.split(':', 2)
            search_text = ' '.join(terms)

            window: MainWindow = self.app.get_active_window()
            if not window:
                # No window exists, we need to create one
                # This will be done in on_activate
                logger.debug("SearchProvider: No window, creating one...")
                self.app.activate()
                window = self.app.get_active_window()

            if window:
                window.present()
                entry = MainWindow.LookupEntry(
                    term=key,
                    dict_id=source,
                    term_id=int(key_id)
                )
                window.perform_lookup(search_text, selected_entry=entry)
                logger.debug(f"SearchProvider: Called perform_lookup with key '{key}'")
            else:
                logger.debug("SearchProvider: Failed to create/get window")
        except Exception as e:
            logger.exception(f"SearchProvider error activating result.")
        finally:
            self.app.release()

    def _launch_search(self, terms: List[str], timestamp: int) -> None:
        """
        Launch search with given terms.
        """
        self.app.hold()
        try:
            from .ui.main_window import MainWindow

            window: MainWindow = self.app.get_active_window()
            if not window:
                self.app.activate()
                window = self.app.get_active_window()

            if window:
                window.present()
                search_text = ' '.join(terms)
                window.perform_lookup(search_text)
            else:
                logger.debug("SearchProvider: Failed to create/get window for search")

        except Exception as e:
            logger.exception(f"SearchProvider error launching search.")
        finally:
            self.app.release()
    
    def _get_search_results(self, search_term: str) -> List[str]:
        """
        Retrieve search results from dictionaries.

        Format: id:blob_id:key
        """
        results = []
        try:
            matches = self.slob_client.search(search_term, limit=5)
            for match in matches[:10]:
                results.append(f"{match.dict_id}:{match.term_id}:{match.term}")
        except Exception as e:
            logger.exception(f"SearchProvider error during lookup.")
        
        logger.debug(f"SearchProvider: Returning {len(results)} results")
        return results[:10]

    def _get_definition(self, key: str, key_id: int, source: str) -> str:
        """
        Get the definition for a word from the dictionary.
        
        Returns a short preview string for display in search results.
        If lookup fails, returns a generic placeholder.
        
        Args:
            word: The word to look up
            
        Returns:
            A definition string (short, for display in search)
        """
        try:
            entry = self.slob_client.get_entry(key, key_id, source)
            if entry:
                content_type = entry.content_type
                content = entry.content

                if content_type.startswith("text/"):
                    content_text = content.decode('utf-8') if isinstance(content, bytes) else str(content)
                    if content_type.startswith("text/html"):
                        from .utils.utils import html_to_text
                        return self._remove_entry_name(html_to_text(content_text), key)
                    return content_text
        except Exception as e:
            logger.exception(f"SearchProvider error getting definition.")

        # Fallback if lookup fails
        return _("View definition of %s") % key
    
    def _remove_entry_name(self, text: str, word: str) -> str:
        """
        Robust entry name removal - handles variations.
        """
        if not text or not word:
            return text
        
        patterns = [
            word,                    # Exact match
            f"{word}.",             # "word."
            f"{word},",             # "word,"
            f"{word}:",             # "word:"
            f"{word} -",            # "word -"
            f"{word} —",            # "word —"
        ]
        
        for pattern in patterns:
            if text.startswith(pattern):
                # Remove pattern + following whitespace
                end_pos = len(pattern)
                while (end_pos < len(text) and 
                    text[end_pos] in ' \t\n.,:;?!'):
                    end_pos += 1
                return text[end_pos:].strip()
        
        return text.strip()
