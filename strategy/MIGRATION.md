# Single-machine migration

The system keeps all current trading data. Migration is a stop-copy-start operation; it is not a fresh start.

## Files to copy

- `strategy/`, including private `strategy/.api-keys.json`
- `config/`
- `data/`, including all JSON state and `data/news/news.db`
- dependency lock file and the environment overrides used on the destination machine

Do not delete state files after the code refactor. Old code is cleaned separately from business data.

## Destination setup

1. Install the required Python version and dependencies.
2. Install and configure Futu OpenD.
3. Copy `strategy/`, `config/`, `data/`, and `.api-keys.json` without changing their contents.
4. Set `STOCK_HOME`, `STOCK_PYTHON`, and `FUTU_OPEND_BIN` when the destination layout differs.
5. Run `python3 strategy/system-preflight.py --futu --manifest`.
6. Confirm positions, cooldowns, staged reductions, and news database all pass.
7. Stop scheduled jobs on the old machine, then enable them on the new machine.

The default configuration continues to use `127.0.0.1:11111` for Futu OpenD.
