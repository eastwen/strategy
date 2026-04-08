#!/usr/bin/env python3
"""查找正确的列名"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)

ret, snapshot = quote_ctx.get_market_snapshot(['HK.00001'])

if ret == 0 and not snapshot.empty:
    print("所有列名:")
    cols = list(snapshot.columns)
    for i, col in enumerate(cols[:50]):
        print(f"  {i+1:2d}. {col}")
    
    print(f"\n总列数: {len(cols)}")
    
    # 查找包含"change"的列
    print("\n包含'change'的列:")
    for col in cols:
        if 'change' in col.lower():
            print(f"  - {col}")
    
    # 打印这一行的数据
    print("\n数据样本:")
    row = snapshot.iloc[0]
    for col in cols[:25]:
        val = row[col]
        print(f"  {col}: {val}")

quote_ctx.close()