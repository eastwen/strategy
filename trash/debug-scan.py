#!/usr/bin/env python3
"""调试扫描问题"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)

test_codes = ['HK.00001', 'HK.00700', 'HK.02331']

print("测试代码:", test_codes)

results = []

for code in test_codes:
    print(f"\n测试: {code}")
    ret, snapshot = quote_ctx.get_market_snapshot([code])
    
    if ret == 0 and not snapshot.empty:
        print("成功获取数据")
        
        row = snapshot.iloc[0]
        
        print("last_price:", row['last_price'], type(row['last_price']))
        print("change_rate:", row['change_rate'], type(row['change_rate']))
        
        # 尝试获取
        price = row['last_price']
        change_rate = row['change_rate']
        
        # 检查是否有效
        if price is None:
            print("price is None!")
        elif price == 'N/A':
            print("price is 'N/A'!")
        
        if change_rate is None:
            print("change_rate is None!")
        elif change_rate == 'N/A':
            print("change_rate is 'N/A'!")
        
        # 处理
        if price not in (None, 'N/A'):
            price_float = float(price)
            print("price_float:", price_float)
            
            change_pct = 0.0
            if change_rate not in (None, 'N/A'):
                change_pct = float(change_rate)
            print("change_pct:", change_pct)
            
            results.append({
                'code': code,
                'name': row['name'],
                'price': price_float,
                'change_pct': change_pct,
            })

print("\n结果:", results)
print(f"成功获取: {len(results)}只")

quote_ctx.close()