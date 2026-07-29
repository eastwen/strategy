#!/usr/bin/env python3
"""每周刷新港股指数成分股，并保留明确配置的自定义标的。"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from futu import OpenQuoteContext, RET_OK
from runtime_config import FUTU_HOST, FUTU_PORT, STRATEGY_DIR

POOL_PATH = STRATEGY_DIR / 'hk-index-constituents.json'
CUSTOM_SYMBOLS = ['HK.07709', 'HK.07747']


def _codes(values):
    result = []
    for value in values or []:
        code = value.get('code') if isinstance(value, dict) else value
        code = str(code or '').strip().upper()
        if code and code.startswith('HK.'):
            result.append(code)
    return list(dict.fromkeys(result))


def fetch_index_constituents(ctx, index_code, index_name):
    ret, data = ctx.get_plate_stock(index_code)
    if ret != RET_OK:
        raise RuntimeError(f'获取{index_name}失败: {data}')
    codes = _codes(data['code'].tolist())
    print(f'✅ {index_name}: {len(codes)}只')
    return codes


def build_updated_pool(hsi, hstech):
    if len(hsi) < 50 or len(hstech) < 20:
        raise ValueError(f'新名单数量异常: 恒指{len(hsi)}、恒科{len(hstech)}')
    custom = _codes(CUSTOM_SYMBOLS)
    all_symbols = list(dict.fromkeys(hsi + hstech + custom))
    return {
        'hsi': hsi,
        'hstech': hstech,
        'custom': custom,
        'hk_all': all_symbols,
        'overlap_count': len(set(hsi) & set(hstech)),
        'unique_count': len(all_symbols),
        'updated_at': datetime.now().isoformat(),
        'update_source': 'Futu HK.800000/HK.800700',
    }


def atomic_write(path, payload):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
    try:
        hsi = fetch_index_constituents(ctx, 'HK.800000', '恒生指数')
        hstech = fetch_index_constituents(ctx, 'HK.800700', '恒生科技指数')
    finally:
        ctx.close()
    payload = build_updated_pool(hsi, hstech)
    print(
        f"📊 最终港股池: 恒指、恒科与自定义标的去重后共"
        f"{payload['unique_count']}只（自定义{len(payload['custom'])}只）"
    )
    if args.dry_run:
        print('🧪 dry-run：未写入文件')
        return
    atomic_write(POOL_PATH, payload)
    print(f'💾 已原子更新: {POOL_PATH}')


if __name__ == '__main__':
    main()
