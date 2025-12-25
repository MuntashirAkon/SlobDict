# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path
from datetime import datetime
import sqlite3
from typing import List, Dict, Optional
from ..utils.structs import DictEntry


class BookmarksDB:
    """Manage dictionary entry bookmarks with SQLite."""

    class BookmarkEntry(DictEntry):
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
        """Initialize bookmarks database."""
        from ..utils.utils import get_config_dir
        self.config_dir = get_config_dir()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.config_dir / "bookmarks.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    dictionary TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(key_id, source)
                )
            """)
            # Index for faster lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON bookmarks(created_at DESC)")
            conn.commit()
        print(f"✓ Bookmarks database initialized at {self.db_path}")

    def add_bookmark(self, entry: DictEntry) -> bool:
        """Add entry to bookmarks. Returns True if added, False if already exists."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT INTO bookmarks (key_id, key, source, dictionary) VALUES (?, ?, ?, ?)",
                    (str(entry.term_id), entry.term, entry.dict_id, entry.dict_name)
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            # Already bookmarked
            return False
        except Exception as e:
            print(f"✗ Failed to add bookmark: {e}")
            return False

    def remove_bookmark(self, entry: DictEntry) -> bool:
        """Remove entry from bookmarks. Returns True if removed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM bookmarks WHERE key_id = ? AND source = ?",
                    (str(entry.term_id), entry.dict_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"✗ Failed to remove bookmark: {e}")
            return False

    def is_bookmarked(self, entry: DictEntry) -> bool:
        """Check if entry is bookmarked."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM bookmarks WHERE key_id = ? AND source = ?",
                    (str(entry.term_id), entry.dict_id)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"✗ Failed to check bookmark: {e}")
            return False

    def get_bookmarks(self, filter_query: str = "", limit: int = 1000) -> List[BookmarkEntry]:
        """Get bookmarks, optionally filtered."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if filter_query:
                    query_lower = f"%{filter_query.lower()}%"
                    cursor = conn.execute("""
                        SELECT key_id, key, source, dictionary, created_at FROM bookmarks
                        WHERE LOWER(key) LIKE ? OR LOWER(dictionary) LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (query_lower, query_lower, limit))
                else:
                    cursor = conn.execute("""
                        SELECT key_id, key, source, dictionary, created_at FROM bookmarks
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (limit,))
                
                rows = []
                for row in cursor.fetchall():
                    rows.append(self.BookmarkEntry(
                        term_id=row[0],
                        term=row[1],
                        dict_id=row[2],
                        dict_name=row[3],
                        created_at=row[4]
                    ))
                return rows
        except Exception as e:
            print(f"✗ Failed to get bookmarks: {e}")
            return []

    def clear_bookmarks(self) -> None:
        """Clear all bookmarks."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM bookmarks")
                conn.commit()
            print("✓ Bookmarks cleared")
        except Exception as e:
            print(f"✗ Failed to clear bookmarks: {e}")

    def get_count(self) -> int:
        """Get total number of bookmarks."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM bookmarks")
                return int(cursor.fetchone()[0])
        except:
            return 0
