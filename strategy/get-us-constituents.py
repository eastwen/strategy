#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
美股成分股列表
标普500 (505只) + 纳斯达克100 (103只)
"""

import requests
import json

def get_sp500_constituents():
    """从Wikipedia获取标普500成分股"""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        # 使用pandas读取HTML表格
        import pandas as pd
        tables = pd.read_html(url)
        df = tables[0]
        symbols = df['Symbol'].tolist()
        # 处理特殊情况（如BRK.B -> BRK-B）
        symbols = [s.replace('.', '-') for s in symbols]
        return symbols
    except Exception as e:
        print(f"获取标普500失败: {e}")
        return []

def get_nasdaq100_constituents():
    """获取纳斯达克100成分股"""
    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        import pandas as pd
        tables = pd.read_html(url)
        # 找到成分股表格
        for table in tables:
            if 'Ticker' in table.columns or 'Symbol' in table.columns:
                col = 'Ticker' if 'Ticker' in table.columns else 'Symbol'
                symbols = table[col].tolist()
                symbols = [s.replace('.', '-') for s in symbols if isinstance(s, str)]
                return symbols
        return []
    except Exception as e:
        print(f"获取纳斯达克100失败: {e}")
        return []

def main():
    print("="*60)
    print("获取美股成分股列表")
    print("="*60)
    
    # 标普500
    sp500 = get_sp500_constituents()
    print(f"✅ 标普500: {len(sp500)}只")
    
    # 纳斯达克100
    nasdaq100 = get_nasdaq100_constituents()
    print(f"✅ 纳斯达克100: {len(nasdaq100)}只")
    
    # 合并去重
    all_symbols = list(set(sp500 + nasdaq100))
    print(f"✅ 合并去重: {len(all_symbols)}只")
    
    # 保存
    data = {
        'sp500': sp500,
        'nasdaq100': nasdaq100,
        'all': all_symbols
    }
    
    with open('/home/admin/.openclaw/workspace-stock/data/us-index-constituents.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ 已保存到: data/us-index-constituents.json")
    
    # 打印前10只
    print("\n前10只股票:")
    for s in all_symbols[:10]:
        print(f"  {s}")

if __name__ == '__main__':
    main()
