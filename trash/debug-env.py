#!/usr/bin/env python3
# Debug the trd_env values

from futu import *

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
trade_ctx = OpenSecTradeContext(TrdMarket.HK, '127.0.0.1', 11111)

try:
    ret_unlock, _ = trade_ctx.unlock_trade('709394')
    print(f"Unlock: {ret_unlock}")
    
    ret_acc, acc_list = trade_ctx.get_acc_list()
    print(f"\nAccounts found: {len(acc_list)}")
    
    print("\nDebug each row:")
    for idx, row in acc_list.iterrows():
        print(f"\nAccount {idx}: acc_id={row['acc_id']}, trd_env={row['trd_env']}, acc_type={row['acc_type']}")
        print(f"  trd_env is {type(row['trd_env'])} = {row['trd_env']}")
        
finally:
    quote_ctx.close()
    trade_ctx.close()
