#!/usr/bin/env python3
# Debug accinfo_query response

from futu import *

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host='127.0.0.1', port=11111)

try:
    ret_unlock, _ = trade_ctx.unlock_trade('709394')
    print(f"Unlock: {ret_unlock}")
    
    ret_info, acc_info = trade_ctx.accinfo_query(acc_id=15270899, trd_env=TrdEnv.SIMULATE)
    print(f"\naccinfo_query ret={ret_info}")
    if ret_info == RET_OK:
        print(f"\nColumns found: {list(acc_info.columns)}")
        print(f"\nFull data:")
        print(acc_info.to_string())
        
finally:
    quote_ctx.close()
    trade_ctx.close()
