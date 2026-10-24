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
    deleted_at TEXT,
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

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL UNIQUE,
    media_type TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    extract_status TEXT NOT NULL,
    extract_note TEXT,
    analysis_method TEXT NOT NULL DEFAULT 'rules',
    extracted_text TEXT,
    message_id INTEGER,
    activity_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES messages(id),
    FOREIGN KEY(activity_id) REFERENCES activities(id)
);

CREATE TABLE IF NOT EXISTS document_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    locator TEXT NOT NULL,
    block_type TEXT NOT NULL,
    text TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE(document_id, locator),
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS document_activity_links (
    document_id INTEGER NOT NULL,
    activity_id INTEGER NOT NULL,
    PRIMARY KEY(document_id, activity_id),
    FOREIGN KEY(document_id) REFERENCES documents(id),
    FOREIGN KEY(activity_id) REFERENCES activities(id)
);

CREATE TABLE IF NOT EXISTS activity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    block_id INTEGER NOT NULL,
    activity_id INTEGER NOT NULL,
    quote TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id),
    FOREIGN KEY(block_id) REFERENCES document_blocks(id),
    FOREIGN KEY(activity_id) REFERENCES activities(id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activities_deadline
ON activities(deadline);

CREATE INDEX IF NOT EXISTS idx_activity_events_activity
ON activity_events(activity_id);

CREATE INDEX IF NOT EXISTS idx_documents_sha256
ON documents(sha256);

CREATE INDEX IF NOT EXISTS idx_document_blocks_document
ON document_blocks(document_id);

CREATE INDEX IF NOT EXISTS idx_activity_mentions_activity
ON activity_mentions(activity_id);
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
            document_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(documents)")
            }
            if "analysis_method" not in document_columns:
                connection.execute(
                    """
                    ALTER TABLE documents
                    ADD COLUMN analysis_method TEXT NOT NULL DEFAULT 'rules'
                    """
                )
            activity_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(activities)")
            }
            if "deleted_at" not in activity_columns:
                connection.execute(
                    "ALTER TABLE activities ADD COLUMN deleted_at TEXT"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_activities_deleted_at
                ON activities(deleted_at)
                """
            )
            connection.execute(
                """
                UPDATE activities
                SET status = 'open'
                WHERE status = 'needs_review'
                """
            )

