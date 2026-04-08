#!/usr/bin/env python3
"""
Futu OpenD Simulated Trading Demo
Try login password as trading password
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *

def sim_trade_demo():
    # 1. Connect
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    # For Hong Kong market
    trade_ctx = OpenSecTradeContext(TrdMarket.HK, '127.0.0.1', 11111)
    
    try:
        # Try login password as trading password
        ret, data = trade_ctx.unlock_trade('qq392084795', TrdEnv.SIMULATE)
        
        if ret != RET_OK:
            print(f"❌ 解锁账户失败：{data}")
            return
        
        print("✅ 解锁模拟交易成功!")
        
        # Query account list
        ret, data = trade_ctx.get_acc_list()
        if ret == RET_OK:
            print(f"\n📊 找到 {len(data)} 个账户：")
            if not data.empty:
                print(data.to_string())
            else:
                print("⚠️  仍然没有找到账户\n👉 需要你先在富途牛牛App开通模拟交易：个人中心 → 模拟交易 → 申请开通")
        
        # Get account info
        ret, acc_info = trade_ctx.get_account_info()
        if ret == RET_OK:
            print("\n💰 账户详细信息：")
            print(f"  账户ID: {acc_info['acc_id']}")
            print(f"  总资产: {acc_info['total_asset']:.2f}")
            print(f"  可用资金: {acc_info['available_funds']:.2f}")
            print(f"  市值: {acc_info['market_val']:.2f}")
            print(f"  累计盈亏: {acc_info['total_pnl']:.2f}")
            print(f"  今日盈亏: {acc_info['daily_pnl']:.2f}")
        
        # Get positions
        ret, positions = trade_ctx.get_position_list()
        if ret == RET_OK:
            print(f"\n📋 当前持仓: {len(positions)} 个")
            if len(positions) > 0:
                print(positions.to_string())
        
    finally:
        quote_ctx.close()
        trade_ctx.close()
    
    print("\n✅ Done!")

if __name__ == "__main__":
    sim_trade_demo()
