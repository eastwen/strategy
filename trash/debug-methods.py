#!/usr/bin/env python3
# Debug what methods are available on OpenSecTradeContext

from futu import *

quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host='127.0.0.1', port=11111)

try:
    ret_unlock, _ = trade_ctx.unlock_trade('709394')
    print(f"Unlock: {ret_unlock}")
    
    print("\n--- Looking for get_account methods ---\n")
    
    # List all methods that contain 'account' or 'info'
    for name in dir(trade_ctx):
        if 'account' in name.lower() or 'info' in name.lower():
            print(f"  {name}")
    
    # List all methods that contain 'position'
    print("\n--- Looking for position methods ---\n")
    for name in dir(trade_ctx):
        if 'position' in name.lower():
            print(f"  {name}")
            
finally:
    quote_ctx.close()
    trade_ctx.close()
