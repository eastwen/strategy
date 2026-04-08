#!/usr/bin/env python3
from futu import *

trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)
ret_unlock, _ = trade_ctx.unlock_trade('709394')
print(f"解锁: {'✅' if ret_unlock == RET_OK else '❌'}")

ret_acc, acc_list = trade_ctx.get_acc_list()
sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
acc_id = sim_acc.iloc[0]['acc_id']
ret_info, acc_info = trade_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)

print("账户信息字段:", list(acc_info.columns))
print("账户信息内容:", acc_info)

trade_ctx.close()
