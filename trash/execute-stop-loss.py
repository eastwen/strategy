#!/usr/bin/env python3
"""Execute stop loss for US.LITE"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

# Connect
trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)

# Unlock
ret_unlock, _ = trade_ctx.unlock_trade('709394')
print(f"🔑 解锁: {'✅ 成功' if ret_unlock == RET_OK else '❌ 失败'}")

# Get account
ret_acc, acc_list = trade_ctx.get_acc_list()
sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
acc_id = sim_acc.iloc[0]['acc_id']

# Get position for US.LITE
ret, positions = trade_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE, code='US.LITE')
if ret != RET_OK or len(positions) == 0:
    print("❌ 未找到US.LITE持仓")
    trade_ctx.close()
    sys.exit(1)

qty = positions.iloc[0]['qty']
print(f"📦 待卖出US.LITE持仓: {qty}股")

# Place sell order (market price)
ret, data = trade_ctx.place_order(
    price=0,
    qty=qty,
    code='US.LITE',
    trd_side=TrdSide.SELL,
    order_type=OrderType.MARKET,
    trd_env=TrdEnv.SIMULATE
)

if ret == RET_OK:
    order_id = data['order_id'][0]
    print(f"✅ 止损委托成功! 单号: {order_id}")
else:
    print(f"❌ 委托失败: {data}")

trade_ctx.close()
print("✅ 止损执行完成")
