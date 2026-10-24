from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    group_id TEXT,
    sender_id TEXT,
    sent_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    audience TEXT,
    deadline TEXT,
    location TEXT,
    materials TEXT NOT NULL DEFAULT '[]',
    registration_url TEXT,
    contact TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    needs_review INTEGER NOT NULL DEFAULT 0,
    source_message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(activity_id) REFERENCES activities(id),
    FOREIGN KEY(message_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_activities_deadline
ON activities(deadline);

CREATE INDEX IF NOT EXISTS idx_activity_events_activity
ON activity_events(activity_id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """
                UPDATE activities
                SET status = 'open'
                WHERE status = 'needs_review'
                """
            )

