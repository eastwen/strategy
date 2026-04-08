#!/usr/bin/env python3
"""
自动止损止盈执行器
支持：止损、止盈、情绪联动
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3*/site-packages')
from futu import *
import requests
import json

class StopLossExecutor:
    """自动止损止盈执行器"""
    
    def __init__(self):
        self.quote_ctx = None
        self.trade_ctx = None
        self.acc_id = None
        self.feishu_token = None
        
        # 风控参数
        self.stop_loss_threshold = -0.06  # -6%
        self.take_profit_1 = 0.15  # 15%减半
        self.take_profit_2 = 0.25  # 25%全出
        
        # 情绪联动参数
        self.vix = None
        self.vhsi = None
        
    def connect(self):
        """连接交易接口"""
        try:
            self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            self.trade_ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host='127.0.0.1', port=11111)
            
            # 解锁
            ret, _ = self.trade_ctx.unlock_trade('709394')
            if ret != RET_OK:
                print("❌ 解锁失败")
                return False
            
            # 获取账户
            ret, acc_list = self.trade_ctx.get_acc_list()
            if ret == RET_OK and not acc_list.empty:
                self.acc_id = acc_list.iloc[0]['acc_id']
                print(f"✅ 连接成功，账户: {self.acc_id}")
                return True
            return False
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
    
    def get_feishu_token(self):
        """获取飞书token"""
        try:
            res = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": "cli_a93b169884f8dcc1", "app_secret": "9b8a6LP4Tki2ghq9muMcqdCg6m0bv5cV"},
                timeout=10
            )
            self.feishu_token = res.json()["tenant_access_token"]
            return self.feishu_token
        except Exception as e:
            print(f"⚠️ 获取飞书token失败: {e}")
            return None
    
    def send_feishu_msg(self, msg):
        """发送飞书消息"""
        if not self.feishu_token:
            self.get_feishu_token()
        
        if self.feishu_token:
            try:
                requests.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                    headers={"Authorization": f"Bearer {self.feishu_token}", "Content-Type": "application/json"},
                    json={
                        "receive_id": "ou_571e965fc81a2e887609a06ed6103d66",
                        "msg_type": "text",
                        "content": '{"text": "' + msg.replace("\n", "\\n").replace('"', '\\"') + '"}'
                    },
                    timeout=10
                )
            except Exception as e:
                print(f"⚠️ 发送飞书消息失败: {e}")
    
    def get_sentiment(self):
        """获取市场情绪（VIX/VHSI）"""
        try:
            # 获取VIX
            ret, data = self.quote_ctx.get_market_snapshot(['US.VIX'])
            if ret == RET_OK and not data.empty:
                self.vix = float(data.iloc[0]['last_price']) if data.iloc[0]['last_price'] != 'N/A' else None
            
            # 获取VHSI
            ret, data = self.quote_ctx.get_market_snapshot(['HK.800125'])
            if ret == RET_OK and not data.empty:
                self.vhsi = float(data.iloc[0]['last_price']) if data.iloc[0]['last_price'] != 'N/A' else None
            
            print(f"📊 情绪指标: VIX={self.vix or 'N/A'}, VHSI={self.vhsi or 'N/A'}")
        except Exception as e:
            print(f"⚠️ 获取情绪指标失败: {e}")
    
    def adjust_threshold_by_sentiment(self):
        """根据情绪指标调整止损止盈阈值"""
        # 默认阈值
        adjusted_stop_loss = self.stop_loss_threshold
        
        # VIX联动：恐慌时收紧止损
        if self.vix:
            if self.vix >= 40:
                adjusted_stop_loss = -0.04  # 极端恐慌，止损收紧到-4%
                print("⚠️ VIX≥40，极端恐慌，止损收紧到-4%")
            elif self.vix >= 30:
                adjusted_stop_loss = -0.05  # 恐慌，止损收紧到-5%
                print("⚠️ VIX≥30，恐慌，止损收紧到-5%")
        
        # VHSI联动
        if self.vhsi:
            if self.vhsi >= 40:
                adjusted_stop_loss = max(adjusted_stop_loss, -0.04)
            elif self.vhsi >= 30:
                adjusted_stop_loss = max(adjusted_stop_loss, -0.05)
        
        return adjusted_stop_loss
    
    def execute_stop_loss_take_profit(self):
        """执行止损止盈检查"""
        print("\n" + "="*50)
        print("🛡️  自动止损止盈检查")
        print("="*50)
        
        # 获取情绪指标
        self.get_sentiment()
        adjusted_stop_loss = self.adjust_threshold_by_sentiment()
        print(f"📋 调整后止损线: {adjusted_stop_loss*100:.1f}%")
        
        # 获取持仓
        ret, positions = self.trade_ctx.position_list_query(acc_id=self.acc_id, trd_env=TrdEnv.SIMULATE)
        if ret != RET_OK:
            print(f"❌ 获取持仓失败: {positions}")
            return
        
        if positions.empty:
            print("✅ 当前无持仓")
            return
        
        actions = []
        
        for _, pos in positions.iterrows():
            code = pos['code']
            name = pos['stock_name']
            qty = int(pos['qty'])
            can_sell = int(pos['can_sell_qty']) if pos['can_sell_qty'] != 'N/A' else qty
            pl_ratio = float(pos['pl_ratio']) if pos['pl_ratio'] != 'N/A' else 0
            pl_val = float(pos['pl_val']) if pos['pl_val'] != 'N/A' else 0
            
            action = None
            
            # 止损检查
            if pl_ratio <= adjusted_stop_loss * 100:
                action = "stop_loss"
                reason = f"触发止损线（{pl_ratio:.2f}% ≤ {adjusted_stop_loss*100:.1f}%）"
            
            # 止盈检查
            elif pl_ratio >= self.take_profit_2 * 100:
                action = "take_profit_all"
                reason = f"触发止盈2（{pl_ratio:.2f}% ≥ {self.take_profit_2*100:.0f}%）"
            elif pl_ratio >= self.take_profit_1 * 100:
                action = "take_profit_half"
                reason = f"触发止盈1（{pl_ratio:.2f}% ≥ {self.take_profit_1*100:.0f}%）"
            
            if action and can_sell > 0:
                sell_qty = qty if action in ["stop_loss", "take_profit_all"] else qty // 2
                sell_qty = min(sell_qty, can_sell)
                
                print(f"\n⚠️ {code} {name}: {reason}")
                print(f"   执行: {'止损' if action == 'stop_loss' else '止盈'} 卖出 {sell_qty} 股")
                
                # 执行卖出
                ret, data = self.trade_ctx.place_order(
                    price=0,
                    qty=sell_qty,
                    code=code,
                    trd_side=TrdSide.SELL,
                    order_type=OrderType.MARKET,
                    trd_env=TrdEnv.SIMULATE
                )
                
                if ret == RET_OK:
                    order_id = data['order_id'][0]
                    print(f"   ✅ 委托成功! 单号: {order_id}")
                    actions.append({
                        "code": code,
                        "name": name,
                        "action": action,
                        "qty": sell_qty,
                        "pl_ratio": pl_ratio,
                        "order_id": order_id
                    })
                else:
                    print(f"   ❌ 委托失败: {data}")
        
        # 发送汇总通知
        if actions:
            msg = f"""🛡️ 止损止盈执行汇总

执行时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
VIX: {self.vix or 'N/A'} | VHSI: {self.vhsi or 'N/A'}
调整后止损线: {adjusted_stop_loss*100:.1f}%

执行明细:
"""
            for a in actions:
                action_name = "止损" if a['action'] == "stop_loss" else "止盈"
                msg += f"• {a['code']} {a['name']}: {action_name} {a['qty']}股 ({a['pl_ratio']:.2f}%)\n"
            
            self.send_feishu_msg(msg)
        else:
            print("\n✅ 所有持仓未触发止损止盈条件")
        
        return actions


if __name__ == "__main__":
    executor = StopLossExecutor()
    if executor.connect():
        executor.execute_stop_loss_take_profit()
        executor.close()
