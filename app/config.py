from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "app" / "static"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "class_notice.db"


def database_path() -> Path:
    configured = os.getenv("BANWUTONG_DATABASE_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATABASE_PATH

