#!/usr/bin/env python3
"""Test trade - buy a small position"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

print("="*50)
print("🧪 OpenClaw 测试交易")
print("="*50)

# Connect
quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)

# Unlock
ret_unlock, _ = trade_ctx.unlock_trade('709394')
if ret_unlock != RET_OK:
    print(f"❌ 解锁失败")
    sys.exit(1)

print("✅ 解锁成功")

# Get account
ret_acc, acc_list = trade_ctx.get_acc_list()
sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
acc_id = sim_acc.iloc[0]['acc_id']

# Get cash
ret_info, acc_info = trade_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
cash = acc_info['cash'].iloc[0]
print(f"💰 可用资金: ${cash:,.2f}")

# Calculate position: 2% = $20,000
position_size = cash * 0.02
print(f"📊 测试仓位 (2%): ${position_size:,.2f}")

# Test buy 1 share of NVDA at market price ~$900 (just for test)
# This is just to verify the system works
test_code = 'US.NVDA'
test_price = 900.0  # approximate
test_qty = 1

print(f"\n📝 尝试买入测试:")
print(f"  标的: {test_code}")
print(f"  价格: ${test_price}")
print(f"  数量: {test_qty} 股")

# Place order
ret, data = trade_ctx.place_order(
    price=test_price,
    qty=test_qty,
    code=test_code,
    trd_side=TrdSide.BUY,
    order_type=OrderType.NORMAL,
    trd_env=TrdEnv.SIMULATE
)

print(f"\n📋 下单结果: ret={ret}")
if ret == RET_OK:
    order_id = data['order_id'][0]
    print(f"✅ 测试成功! 委托单号: {order_id}")
    print(f"\n🧪 系统测试通过，可以开始实盘模拟交易!")
else:
    print(f"❌ 下单失败: {data}")

quote_ctx.close()
trade_ctx.close()
print("\n✅ 测试完成!")
