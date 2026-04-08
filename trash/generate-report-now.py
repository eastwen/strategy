#!/usr/bin/env python3
"""
手动生成并发送日报
"""

import sys
import json
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)

print("=" * 60)
print("🇭🇰 港股日报 - 2026-03-23")
print("=" * 60)

# 1. 指数
indices = [
    ('HK.800000', '恒生指数'),
    ('HK.800100', '国企指数'),
    ('HK.800700', '恒生科技'),
]

print("\n## 📈 一、主要指数")
print("| 指数 | 价格 | 涨跌 |")
print("|------|------|------|")
for code, name in indices:
    ret, data = quote_ctx.get_market_snapshot([code])
    if ret == 0 and not data.empty:
        row = data.iloc[0]
        price = row['last_price']
        prev = row['prev_close_price']
        change = (price - prev) / prev * 100 if prev > 0 else 0
        print(f"| {name} | {price:,.2f} | {change:+.2f}% |")

# 2. 推荐股票
stocks = [
    ('HK.00700', '腾讯控股'),
    ('HK.09988', '阿里巴巴-W'),
    ('HK.03690', '美团-W'),
    ('HK.02331', '李宁'),
    ('HK.02020', '安踏体育'),
    ('HK.09868', '小鹏汽车-W'),
    ('HK.09866', '蔚来-SW'),
    ('HK.02333', '比亚迪股份'),
]

print("\n## 📊 二、推荐股票动态")
print("| 股票 | 价格 | 涨跌 | 评分 |")
print("|------|------|------|------|")
for code, name in stocks:
    ret, data = quote_ctx.get_market_snapshot([code])
    if ret == 0 and not data.empty:
        row = data.iloc[0]
        price = row['last_price']
        prev = row['prev_close_price']
        change = (price - prev) / prev * 100 if prev > 0 else 0
        score = 60 + (20 if change > 2 else 10 if change > 1 else -20 if change < -2 else 0)
        print(f"| {name} | {price:.2f} | {change:+.2f}% | {score} |")

# 3. VHSI
print("\n## 📉 三、市场情绪")
ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
if ret == 0 and not data.empty:
    vhsi = data.iloc[0]['last_price']
    print(f"- VHSI恒指波幅: {vhsi:.2f}")
    if vhsi >= 30:
        print("  状态: ⚠️ 极度恐慌")
    elif vhsi >= 25:
        print("  状态: 😰 恐慌")
    elif vhsi >= 20:
        print("  状态: 😐 正常")
    else:
        print("  状态: 😌 平静")

# 4. 美股自动交易状态
print("\n## 🤖 四、美股自动交易状态")
try:
    with open('data/trades.json', 'r') as f:
        trades = json.load(f)
        last_trade = trades.get('trades', [])[-1] if trades.get('trades') else None
        if last_trade:
            print(f"- 最后交易: {last_trade['action']} {last_trade['symbol']} @${last_trade['price']:.2f}")
except:
    print("- 暂无交易记录")

print("\n## 💡 五、今日总结")
print("- 港股普遍下跌，恒指跌3.54%")
print("- 科技股领跌，美团、阿里跌幅较大")
print("- 市场情绪恐慌（VHSI接近30）")
print("- 暂无买入机会，等待市场回暖")
print("- 美股自动交易机器人运行中")

print("\n---")
print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"下次自动生成: 明天16:10")

quote_ctx.close()
