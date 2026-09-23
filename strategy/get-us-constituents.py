#!/usr/bin/env python3
"""每周刷新美股官方股票池，只保留当前官方名单。"""

import argparse
import csv
import io
import json
import os
import re
from datetime import datetime

import pandas as pd
import requests

from runtime_config import STRATEGY_DIR, load_api_keys

POOL_PATH = STRATEGY_DIR / 'us-index-constituents.json'
SP500_URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
SP500_FALLBACK_URL = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'
NASDAQ_URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt'
FINNHUB_URL = 'https://finnhub.io/api/v1/stock/symbol'
HEADERS = {'User-Agent': 'Mozilla/5.0 stock-pool-updater/1.0'}
FINNHUB_EQUITY_TYPES = {'Common Stock', 'ADR', 'REIT'}
MIN_MARKET_CAP_USD = 500_000_000
LONGBRIDGE_BATCH_SIZE = 500


def _is_supported_nasdaq_security(row):
    """Keep operating equities; reject warrants, rights, units and preferred shares."""
    if row.get('Test Issue') != 'N' or row.get('ETF') != 'N':
        return False
    name = str(row.get('Security Name') or '').strip()
    excluded = re.compile(
        r'\b(warrants?|rights?|units?|preferred|preference)\b',
        re.IGNORECASE,
    )
    return not excluded.search(name)


def _symbols(values):
    result = []
    for value in values or []:
        symbol = value.get('symbol') if isinstance(value, dict) else value
        symbol = str(symbol or '').strip().upper()
        if symbol:
            result.append(symbol)
    return list(dict.fromkeys(result))


