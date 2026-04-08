#!/usr/bin/env python3
# tencent_strategy.py
# Example strategy: buy Tencent HK.00700
from futu import *

def sim_buy_tencent():
    # 1. 连接OpenD（后台已运行，直接连）
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    trade_ctx = OpenSecTradeContext(TrdMarket.HK, '127.0.0.1', 11111)

    try:
        # 2. 解锁模拟账户（密码已验证正确）- following your example
        ret_unlock, _ = trade_ctx.unlock_trade('709394')
        if ret_unlock != RET_OK:
            print(f"❌ 账户解锁失败: {_}")
            return

        print("✅ 模拟账户解锁成功！")

        # 4. 获取账户列表 - correct method name is get_acc_list
        ret_acc, acc_list = trade_ctx.get_acc_list()
        if ret_acc == RET_OK and len(acc_list) > 0:
            print("\n📊 账户列表:")
            print(acc_list.to_string(index=False))
            
            print(f"\n✅ 找到 {len(acc_list)} 个账户!")

            # 尝试获取持仓
            try:
                ret_pos, positions = trade_ctx.get_position_list()
                if ret_pos == RET_OK:
                    print(f"\n📋 当前持仓: {len(positions)} 个持仓")
                    if len(positions) > 0:
                        print(positions[['code', 'qty', 'cost_price', 'pnl']].to_string(index=False))
            except Exception as e:
                print(f"\n⚠️ 获取持仓失败: {e}")

    finally:
        quote_ctx.close()
        trade_ctx.close()

if __name__ == "__main__":
    sim_buy_tencent()
