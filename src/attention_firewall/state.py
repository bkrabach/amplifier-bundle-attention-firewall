"""State management for Attention Firewall.

Provides SQLite persistence with in-memory caching for fast lookups.
Philosophy: Simple, direct SQL - no ORM complexity.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class NotificationStateManager:
    """Persistent state for notification filtering.
    
    Two-tier storage:
    - SQLite: Durable storage for notifications and policies
    - Memory: Fast lookup for VIPs, keywords, app settings
    """
    
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # In-memory caches (loaded from DB on init)
        self._vips: dict[str, str] = {}  # sender -> notes
        self._keywords: set[str] = set()
        self._muted_apps: dict[str, datetime | None] = {}  # app -> until_time
        self._suppress_patterns: set[str] = set()
        
        self._init_db()
        self._load_cache()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)
    
    def _init_db(self) -> None:
        """Create tables if needed."""
        conn = self._get_conn()
        conn.executescript("""
            -- Notification history
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                title TEXT,
                body TEXT,
                sender TEXT,
                conversation_hint TEXT,
                timestamp TEXT NOT NULL,
                surfaced INTEGER DEFAULT 0,
                decision TEXT,  -- 'surfaced', 'suppressed', 'digest'
                rationale TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- VIP senders (always surface their messages)
            CREATE TABLE IF NOT EXISTS vips (
                sender TEXT PRIMARY KEY,
                notes TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Priority keywords (trigger surfacing)
            CREATE TABLE IF NOT EXISTS keywords (
                keyword TEXT PRIMARY KEY,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Muted apps (temporarily suppress)
            CREATE TABLE IF NOT EXISTS muted_apps (
                app_id TEXT PRIMARY KEY,
                until_time TEXT,  -- NULL means indefinite
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Suppress patterns (noise patterns to always filter)
            CREATE TABLE IF NOT EXISTS suppress_patterns (
                pattern TEXT PRIMARY KEY,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Indexes for fast queries
            CREATE INDEX IF NOT EXISTS idx_notif_sender ON notifications(sender);
            CREATE INDEX IF NOT EXISTS idx_notif_timestamp ON notifications(timestamp);
            CREATE INDEX IF NOT EXISTS idx_notif_app ON notifications(app_id);
            CREATE INDEX IF NOT EXISTS idx_notif_decision ON notifications(decision);
            CREATE INDEX IF NOT EXISTS idx_notif_conversation 
                ON notifications(app_id, conversation_hint);
        """)
        conn.commit()
        conn.close()
    
    def _load_cache(self) -> None:
        """Load policies into memory for fast access."""
        conn = self._get_conn()
        
        # Load VIPs
        self._vips = {
            row[0].lower(): row[1] 
            for row in conn.execute("SELECT sender, notes FROM vips")
        }
        
        # Load keywords
        self._keywords = {
            row[0].lower() 
            for row in conn.execute("SELECT keyword FROM keywords")
        }
        
        # Load muted apps
        for row in conn.execute("SELECT app_id, until_time FROM muted_apps"):
            until = datetime.fromisoformat(row[1]) if row[1] else None
            self._muted_apps[row[0].lower()] = until
        
        # Load suppress patterns
        self._suppress_patterns = {
            row[0].lower() 
            for row in conn.execute("SELECT pattern FROM suppress_patterns")
        }
        
        conn.close()
    
    # -------------------------------------------------------------------------
    # Notification Storage
    # -------------------------------------------------------------------------
    
    def store_notification(
        self,
        app_id: str,
        title: str,
        body: str,
        timestamp: str,
        sender: str | None = None,
        conversation_hint: str | None = None,
    ) -> str:
        """Store a notification and return its ID."""
        notif_id = str(uuid.uuid4())
        
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO notifications 
            (id, app_id, title, body, sender, conversation_hint, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (notif_id, app_id, title, body, sender, conversation_hint, timestamp))
        conn.commit()
        conn.close()
        
        return notif_id
    
    def update_notification_decision(
        self, 
        notif_id: str, 
        decision: str, 
        rationale: str | None = None,
        surfaced: bool = False,
    ) -> None:
        """Update the decision for a notification."""
        conn = self._get_conn()
        conn.execute("""
            UPDATE notifications 
            SET decision = ?, rationale = ?, surfaced = ?
            WHERE id = ?
        """, (decision, rationale, 1 if surfaced else 0, notif_id))
        conn.commit()
        conn.close()
    
    def get_pending_notifications(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get notifications pending for digest."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT id, app_id, title, body, sender, timestamp, rationale
            FROM notifications
            WHERE decision = 'digest' AND timestamp > ?
            ORDER BY timestamp DESC
        """, (cutoff,)).fetchall()
        conn.close()
        
        return [
            {
                "id": r[0],
                "app_id": r[1],
                "title": r[2],
                "body": r[3],
                "sender": r[4],
                "timestamp": r[5],
                "rationale": r[6],
            }
            for r in rows
        ]
    
    def clear_pending_notifications(self) -> int:
        """Mark pending notifications as processed. Returns count."""
        conn = self._get_conn()
        cursor = conn.execute("""
            UPDATE notifications 
            SET decision = 'processed'
            WHERE decision = 'digest'
        """)
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count
    
    # -------------------------------------------------------------------------
    # VIP Management
    # -------------------------------------------------------------------------
    
    def is_vip(self, sender: str | None) -> bool:
        """Check if sender is VIP (fast, in-memory)."""
        if not sender:
            return False
        return sender.lower() in self._vips
    
    def add_vip(self, sender: str, notes: str = "") -> None:
        """Add sender to VIP list."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO vips (sender, notes) VALUES (?, ?)",
            (sender, notes)
        )
        conn.commit()
        conn.close()
        self._vips[sender.lower()] = notes
    
    def remove_vip(self, sender: str) -> bool:
        """Remove sender from VIP list. Returns True if existed."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM vips WHERE LOWER(sender) = ?", (sender.lower(),))
        existed = cursor.rowcount > 0
        conn.commit()
        conn.close()
        self._vips.pop(sender.lower(), None)
        return existed
    
    def get_vips(self) -> dict[str, str]:
        """Get all VIPs."""
        return dict(self._vips)
    
    # -------------------------------------------------------------------------
    # Keyword Management
    # -------------------------------------------------------------------------
    
    def check_keywords(self, text: str) -> list[str]:
        """Check for keyword matches (fast, in-memory)."""
        text_lower = text.lower()
        return [kw for kw in self._keywords if kw in text_lower]
    
    def add_keyword(self, keyword: str) -> None:
        """Add priority keyword."""
        conn = self._get_conn()
        conn.execute("INSERT OR IGNORE INTO keywords (keyword) VALUES (?)", (keyword,))
        conn.commit()
        conn.close()
        self._keywords.add(keyword.lower())
    
    def remove_keyword(self, keyword: str) -> bool:
        """Remove keyword. Returns True if existed."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM keywords WHERE LOWER(keyword) = ?", 
            (keyword.lower(),)
        )
        existed = cursor.rowcount > 0
        conn.commit()
        conn.close()
        self._keywords.discard(keyword.lower())
        return existed
    
    def get_keywords(self) -> set[str]:
        """Get all keywords."""
        return set(self._keywords)
    
    # -------------------------------------------------------------------------
    # App Muting
    # -------------------------------------------------------------------------
    
    def is_app_muted(self, app_id: str) -> bool:
        """Check if app is currently muted."""
        app_lower = app_id.lower()
        if app_lower not in self._muted_apps:
            return False
        
        until = self._muted_apps[app_lower]
        if until is None:
            return True  # Indefinitely muted
        
        if datetime.now() < until:
            return True
        
        # Mute expired, clean up
        self._unmute_app(app_id)
        return False
    
    def mute_app(self, app_id: str, until: datetime | None = None) -> None:
        """Mute an app, optionally until a specific time."""
        until_str = until.isoformat() if until else None
        
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO muted_apps (app_id, until_time) VALUES (?, ?)",
            (app_id, until_str)
        )
        conn.commit()
        conn.close()
        self._muted_apps[app_id.lower()] = until
    
    def _unmute_app(self, app_id: str) -> None:
        """Internal unmute (used for expiry cleanup)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM muted_apps WHERE LOWER(app_id) = ?", (app_id.lower(),))
        conn.commit()
        conn.close()
        self._muted_apps.pop(app_id.lower(), None)
    
    def unmute_app(self, app_id: str) -> bool:
        """Unmute an app. Returns True if was muted."""
        was_muted = app_id.lower() in self._muted_apps
        self._unmute_app(app_id)
        return was_muted
    
    def get_muted_apps(self) -> dict[str, datetime | None]:
        """Get all muted apps."""
        return dict(self._muted_apps)
    
    # -------------------------------------------------------------------------
    # Suppress Patterns
    # -------------------------------------------------------------------------
    
    def matches_suppress_pattern(self, text: str) -> str | None:
        """Check if text matches any suppress pattern. Returns matched pattern or None."""
        text_lower = text.lower()
        for pattern in self._suppress_patterns:
            if pattern in text_lower:
                return pattern
        return None
    
    def add_suppress_pattern(self, pattern: str) -> None:
        """Add a suppress pattern."""
        conn = self._get_conn()
        conn.execute("INSERT OR IGNORE INTO suppress_patterns (pattern) VALUES (?)", (pattern,))
        conn.commit()
        conn.close()
        self._suppress_patterns.add(pattern.lower())
    
    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    
    def get_statistics(self, hours: int = 24) -> dict[str, Any]:
        """Get notification statistics for the given timeframe."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        conn = self._get_conn()
        
        # Total count
        total = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE timestamp > ?",
            (cutoff,)
        ).fetchone()[0]
        
        # By decision
        by_decision = {
            row[0] or "pending": row[1]
            for row in conn.execute("""
                SELECT decision, COUNT(*) FROM notifications 
                WHERE timestamp > ? GROUP BY decision
            """, (cutoff,))
        }
        
        # By app
        by_app = {
            row[0]: row[1]
            for row in conn.execute("""
                SELECT app_id, COUNT(*) FROM notifications 
                WHERE timestamp > ? GROUP BY app_id
            """, (cutoff,))
        }
        
        # Top senders
        top_senders = {
            row[0]: row[1]
            for row in conn.execute("""
                SELECT sender, COUNT(*) FROM notifications 
                WHERE timestamp > ? AND sender IS NOT NULL 
                GROUP BY sender ORDER BY COUNT(*) DESC LIMIT 10
            """, (cutoff,))
        }
        
        conn.close()
        
        return {
            "timeframe_hours": hours,
            "total": total,
            "by_decision": by_decision,
            "by_app": by_app,
            "top_senders": top_senders,
            "surfaced": by_decision.get("surfaced", 0),
            "suppressed": by_decision.get("suppressed", 0),
            "digest": by_decision.get("digest", 0),
        }
    
    def recent_from_sender(self, sender: str | None, hours: int = 1) -> int:
        """Count recent notifications from a sender."""
        if not sender:
            return 0
        
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE LOWER(sender) = ? AND timestamp > ?",
            (sender.lower(), cutoff)
        ).fetchone()[0]
        conn.close()
        return count
    
    def get_all_policies(self) -> dict[str, Any]:
        """Get all current policies for display."""
        return {
            "vips": list(self._vips.keys()),
            "keywords": list(self._keywords),
            "muted_apps": {
                app: until.isoformat() if until else "indefinite"
                for app, until in self._muted_apps.items()
            },
            "suppress_patterns": list(self._suppress_patterns),
        }
