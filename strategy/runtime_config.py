"""Portable runtime paths and machine-specific settings.

Defaults preserve the current workspace layout. A future machine only needs to
set STOCK_HOME (and optional overrides) without changing application code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


STRATEGY_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = Path(os.getenv("STOCK_HOME", STRATEGY_DIR.parent)).expanduser().resolve()
DATA_DIR = Path(os.getenv("STOCK_DATA_DIR", WORKSPACE_DIR / "data")).expanduser().resolve()
CONFIG_DIR = Path(os.getenv("STOCK_CONFIG_DIR", WORKSPACE_DIR / "config")).expanduser().resolve()
LOG_DIR = Path(os.getenv("STOCK_LOG_DIR", WORKSPACE_DIR / "logs")).expanduser().resolve()
REPORTS_DIR = Path(os.getenv("STOCK_REPORTS_DIR", WORKSPACE_DIR / "daily-reports")).expanduser().resolve()
RUNTIME_DIR = Path(os.getenv("STOCK_RUNTIME_DIR", WORKSPACE_DIR / "runtime")).expanduser().resolve()
NEWS_DIR = DATA_DIR / "news"
NEWS_DB_PATH = NEWS_DIR / "news.db"
API_KEYS_PATH = Path(os.getenv("STOCK_API_KEYS_FILE", STRATEGY_DIR / ".api-keys.json")).expanduser().resolve()

FUTU_HOST = os.getenv("FUTU_HOST", "127.0.0.1")
FUTU_PORT = int(os.getenv("FUTU_PORT", "11111"))
FUTU_OPEND_BIN = Path(
    os.getenv(
        "FUTU_OPEND_BIN",
        Path.home() / "Futu_OpenD_10.8.6808_Ubuntu18.04" / "FutuOpenD",
    )
).expanduser().resolve()
PYTHON_BIN = Path(os.getenv("STOCK_PYTHON", sys.executable)).expanduser().resolve()
OPENCLAW_HOME = Path(os.getenv("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser().resolve()
SKILLS_DIR = Path(os.getenv("OPENCLAW_SKILLS_DIR", OPENCLAW_HOME / "skills")).expanduser().resolve()


def data_path(*parts: str) -> Path:
    return DATA_DIR.joinpath(*parts)


def config_path(*parts: str) -> Path:
    return CONFIG_DIR.joinpath(*parts)


def report_path(*parts: str) -> Path:
    return REPORTS_DIR.joinpath(*parts)


def load_api_keys() -> dict[str, Any]:
    try:
        with API_KEYS_PATH.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, CONFIG_DIR, LOG_DIR, REPORTS_DIR, RUNTIME_DIR, NEWS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def add_venv_site_packages() -> None:
    """Add this workspace's venv packages only when not already in that venv."""
    venv_dir = Path(os.getenv("STOCK_VENV", WORKSPACE_DIR / "futu-venv"))
    lib_dir = venv_dir / "lib"
    if not lib_dir.is_dir():
        return
    for candidate in sorted(lib_dir.glob("python*/site-packages"), reverse=True):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)
        break
