#!/usr/bin/env python3
"""Read-only portability and runtime checks for the stock system."""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path

from runtime_config import (
    API_KEYS_PATH,
    CONFIG_DIR,
    DATA_DIR,
    FUTU_HOST,
    FUTU_PORT,
    NEWS_DB_PATH,
    STRATEGY_DIR,
    WORKSPACE_DIR,
    load_api_keys,
)


JSON_STATE_FILES = (
    "trades.json",
    "open-positions.json",
    "closed-trades.json",
    "staged-reductions.json",
    "notify-cooldowns.json",
    "alerts.json",
    "us-opportunities.json",
    "hk-opportunities.json",
)

REQUIRED_SECRET_FIELDS = {
    "feishu": ("appId", "appSecret", "chatId"),
    "llm": ("api_key",),
    "futu": ("trade_password",),
}


def report(ok: bool, label: str, detail: str = "") -> bool:
    prefix = "OK" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{prefix}] {label}{suffix}")
    return ok


def check_paths() -> bool:
    checks = [
        report(WORKSPACE_DIR.is_dir(), "workspace", str(WORKSPACE_DIR)),
        report(STRATEGY_DIR.is_dir(), "strategy", str(STRATEGY_DIR)),
        report(DATA_DIR.is_dir(), "data", str(DATA_DIR)),
        report(CONFIG_DIR.is_dir(), "config", str(CONFIG_DIR)),
        report(API_KEYS_PATH.is_file(), "private keys", str(API_KEYS_PATH)),
    ]
    return all(checks)


def check_secrets() -> bool:
    keys = load_api_keys()
    checks = []
    for section, fields in REQUIRED_SECRET_FIELDS.items():
        value = keys.get(section, {})
        missing = [field for field in fields if not value.get(field)]
        checks.append(report(not missing, f"secret section {section}", f"missing={missing}" if missing else "configured"))
    return all(checks)


def check_state_files() -> bool:
    checks = []
    for name in JSON_STATE_FILES:
        path = DATA_DIR / name
        if not path.exists():
            checks.append(report(False, f"state {name}", "missing"))
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
            checks.append(report(True, f"state {name}", f"{path.stat().st_size} bytes"))
        except (OSError, ValueError) as exc:
            checks.append(report(False, f"state {name}", str(exc)))
    return all(checks)


def check_news_db() -> bool:
    if not NEWS_DB_PATH.exists():
        return report(False, "news database", "missing")
    try:
        with sqlite3.connect(NEWS_DB_PATH, timeout=5) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
        return report(result == "ok", "news database", result)
    except sqlite3.Error as exc:
        return report(False, "news database", str(exc))


def check_imports() -> bool:
    modules = (
        "runtime_config",
        "four_source_scorer",
        "llm_stock_analyzer",
        "technical_indicators_us",
        "technical_indicators_hk",
        "news_pipeline",
    )
    checks = []
    for name in modules:
        try:
            importlib.import_module(name)
            checks.append(report(True, f"import {name}"))
        except Exception as exc:
            checks.append(report(False, f"import {name}", str(exc)))
    return all(checks)


def check_futu() -> bool:
    try:
        from futu import OpenQuoteContext

        ctx = OpenQuoteContext(FUTU_HOST, FUTU_PORT)
        ctx.close()
        return report(True, "Futu OpenD", f"{FUTU_HOST}:{FUTU_PORT}")
    except Exception as exc:
        return report(False, "Futu OpenD", str(exc))


def print_manifest() -> None:
    print("\nMigration copy set:")
    print(f"- {STRATEGY_DIR}")
    print(f"- {CONFIG_DIR}")
    print(f"- {DATA_DIR}")
    print(f"- {API_KEYS_PATH} (contains private keys)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--futu", action="store_true", help="perform a read-only Futu connection check")
    parser.add_argument("--manifest", action="store_true", help="print paths required for migration")
    args = parser.parse_args()

    results = [check_paths(), check_secrets(), check_state_files(), check_news_db(), check_imports()]
    if args.futu:
        results.append(check_futu())
    if args.manifest:
        print_manifest()
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

