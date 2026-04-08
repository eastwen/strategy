#!/usr/bin/env python3
"""Debug stock quotes"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)

# Try different code formats
codes = ['VRT', 'LITE', 'COHR', 'NVDA', 'US.VRT', 'US.LITE', 'US.COHR', 'US.NVDA']

for code in codes:
    ret, data = quote_ctx.get_market_snapshot([code])
    print(f"{code}: ret={ret}")
    if ret == RET_OK and not data.empty:
        print(f"  {data[['code', 'latest_price', 'volume']].to_string()}")
    else:
        print(f"  Failed: {data}")
    print()

quote_ctx.close()
