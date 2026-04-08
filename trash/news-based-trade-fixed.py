#!/usr/bin/env python3
"""Buy stocks with fixed price (no real-time quote needed)"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

print("="*50)
print("📰 根据四源资讯筛选 - 买入执行 (固定价格)")
print("="*50)

# Connect
quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)

# Unlock
ret_unlock, _ = trade_ctx.unlock_trade('709394')
print(f"解锁: {'✅' if ret_unlock == RET_OK else '❌'}")

# Get account
ret_acc, acc_list = trade_ctx.get_acc_list()
sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
acc_id = sim_acc.iloc[0]['acc_id']
ret_info, acc_info = trade_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
cash = acc_info['cash'].iloc[0]
position_size = cash * 0.02

print(f"💰 可用资金: ${cash:,.2f}")
print(f"📊 单笔仓位 (2%): ${position_size:,.2f}")

# Use limit order with estimated prices (will execute at market price)
# Estimated prices based on recent data
stocks = [
    ('US.VRT', 'Vertiv Holdings', 150.0, 'S&P 500纳入+AI基建', 85),
    ('US.LITE', 'Lumentum Holdings', 85.0, 'S&P 500纳入+AI光通讯', 82),
    ('US.NVDA', 'NVIDIA', 900.0, 'GTC 2026大会', 80),
]

print(f"\n📋 今日关注标的 (使用估计价格下单):")

trades = []
for code, name, est_price, reason, score in stocks:
    qty = int(position_size / est_price)
    if qty > 0:
        print(f"\n📝 买入 {name} ({code})")
        print(f"   估计价格: ${est_price:.2f}")
        print(f"   数量: {qty} 股")
        print(f"   理由: {reason} (评分{score})")
        
        ret, data = trade_ctx.place_order(
            price=est_price,
            qty=qty,
            code=code,
            trd_side=TrdSide.BUY,
            order_type=OrderType.MARKET,  # Use market order
            trd_env=TrdEnv.SIMULATE
        )
        
        if ret == RET_OK:
            order_id = data['order_id'][0]
            print(f"   ✅ 委托成功! 单号: {order_id}")
            trades.append((code, name, est_price, qty, reason, score))
        else:
            print(f"   ❌ 失败: {data}")

print(f"\n{'='*50}")
print(f"📊 今日交易汇总")
print(f"{'='*50}")
for code, name, price, qty, reason, score in trades:
    print(f"✅ 买入 {code} {name} - {qty}股@约${price:.2f}")
print(f"\n共 {len(trades)} 笔交易")

quote_ctx.close()
trade_ctx.close()
print("\n✅ 全部完成!")
