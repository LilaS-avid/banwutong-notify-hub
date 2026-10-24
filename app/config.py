from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "app" / "static"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "class_notice.db"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
load_dotenv(PROJECT_ROOT / ".env")


def database_path() -> Path:
    configured = os.getenv("BANWUTONG_DATABASE_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATABASE_PATH


def upload_directory() -> Path:
    configured = os.getenv("BANWUTONG_UPLOAD_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_UPLOAD_DIR