def fetch_sp500_wikipedia():
    response = requests.get(SP500_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    tables = pd.read_html(io.StringIO(response.text))
    symbols = _symbols(tables[0]['Symbol'].tolist())
    if len(symbols) < 450:
        raise ValueError(f'Wikipedia标普500数量异常: {len(symbols)}')
    return symbols


def fetch_sp500_github():
    response = requests.get(SP500_FALLBACK_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    rows = csv.DictReader(io.StringIO(response.text))
    symbols = _symbols(row.get('Symbol') for row in rows)
    if len(symbols) < 450:
        raise ValueError(f'GitHub CSV标普500数量异常: {len(symbols)}')
    return symbols


def fetch_sp500():
    sources = {}
    errors = {}
    try:
        sources['wikipedia'] = fetch_sp500_wikipedia()
    except Exception as error:
        errors['wikipedia'] = str(error)
        print(f'⚠️ Wikipedia标普名单失败: {error}')
    try:
        sources['github_csv'] = fetch_sp500_github()
    except Exception as error:
        errors['github_csv'] = str(error)
        print(f'⚠️ GitHub CSV标普名单失败: {error}')

    if not sources:
        raise RuntimeError(f'标普500全部名单源失败: {errors}')
    if 'wikipedia' in sources and 'github_csv' in sources:
        wiki_set = set(sources['wikipedia'])
        github_set = set(sources['github_csv'])
        only_wiki = sorted(wiki_set - github_set)
        only_github = sorted(github_set - wiki_set)
        if len(only_wiki) + len(only_github) > 20:
            raise ValueError(
                f'标普500双源差异异常: Wikipedia独有{len(only_wiki)}只、'
                f'GitHub独有{len(only_github)}只'
            )
        symbols = sources['wikipedia']
        selected = 'Wikipedia（双源核对）'
        print(
            f'🔎 标普500双源差异: Wikipedia独有{len(only_wiki)}只、'
            f'GitHub独有{len(only_github)}只'
        )
    elif 'wikipedia' in sources:
        symbols = sources['wikipedia']
        selected = 'Wikipedia（GitHub不可用）'
    else:
        symbols = sources['github_csv']
        selected = 'GitHub CSV（Wikipedia不可用）'
    print(f'✅ 标普500: {len(symbols)}只 ({selected})')
    return symbols


def fetch_nasdaq():
    response = requests.get(NASDAQ_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    rows = csv.DictReader(io.StringIO(response.text), delimiter='|')
    symbols = _symbols(
        row.get('Symbol') for row in rows
        if _is_supported_nasdaq_security(row)
    )
    if len(symbols) < 3000:
        raise ValueError(f'纳斯达克正常上市股票数量异常: {len(symbols)}')
    print(f'✅ 纳斯达克普通股/ADR/REIT: {len(symbols)}只')
    return symbols


def fetch_market_caps_longbridge(symbols, keys):
    """Batch market caps from real Longbridge shares and quotes."""
    config = keys.get('longbridge', {})
    required = ('app_key', 'app_secret', 'token')
    if not all(config.get(key) for key in required):
        raise RuntimeError('长桥配置不完整，无法执行市值股票池过滤')

    from longbridge.openapi import Config, QuoteContext

    client_config = Config.from_apikey(
        config['app_key'], config['app_secret'], config['token'],
    )
    quote_ctx = QuoteContext(client_config)
    market_caps = {}
    unique_symbols = list(dict.fromkeys(symbols))
    for offset in range(0, len(unique_symbols), LONGBRIDGE_BATCH_SIZE):
        batch = unique_symbols[offset:offset + LONGBRIDGE_BATCH_SIZE]
        longbridge_symbols = [f'{symbol}.US' for symbol in batch]
        static_rows = quote_ctx.static_info(longbridge_symbols)
        quote_rows = quote_ctx.quote(longbridge_symbols)
        shares_by_symbol = {
            str(row.symbol).removesuffix('.US'): int(row.total_shares or 0)
            for row in static_rows
        }
        price_by_symbol = {
            str(row.symbol).removesuffix('.US'): float(row.last_done or 0)
            for row in quote_rows
        }
        for symbol in batch:
            shares = shares_by_symbol.get(symbol, 0)
            price = price_by_symbol.get(symbol, 0)
            if shares > 0 and price > 0:
                market_caps[symbol] = shares * price
    if len(market_caps) < max(1, int(len(unique_symbols) * 0.8)):
        raise RuntimeError(
            f'长桥市值覆盖异常: {len(market_caps)}/{len(unique_symbols)}，停止更新以防误删'
        )
    return market_caps


def fetch_finnhub(api_key):
    if not api_key:
        print('⚠️ Finnhub未配置，跳过股票名录备用源')
        return []
    response = requests.get(FINNHUB_URL, params={
        'exchange': 'US', 'token': api_key,
    }, headers=HEADERS, timeout=45)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError('Finnhub股票名录响应格式异常')
    symbols = _symbols(
        row.get('symbol') for row in rows
        if row.get('mic') == 'XNAS'
        and row.get('type') in FINNHUB_EQUITY_TYPES
    )
    if len(symbols) < 3000:
        raise ValueError(f'Finnhub美国交易所股票数量异常: {len(symbols)}')
    print(f'✅ Finnhub纳斯达克股票: {len(symbols)}只')
    return symbols


def _optional_source(name, fetcher, api_key):
    try:
        return fetcher(api_key)
    except Exception as error:
        print(f'⚠️ {name}股票名录失败，本周使用其他真实来源: {error}')
        return []


def build_updated_pool(
    sp500, nasdaq, finnhub=None, existing_custom=None, market_caps=None,
):
    finnhub = finnhub or []
    custom = _symbols(existing_custom)
    unfiltered_symbols = list(dict.fromkeys(
        sp500 + nasdaq + finnhub + custom
    ))
    if market_caps is None:
        all_symbols = unfiltered_symbols
        market_cap_excluded = []
        market_cap_unresolved = []
    else:
        market_cap_excluded = [
            symbol for symbol in unfiltered_symbols
            if 0 < float(market_caps.get(symbol, 0)) < MIN_MARKET_CAP_USD
        ]
        market_cap_unresolved = [
            symbol for symbol in unfiltered_symbols if not market_caps.get(symbol)
        ]
        # Strict pool gate: unresolved capitalization cannot be verified as >= $500m.
        excluded = set(market_cap_excluded + market_cap_unresolved)
        all_symbols = [symbol for symbol in unfiltered_symbols if symbol not in excluded]
        allowed = set(all_symbols)
        sp500 = [symbol for symbol in sp500 if symbol in allowed]
        nasdaq = [symbol for symbol in nasdaq if symbol in allowed]
        finnhub = [symbol for symbol in finnhub if symbol in allowed]
        custom = [symbol for symbol in custom if symbol in allowed]
    source_sets = tuple(map(set, (
        sp500, nasdaq, finnhub,
    )))
    return {
        'sp500': sp500,
        'nasdaq': nasdaq,
        'finnhub_us': finnhub,
        'custom': custom,
        'all': all_symbols,
        'unique_stocks': all_symbols,
        'overlap_count': sum(
            1 for symbol in all_symbols
            if sum(symbol in source for source in source_sets) > 1
        ),
        'unique_count': len(all_symbols),
        'market_cap_filter': {
            'minimum_usd': MIN_MARKET_CAP_USD,
            'excluded_count': len(market_cap_excluded),
            'excluded_symbols': market_cap_excluded,
            'unresolved_excluded_count': len(market_cap_unresolved),
            'unresolved_excluded_symbols': market_cap_unresolved,
            'source': 'Longbridge total_shares x last_done',
        },
        'updated_at': datetime.now().isoformat(),
        'update_source': 'S&P 500 + Nasdaq Trader + Finnhub Nasdaq',
        'source_counts': {
            'sp500': len(sp500),
            'nasdaq': len(nasdaq),
            'finnhub_us': len(finnhub),
        },
    }


def atomic_write(path, payload):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    existing = json.loads(POOL_PATH.read_text()) if POOL_PATH.exists() else {}
    keys = load_api_keys()
    sp500 = fetch_sp500()
    nasdaq = fetch_nasdaq()
    finnhub = _optional_source(
        'Finnhub', fetch_finnhub,
        keys.get('finnhub', {}).get('api_key', ''),
    )
    raw_symbols = list(dict.fromkeys(
        sp500 + nasdaq + finnhub + _symbols(existing.get('custom', []))
    ))
    market_caps = fetch_market_caps_longbridge(raw_symbols, keys)
    payload = build_updated_pool(
        sp500, nasdaq, finnhub,
        existing_custom=existing.get('custom', []),
        market_caps=market_caps,
    )
    print(
        f"📊 最终美股池: 多源合并去重后共{payload['unique_count']}只，"
        f"市值<$5亿剔除{payload['market_cap_filter']['excluded_count']}只，"
        f"市值未解析并剔除{payload['market_cap_filter']['unresolved_excluded_count']}只"
    )
    if args.dry_run:
        print('🧪 dry-run：未写入文件')
        return
    atomic_write(POOL_PATH, payload)
    print(f'💾 已原子更新: {POOL_PATH}')


if __name__ == '__main__':
    main()
