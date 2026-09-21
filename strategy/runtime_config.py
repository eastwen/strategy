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

# Single source of truth for strategy thresholds shown in reports and enforced by runners.
SYSTEM_VERSION = "v2.9"
HK_STRATEGY_VERSION = "v2.3"
US_STRATEGY_VERSION = "v2.0"
SYSTEM_UPDATED = "2026-09-22"
HK_STRATEGY_UPDATED = SYSTEM_UPDATED
US_STRATEGY_UPDATED = SYSTEM_UPDATED

STRATEGY_POLICY = {
    "us": {
        "version": US_STRATEGY_VERSION, "updated": US_STRATEGY_UPDATED, "min_score": 75,
        "opp_alert_score": 85, "position_size": 0.12, "max_positions": 999,
        "single_position_limit": 0.12, "total_position_limit": 1.0,
        "score_position_rules": "75-79分 6%-8%；80-84分 8%-10%；85-89分 10%-11%；90-94分 11%-12%；95分以上 12%",
        "market_sentiment_rules": "≥65 正常；55-64 为90%；45-54 为80%；35-44 为60%；25-34 为50%；<25 暂停开仓",
        "entry_timing": {
            "enabled": True,
            "mode": "trend_or_passive_day_limit",
            "watch_minutes": 30,
            "max_signal_age_minutes": 120,
            "max_signal_drift_pct": 1.5,
            "near_day_high_pct": 0.5,
            "limit_buffer_pct": 0.25,
            "passive_discount_pct": 0.3,
            "order_ttl_seconds": 120,
            "min_session_bars": 8,
            "breakout_hold_bars": 2,
            "breakout_volume_ratio": 1.2,
        },
    },
    "hk": {
        "version": HK_STRATEGY_VERSION, "updated": HK_STRATEGY_UPDATED, "min_score": 75,
        "position_size": 0.03, "max_positions": 999,
        "single_position_limit": 0.06, "total_position_limit": 1.0,
        "score_position_rules": "75-79分 2%；80-84分 3%；85-89分 4%；90-94分 5%；95分以上 6%",
        "entry_timing": {
            "enabled": True,
            "watch_minutes": 30,
            "max_signal_age_minutes": 30,
            "max_signal_drift_pct": 1.5,
            "near_day_high_pct": 0.5,
            "limit_buffer_pct": 0.20,
            "order_ttl_seconds": 120,
            "min_session_bars": 8,
            "breakout_hold_bars": 2,
            "breakout_volume_ratio": 1.2,
        },
    },
    "risk": {
        "cooldown_seconds": 86400, "hard_stop_loss_pct": -6,
        "trailing_profit_trigger_pct": 4, "trailing_drawdown_pct": 2,
        # 2026-08-25 east：时间维度退出规则（条件版）
        "us_max_holding_trading_days": 6, "hk_max_holding_trading_days": 10,
        "time_exit_min_profit_pct": 2.0,
    },
}


