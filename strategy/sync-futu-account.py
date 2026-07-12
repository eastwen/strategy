#!/usr/bin/env python3
"""
富途模拟账户数据同步脚本
- 从富途OpenD获取真实账户和持仓数据
- 同步到 trades.json 供日报和其他脚本使用
"""

import sys
import json
import os
from datetime import datetime

from runtime_config import DATA_DIR, FUTU_HOST, FUTU_PORT, load_api_keys
from futu import OpenQuoteContext, OpenSecTradeContext, TrdEnv, TrdMarket, SecurityFirm, RET_OK

def safe_float(val, default=0.0):
    """安全转换浮点数"""
    if val == 'N/A' or val is None:
        return default
    try:
        return float(val)
    except:
        return default

def query_account(trade_ctx, acc_id, acc_type):
    """查询单个账户信息和持仓"""
    accounts = []
    positions = []

    # 查询账户信息
    ret_info, acc_info = trade_ctx.accinfo_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
    if ret_info == RET_OK and len(acc_info) > 0:
        info = acc_info.iloc[0]
        accounts.append({
            'acc_id': int(acc_id),
            'acc_type': acc_type,
            'total_assets': safe_float(info.get('total_assets', 0)),
            'cash': safe_float(info.get('cash', 0)),
            'market_val': safe_float(info.get('market_val', 0)),
            'securities_assets': safe_float(info.get('securities_assets', 0))
        })

    # 查询持仓
    ret_pos, pos_list = trade_ctx.position_list_query(acc_id=acc_id, trd_env=TrdEnv.SIMULATE)
    if ret_pos == RET_OK and len(pos_list) > 0:
        for _, pos in pos_list.iterrows():
            qty = int(pos['qty'])
            if qty > 0:
                cost = safe_float(pos['cost_price'])
                market = safe_float(pos.get('market_val', 0))
                # 富途 SDK 的 pl_ratio 已是百分比数值，如 -0.57 表示 -0.57%。
                # 仅在该字段缺失时才用盈亏金额反推，并同样转换为百分比。
                raw_pl_ratio = pos.get('pl_ratio')
                if raw_pl_ratio is None:
                    total_cost = cost * qty
                    pl_val = safe_float(pos.get('pl_val', 0))
                    pl_ratio_pct = (pl_val / total_cost * 100) if total_cost > 0 else 0
                else:
                    pl_ratio_pct = safe_float(raw_pl_ratio)

                positions.append({
                    'acc_id': int(acc_id),
                    'symbol': pos['code'],
                    'shares': qty,
                    'cost_price': cost,
                    'market_val': market,
                    'pl_ratio': pl_ratio_pct
                })

    return accounts, positions

def sync_futu_account():
    """同步富途模拟账户数据（美股+港股）"""
    quote_ctx = OpenQuoteContext(FUTU_HOST, FUTU_PORT)

    account_data = {
        'source': 'futu_simulate',
        'sync_time': datetime.now().isoformat(),
        'accounts': [],
        'positions': [],
        'trades': []
    }

    try:
        # ========== 美股账户 ==========
        trade_ctx_us = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=FUTU_HOST, port=FUTU_PORT,
                                           security_firm=SecurityFirm.FUTUSECURITIES)
        trade_password = os.getenv('FUTU_TRADE_PASSWORD') or load_api_keys().get('futu', {}).get('trade_password', '')
        ret_unlock, _ = trade_ctx_us.unlock_trade(trade_password)
        if ret_unlock != RET_OK:
            print("❌ 美股解锁失败")
        else:
            ret_acc, acc_list = trade_ctx_us.get_acc_list()
            if ret_acc == RET_OK:
                sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
                for _, acc_row in sim_acc.iterrows():
                    acc_id = acc_row['acc_id']
                    acc_type = acc_row['acc_type']
                    accs, poss = query_account(trade_ctx_us, acc_id, acc_type)
                    account_data['accounts'].extend(accs)
                    account_data['positions'].extend(poss)
                    print(f"   US账户 {acc_id}: {len(accs)}账户, {len(poss)}持仓")
            else:
                print(f"❌ 获取美股账户列表失败: {acc_list}")
        trade_ctx_us.close()

        # ========== 港股账户 ==========
        # 2026-06-26 east: futu-api 10.8+ 弃用了 OpenHKTradeContext，统一用 OpenSecTradeContext + filter_trdmarket=TrdMarket.HK
        trade_ctx_hk = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host=FUTU_HOST, port=FUTU_PORT,
                                            security_firm=SecurityFirm.FUTUSECURITIES)
        # 港股可能不需要解锁，或者解锁密码不同，先尝试不解锁直接查询
        ret_unlock = RET_OK
        if ret_unlock == RET_OK:
            ret_acc, acc_list = trade_ctx_hk.get_acc_list()
            if ret_acc == RET_OK:
                sim_acc = acc_list[acc_list['trd_env'] == 'SIMULATE']
                # 只同步 HK 15270899，忽略 15270902
                for _, acc_row in sim_acc.iterrows():
                    acc_id = acc_row['acc_id']
                    if acc_id == 15270902:
                        print(f"   跳过HK账户 {acc_id} (不使用)")
                        continue
                    acc_type = acc_row['acc_type']
                    accs, poss = query_account(trade_ctx_hk, acc_id, acc_type)
                    account_data['accounts'].extend(accs)
                    account_data['positions'].extend(poss)
                    print(f"   HK账户 {acc_id}: {len(accs)}账户, {len(poss)}持仓")
            else:
                print(f"❌ 获取港股账户列表失败: {acc_list}")
        trade_ctx_hk.close()

        # 保存数据
        trades_path = DATA_DIR / 'trades.json'
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        with open(trades_path, 'w') as f:
            json.dump(account_data, f, indent=2, ensure_ascii=False)

        print("\n✅ 同步完成!")
        print(f"   账户数: {len(account_data['accounts'])}")
        print(f"   持仓数: {len(account_data['positions'])}")

        for acc in account_data['accounts']:
            status = "有持仓" if acc['market_val'] > 0 else "空仓"
            print(f"   账户 {acc['acc_id']}: ${acc['total_assets']:,.2f} ({status})")

        return True

    except Exception as e:
        print(f"❌ 同步失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        quote_ctx.close()

if __name__ == '__main__':
    sync_futu_account()
