#!/usr/bin/env python3
"""
模拟盘交易执行系统 v1.0
连接Futu模拟盘，执行买卖操作
"""

import sys
import json
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

from futu import OpenQuoteContext, OpenHKTradeContext, OrderType, TrdSide, RET_OK, TrdEnv

class TradingExecutor:
    """交易执行器"""
    
    def __init__(self):
        self.host = '127.0.0.1'
        self.port = 11111
        
        # 账户配置
        self.cash_account = 15270899    # 模拟盘-现金
        self.margin_account = 15270902  # 模拟盘-融资
        
        # 风险控制
        self.max_positions = 15         # 最多持仓数
        self.max_single_position = 0.1  # 单只股票最大仓位10%
        self.stop_loss = -0.06          # 止损线-6%
        self.min_score = 65             # 最低评分
        
        # 连接
        self.quote_ctx = None
        self.trade_ctx = None
        
    def connect(self):
        """连接Futu OpenD"""
        print("="*60)
        print("🔌 连接Futu OpenD...")
        print("="*60)
        
        try:
            # 行情连接
            self.quote_ctx = OpenQuoteContext(self.host, self.port)
            print("✅ 行情连接成功")
            
            # 交易连接
            self.trade_ctx = OpenHKTradeContext(self.host, self.port)
            # 模拟盘通常不需要解锁密码，或者使用不同的方法
            print("✅ 交易连接成功")
            return True
                
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def get_account_info(self):
        """获取账户信息"""
        print("\n" + "="*60)
        print("📊 账户信息")
        print("="*60)
        
        # 获取账户列表
        ret, data = self.trade_ctx.get_acc_list()
        if ret == RET_OK:
            print(f"可用账户:")
            for _, row in data.iterrows():
                print(f"  - 账户ID: {row['acc_id']}, 类型: {row['trd_env']}")
        
        # 获取现金账户余额
        ret, data = self.trade_ctx.accinfo_query(trd_env=TrdEnv.SIMULATE, acc_id=self.cash_account)
        if ret == RET_OK:
            print(f"\n现金账户 ({self.cash_account}):")
            for _, row in data.iterrows():
                print(f"  总资产: {row['total_assets']:,.2f}")
                print(f"  现金: {row['cash']:,.2f}")
                print(f"  市值: {row['market_val']:,.2f}")
        
        return data
    
    def get_positions(self):
        """获取当前持仓"""
        print("\n" + "="*60)
        print("📈 当前持仓")
        print("="*60)
        
        ret, data = self.trade_ctx.position_list_query(trd_env=TrdEnv.SIMULATE, acc_id=self.cash_account)
        
        if ret == RET_OK and not data.empty:
            positions = []
            print(f"\n持仓数量: {len(data)}只")
            print(f"{'代码':<12} {'名称':<10} {'数量':<8} {'成本':<10} {'现价':<10} {'盈亏':<10}")
            print("-" * 60)
            
            for _, row in data.iterrows():
                code = row['code']
                name = row.get('stock_name', '')
                qty = row['qty']
                cost = row['cost_price']
                price = row.get('market_price', cost)
                profit = (price - cost) / cost * 100 if cost > 0 else 0
                
                print(f"{code:<12} {name:<10} {qty:<8} {cost:<10.2f} {price:<10.2f} {profit:>+.2f}%")
                
                positions.append({
                    'code': code,
                    'name': name,
                    'qty': qty,
                    'cost': cost,
                    'price': price,
                    'profit': profit
                })
            
            return positions
        else:
            print("暂无持仓")
            return []
    
    def buy(self, code, quantity, price=None):
        """买入股票"""
        print(f"\n" + "="*60)
        print(f"💰 买入: {code}")
        print("="*60)
        
        try:
            # 获取当前价格
            if price is None:
                ret, data = self.quote_ctx.get_market_snapshot([code])
                if ret == RET_OK and not data.empty:
                    price = data.iloc[0]['last_price']
                else:
                    print(f"❌ 无法获取价格")
                    return False
            
            print(f"代码: {code}")
            print(f"数量: {quantity}股")
            print(f"价格: {price}")
            print(f"金额: {quantity * price:,.2f}")
            
            # 下单
            ret, data = self.trade_ctx.place_order(
                price=price,
                qty=quantity,
                code=code,
                trd_side=TrdSide.BUY,
                order_type=OrderType.NORMAL,
                trd_env=TrdEnv.SIMULATE,
                acc_id=self.cash_account
            )
            
            if ret == RET_OK:
                print(f"✅ 下单成功")
                print(f"订单ID: {data.iloc[0]['order_id']}")
                return True
            else:
                print(f"❌ 下单失败: {data}")
                return False
                
        except Exception as e:
            print(f"❌ 交易失败: {e}")
            return False
    
    def sell(self, code, quantity, price=None):
        """卖出股票"""
        print(f"\n" + "="*60)
        print(f"📤 卖出: {code}")
        print("="*60)
        
        try:
            # 获取当前价格
            if price is None:
                ret, data = self.quote_ctx.get_market_snapshot([code])
                if ret == RET_OK and not data.empty:
                    price = data.iloc[0]['last_price']
                else:
                    print(f"❌ 无法获取价格")
                    return False
            
            print(f"代码: {code}")
            print(f"数量: {quantity}股")
            print(f"价格: {price}")
            print(f"金额: {quantity * price:,.2f}")
            
            # 下单
            ret, data = self.trade_ctx.place_order(
                price=price,
                qty=quantity,
                code=code,
                trd_side=TrdSide.SELL,
                order_type=OrderType.NORMAL,
                trd_env=TrdEnv.SIMULATE,
                acc_id=self.cash_account
            )
            
            if ret == RET_OK:
                print(f"✅ 下单成功")
                print(f"订单ID: {data.iloc[0]['order_id']}")
                return True
            else:
                print(f"❌ 下单失败: {data}")
                return False
                
        except Exception as e:
            print(f"❌ 交易失败: {e}")
            return False
    
    def check_stop_loss(self):
        """检查止损"""
        print("\n" + "="*60)
        print("🔍 检查止损")
        print("="*60)
        
        positions = self.get_positions()
        
        for pos in positions:
            if pos['profit'] < self.stop_loss * 100:
                print(f"\n⚠️ 触发止损: {pos['code']} ({pos['profit']:.2f}%)")
                self.sell(pos['code'], pos['qty'])
    
    def execute_signals(self, signals):
        """执行交易信号"""
        print("\n" + "="*60)
        print("🎯 执行交易信号")
        print("="*60)
        
        for signal in signals:
            action = signal.get('action')
            code = signal.get('code')
            score = signal.get('score', 0)
            
            if action == 'buy' and score >= self.min_score:
                # 买入信号
                print(f"\n买入信号: {code} (评分: {score})")
                # 计算买入数量（简化，实际需要更复杂的资金管理）
                # self.buy(code, 1000)
                
            elif action == 'sell':
                # 卖出信号
                print(f"\n卖出信号: {code}")
                # self.sell(code, signal.get('qty', 1000))
    
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
        print("\n✅ 连接已关闭")


# 测试
if __name__ == '__main__':
    print('\n' + '='*60)
    print('🚀 模拟盘交易执行系统 v1.0')
    print('='*60)
    
    executor = TradingExecutor()
    
    try:
        # 连接
        if executor.connect():
            # 获取账户信息
            executor.get_account_info()
            
            # 获取持仓
            executor.get_positions()
            
            # 检查止损
            executor.check_stop_loss()
        
    except Exception as e:
        print(f"\n❌ 系统错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        executor.close()