def format_strategy_policy_markdown() -> str:
    """Render the current user-visible strategy rules from one policy source."""
    us = STRATEGY_POLICY["us"]
    hk = STRATEGY_POLICY["hk"]
    risk = STRATEGY_POLICY["risk"]
    return f"""### 🇭🇰 港股策略（{hk["version"]}，配置更新：{hk["updated"]}）
- 五源共振：国际资讯、港股公告、社区情绪、机构观点、资金异动
- 计分口径：多源原始证据先合并去重再统一计分，单源失败不扣分，五源中性基线合计50分
- 交易候选线：综合评分≥{hk["min_score"]}；动态仓位：{hk["score_position_rules"]}
- 单票上限：{hk["single_position_limit"] * 100:.0f}%；总仓位上限：{hk["total_position_limit"] * 100:.0f}%
- 盘中买点：候选最多观察{hk["entry_timing"]["watch_minutes"]}分钟；回踩VWAP/EMA9重新站稳或放量突破确认后，以价格保护限价单入场
- 风控：ATR动态止盈止损，浮亏≥{abs(risk["hard_stop_loss_pct"]):.0f}%硬止损；时间维度退出：满{risk["hk_max_holding_trading_days"]}个交易日仍未触发止损止盈且浮盈<{risk["time_exit_min_profit_pct"]:.0f}%则全平认错，浮盈≥{risk["time_exit_min_profit_pct"]:.0f}%则止损提到保本位继续持有

### 🇺🇸 美股策略（{us["version"]}，配置更新：{us["updated"]}）
- 五源共振后仅将 Top 20 送入 LLM；LLM失败或未通过不交易
- 计分口径：多源原始证据先合并去重再统一计分，单源失败不扣分，五源中性基线合计50分
- 交易候选线：综合评分≥{us["min_score"]}；非交易时段提醒线：{us["opp_alert_score"]}
- 动态仓位：{us["score_position_rules"]}；单票上限：{us["single_position_limit"] * 100:.0f}%
- 市场情绪总仓位：{us["market_sentiment_rules"]}
- 盘中买点：日线条件通过且现价站稳VWAP/EMA9、未超过信号价1.5%时以保护限价单直接入场；否则挂DAY被动限价等待回踩；不主动撤单，未成交由富途收盘失效
- 风控：ATR动态止盈止损，浮盈≥{risk["trailing_profit_trigger_pct"]}%后从最高价回撤{risk["trailing_drawdown_pct"]}%触发追踪止盈，浮亏≥{abs(risk["hard_stop_loss_pct"]):.0f}%硬止损；时间维度退出：满{risk["us_max_holding_trading_days"]}个交易日仍未触发止损止盈且浮盈<{risk["time_exit_min_profit_pct"]:.0f}%则全平认错，浮盈≥{risk["time_exit_min_profit_pct"]:.0f}%则止损提到保本位继续持有

"""


def format_strategy_policy_compact() -> str:
    """Render concise rules for report advice and LLM prompts."""
    us = STRATEGY_POLICY["us"]
    hk = STRATEGY_POLICY["hk"]
    risk = STRATEGY_POLICY["risk"]
    return (
        f"系统版本：{SYSTEM_VERSION}；港股策略：{hk['version']}；"
        f"美股策略：{us['version']}（更新：{SYSTEM_UPDATED}）\n"
        f"港股交易线：{hk['min_score']}分；动态仓位：{hk['score_position_rules']}；"
        f"单票上限{hk['single_position_limit'] * 100:.0f}%\n"
        f"港股盘中买点：候选观察{hk['entry_timing']['watch_minutes']}分钟，回踩VWAP/EMA9企稳或放量突破后限价入场\n"
        f"美股交易线：{us['min_score']}分；非交易提醒线：{us['opp_alert_score']}分；"
        f"动态仓位：{us['score_position_rules']}；单票上限{us['single_position_limit'] * 100:.0f}%\n"
        f"美股盘中买点：站稳VWAP/EMA9且未超过信号价1.5%时保护限价直入，否则挂DAY被动限价等待回踩；不主动撤单\n"
        f"共同风控：浮亏达到{abs(risk['hard_stop_loss_pct'])}%触发硬止损；"
        f"浮盈达到{risk['trailing_profit_trigger_pct']:.0f}%后，从最高价回撤"
        f"{risk['trailing_drawdown_pct']:.0f}%触发追踪止盈；ATR目标优先于固定估算价；"
        f"时间维度退出：美股满{risk['us_max_holding_trading_days']}个/港股满{risk['hk_max_holding_trading_days']}个交易日"
        f"仍未触发止损止盈且浮盈<{risk['time_exit_min_profit_pct']:.0f}%则全平认错，"
        f"浮盈达标则止损提到保本位继续持有（按交易日计，优先级低于止损止盈）"
    )


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
