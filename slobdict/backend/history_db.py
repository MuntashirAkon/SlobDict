# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path
from datetime import datetime
import sqlite3
from typing import List, Dict, Optional

class HistoryDB:
    """Manage dictionary lookup history with SQLite."""

    def __init__(self):
        """Initialize history database."""
        from ..utils.utils import get_config_dir
        self.config_dir = get_config_dir()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.config_dir / "history.db"
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(key, source)
                )
            """)
            # Index for faster lookups
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON history(timestamp DESC)")
            conn.commit()
        print(f"✓ History database initialized at {self.db_path}")

    def add_entry(self, key: str, source: str):
        """Add entry to history or update timestamp if duplicate."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Try to update existing entry
                cursor = conn.execute(
                    "UPDATE history SET timestamp = CURRENT_TIMESTAMP WHERE key = ? AND source = ?",
                    (key, source)
                )
                
                # If no row was updated, insert new one
                if cursor.rowcount == 0:
                    conn.execute(
                        "INSERT INTO history (key, source) VALUES (?, ?)",
                        (key, source)
                    )
                
                conn.commit()
                
                # Cleanup old entries (keep only 500)
                self._cleanup_old_entries()
        except Exception as e:
            print(f"✗ Failed to add history entry: {e}")

    def _cleanup_old_entries(self):
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

    def get_history(self, filter_query: str = "", limit: int = 500) -> List[Dict]:
        """Get history items, optionally filtered."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                if filter_query:
                    query_lower = f"%{filter_query.lower()}%"
                    cursor = conn.execute("""
                        SELECT key, source, timestamp FROM history
                        WHERE LOWER(key) LIKE ? OR LOWER(source) LIKE ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (query_lower, query_lower, limit))
                else:
                    cursor = conn.execute("""
                        SELECT key, source, timestamp FROM history
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (limit,))
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"✗ Failed to get history: {e}")
            return []

    def clear_history(self):
        """Clear all history."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM history")
                conn.commit()
            print("✓ History cleared")
        except Exception as e:
            print(f"✗ Failed to clear history: {e}")

    def format_timestamp(self, timestamp_str: str) -> str:
        """Format ISO timestamp for display."""
        try:
            # Parse ISO format or SQLite format
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            try:
                # Try SQLite format
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                return timestamp_str

    def get_count(self) -> int:
        """Get total number of history entries."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM history")
                return cursor.fetchone()[0]
        except:
            return 0
