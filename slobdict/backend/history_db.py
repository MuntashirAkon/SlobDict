# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path
from datetime import datetime
import sqlite3
from typing import List, Dict, Optional
from ..utils.structs import DictEntry

class HistoryDB:
    """Manage dictionary lookup history with SQLite."""

    class HistoryEntry(DictEntry):
        def __init__(self,
            dict_id: str,
            dict_name: str,
            term_id: int,
            term: str,
            created_at: str
        ):
            super().__init__(dict_id, dict_name, term_id, term)
            self._created_at = created_at

        @property
        def created_at(self) -> str:
            return self._created_at

        def created_at_formatted(self) -> str:
            """Format ISO timestamp for display."""
            try:
                # Parse ISO format or SQLite format
                dt = datetime.fromisoformat(self.created_at.replace('Z', '+00:00'))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                try:
                    # Try SQLite format
                    dt = datetime.strptime(self.created_at, "%Y-%m-%d %H:%M:%S")
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    return self.created_at


    def __init__(self) -> None:
        """Initialize history database."""
        from ..utils.utils import get_config_dir
        self.config_dir = get_config_dir()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.config_dir / "history.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    dictionary TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(key_id, source)
                )
            """)
            # Index for faster lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON history(timestamp DESC)")
            conn.commit()
        print(f"✓ History database initialized at {self.db_path}")

    def add_entry(self, entry: DictEntry) -> None:
        """Add entry to history or update timestamp if duplicate."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Try to update existing entry
                cursor = conn.execute(
                    "UPDATE history SET timestamp = CURRENT_TIMESTAMP WHERE key_id = ? AND source = ?",
                    (str(entry.term_id), entry.dict_id)
                )
                
                # If no row was updated, insert new one
                if cursor.rowcount == 0:
                    conn.execute(
                        "INSERT INTO history (key_id, key, source, dictionary) VALUES (?, ?, ?, ?)",
                        (str(entry.term_id), entry.term, entry.dict_id, entry.dict_name)
                    )
                
                conn.commit()
                
                # Cleanup old entries (keep only 500)
                self._cleanup_old_entries()
        except Exception as e:
            print(f"✗ Failed to add history entry: {e}")

    def _cleanup_old_entries(self) -> None:
        """Remove entries older than the 500 most recent."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get the timestamp of the 500th most recent entry
                cursor = conn.execute("""
                    SELECT timestamp FROM history 
                    ORDER BY timestamp DESC 
                    LIMIT 1 OFFSET 499
                """)
                result = cursor.fetchone()
                
                if result:
                    # Delete entries older than that
                    conn.execute(
                        "DELETE FROM history WHERE timestamp < ?",
                        (result[0],)
                    )
                    conn.commit()
        except Exception as e:
            print(f"✗ Failed to cleanup history: {e}")

    def get_history(self, filter_query: str = "", limit: int = 500) -> List[HistoryEntry]:
        """Get history items, optionally filtered."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if filter_query:
                    query_lower = f"%{filter_query.lower()}%"
                    cursor = conn.execute("""
                        SELECT key_id, key, source, dictionary, timestamp FROM history
                        WHERE LOWER(key) LIKE ? OR LOWER(dictionary) LIKE ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (query_lower, query_lower, limit))
                else:
                    cursor = conn.execute("""
                        SELECT key_id, key, source, dictionary, timestamp FROM history
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (limit,))
                
                rows = []
                for row in cursor.fetchall():
                    rows.append(self.HistoryEntry(
                        term_id=row[0],
                        term=row[1],
                        dict_id=row[2],
                        dict_name=row[3],
                        created_at=row[4]
                    ))
                return rows
        except Exception as e:
            print(f"✗ Failed to get history: {e}")
            return []

    def clear_history(self) -> None:
        """Clear all history."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM history")
                conn.commit()
            print("✓ History cleared")
        except Exception as e:
            print(f"✗ Failed to clear history: {e}")

    def get_count(self) -> int:
        """Get total number of history entries."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM history")
                return int(cursor.fetchone()[0])
        except:
            return 0
