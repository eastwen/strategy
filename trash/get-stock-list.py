#!/usr/bin/env python3
"""
获取全市场股票列表 - 使用Futu OpenD
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext, KLType, AuType
import json
import time

def get_all_hk_stocks():
    """获取港股全市场股票列表"""
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    all_stocks = []
    
    try:
        print("获取港股全市场股票...")
        
        # 方法：通过获取板块成分股
        # HSI恒生指数成分股
        ret, data = quote_ctx.get_board('HK.800000')  # 恒生指数
        
        if ret == 0 and not data.empty:
            print(f"恒生指数成分股: {len(data)}只")
            for _, row in data.iterrows():
                code = row['code']
                name = row.get('name', code)
                all_stocks.append({'code': code, 'name': name})
        
        # 恒生科技指数成分股
        ret, data = quote_ctx.get_board('HK.800700')
        if ret == 0 and not data.empty:
            print(f"恒生科技成分股: {len(data)}只")
            for _, row in data.iterrows():
                code = row['code']
                if code not in [s['code'] for s in all_stocks]:
                    name = row.get('name', code)
                    all_stocks.append({'code': code, 'name': name})
        
        # 国企指数成分股
        ret, data = quote_ctx.get_board('HK.800100')
        if ret == 0 and not data.empty:
            print(f"国企指数成分股: {len(data)}只")
            for _, row in data.iterrows():
                code = row['code']
                if code not in [s['code'] for s in all_stocks]:
                    name = row.get('name', code)
                    all_stocks.append({'code': code, 'name': name})
        
        print(f"\n✅ 总计获取到 {len(all_stocks)} 只港股")
        
        # 保存到文件
        import os
        os.makedirs('/home/admin/.openclaw/workspace-arashi/data', exist_ok=True)
        
        with open('/home/admin/.openclaw/workspace-arashi/data/hk_stock_list.json', 'w', encoding='utf-8') as f:
            json.dump(all_stocks, f, indent=2, ensure_ascii=False)
        
        print(f"💾 已保存到 data/hk_stock_list.json")
        
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        quote_ctx.close()
    
    return all_stocks


if __name__ == '__main__':
    stocks = get_all_hk_stocks()
    
    if stocks:
        print(f"\n前20只股票:")
        for i, s in enumerate(stocks[:20], 1):
            print(f"  {i}. {s['code']} - {s['name']}")