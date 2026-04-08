#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
获取指数成分股列表
使用富途API获取恒生指数、恒生科技指数成分股
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext, RET_OK

def get_index_constituents(index_code, index_name):
    """获取指数成分股"""
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        # 获取指数成分股
        ret, data = quote_ctx.get_plate_stock(index_code)
        
        if ret == RET_OK:
            stocks = []
            for _, row in data.iterrows():
                stocks.append({
                    'code': row['code'],
                    'name': row['stock_name']
                })
            print(f"✅ {index_name}: {len(stocks)}只")
            return stocks
        else:
            print(f"❌ 获取{index_name}失败: {data}")
            return []
    finally:
        quote_ctx.close()

def main():
    print("="*60)
    print("获取指数成分股列表")
    print("="*60)
    
    # 恒生指数
    hsi_stocks = get_index_constituents('HK.800000', '恒生指数')
    
    # 恒生科技指数
    hstech_stocks = get_index_constituents('HK.800700', '恒生科技指数')
    
    # 合并去重
    all_codes = set()
    all_stocks = []
    
    for s in hsi_stocks + hstech_stocks:
        if s['code'] not in all_codes:
            all_codes.add(s['code'])
            all_stocks.append(s)
    
    print(f"\n合并去重后: {len(all_stocks)}只")
    
    # 保存到文件
    import json
    data = {
        'hsi': hsi_stocks,
        'hstech': hstech_stocks,
        'all': all_stocks
    }
    
    with open('/home/admin/.openclaw/workspace-stock/data/hk-index-constituents.json', 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 已保存到: data/hk-index-constituents.json")
    
    # 打印前10只
    print("\n前10只股票:")
    for s in all_stocks[:10]:
        print(f"  {s['code']}: {s['name']}")

if __name__ == '__main__':
    main()
