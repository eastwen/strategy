# Old-code cleanup candidates

No files in this list have been deleted. Business data under `data/` is never part of code cleanup.

## High-confidence candidates

- `venv.bak/`: old Python 3.12 virtual environment copy; not referenced by the active cron.

## Retained regression tests

- `test_market_sentiment.py`: offline market-sentiment weighting and fallback tests.
- `test_position_control.py`: offline position sizing, pending-fill and local-state tests.
- `test_news_integration.py`: offline news persistence and deduplication tests.
- `test_five_source_scorer.py`: offline five-source scoring and LLM-prompt tests.

## Review before deletion

- `news_integration.py`: referenced by the old `cron-tasks.txt`, but not by the active crontab. The current `news_pipeline.py` appears to replace this flow.
- `sentiment-3day-predictor.py`: no active cron or production import found.
- `earnings-forecast-module.py`: no active cron or production import found.
- `update-heartbeat-status.py`: no active cron or production import found; current heartbeat uses `heartbeat-check.py`.

## Maintenance utilities to retain

- `get-us-constituents.py`
- `get-constituents.py`
- `recompute_sentiment.py`

These are not active daemons but remain useful for manual data maintenance. Their paths should be made portable before future use.

Deletion requires a separate confirmation after one normal trading cycle on the refactored production code.
