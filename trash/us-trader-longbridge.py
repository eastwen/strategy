#!/usr/bin/env python3
"""
美股交易执行模块 - 长桥API
支持买入/卖出/查询持仓/查询订单
"""

import sys
import json
import requests
import time
from datetime import datetime, timedelta

class LongbridgeTrader:
    """长桥美股交易执行器"""
    
    def __init__(self):
        self.load_config()
        self.base_url = "https://openapi.longbridge.sg"
        self.account_id = None
        
    def load_config(self):
        """加载API配置"""
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        self.token = keys['longbridge']['token']
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
    
    def get_account_info(self):
        """获取账户信息"""
        url = f"{self.base_url}/v1/account"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    self.account_id = data['data']['list'][0]['account_id']
                    print(f"✅ 账户连接成功: {self.account_id}")
                    return True
            print(f"❌ 获取账户失败: {res.text}")
            return False
        except Exception as e:
            print(f"❌ 连接异常: {e}")
            return False
    
    def get_positions(self):
        """获取当前持仓"""
        if not self.account_id:
            if not self.get_account_info():
                return []
        
        url = f"{self.base_url}/v1/position"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    positions = data.get('data', {}).get('list', [])
                    print(f"📦 持仓数量: {len(positions)}")
                    return positions
            print(f"❌ 获取持仓失败: {res.text}")
            return []
        except Exception as e:
            print(f"❌ 获取持仓异常: {e}")
            return []
    
    def get_quote(self, symbol):
        """获取实时行情"""
        url = f"{self.base_url}/v1/quote"
        params = {'symbol': symbol}
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    return data['data']
            return None
        except Exception as e:
            print(f"❌ 获取行情异常: {e}")
            return None
    
    def place_order(self, symbol, side, quantity, order_type='MO', price=None):
        """
        下单交易
        
        Args:
            symbol: 股票代码 (如 'NVDA')
            side: 'BUY' 或 'SELL'
            quantity: 数量
            order_type: 'MO'(市价) / 'LO'(限价) / 'MP'(挂单)
            price: 限价单价格
        
        Returns:
            order_id: 订单ID
        """
        if not self.account_id:
            if not self.get_account_info():
                return None
        
        url = f"{self.base_url}/v1/order"
        
        payload = {
            'account_id': self.account_id,
            'symbol': symbol,
            'side': side,  # BUY or SELL
            'order_type': order_type,
            'quantity': str(quantity),
            'time_in_force': 'Day'
        }
        
        if order_type == 'LO' and price:
            payload['price'] = str(price)
        
        try:
            print(f"📝 下单: {side} {quantity}股 {symbol} @ {order_type}")
            res = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    order_id = data['data']['order_id']
                    print(f"✅ 下单成功: {order_id}")
                    return order_id
                else:
                    print(f"❌ 下单失败: {data.get('message')}")
            else:
                print(f"❌ 下单失败: {res.text}")
            return None
        except Exception as e:
            print(f"❌ 下单异常: {e}")
            return None
    
    def cancel_order(self, order_id):
        """撤单"""
        url = f"{self.base_url}/v1/order/{order_id}"
        try:
            res = requests.delete(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    print(f"✅ 撤单成功: {order_id}")
                    return True
            print(f"❌ 撤单失败: {res.text}")
            return False
        except Exception as e:
            print(f"❌ 撤单异常: {e}")
            return False
    
    def get_orders(self, status=None):
        """
        查询订单
        
        Args:
            status: 'Pending'(待成交) / 'Filled'(已成交) / 'Cancelled'(已撤单)
        """
        url = f"{self.base_url}/v1/order"
        params = {}
        if status:
            params['status'] = status
        
        try:
            res = requests.get(url, headers=self.headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get('code') == 0:
                    orders = data.get('data', {}).get('list', [])
                    return orders
            return []
        except Exception as e:
            print(f"❌ 查询订单异常: {e}")
            return []
    
    def calculate_position_size(self, symbol, portfolio_value, risk_per_trade=0.05):
        """
        计算仓位大小
        
        Args:
            symbol: 股票代码
            portfolio_value: 总资产
            risk_per_trade: 单笔风险比例 (默认5%)
        
        Returns:
            quantity: 建议购买数量
        """
        quote = self.get_quote(symbol)
        if not quote:
            return None
        
        price = float(quote.get('last_done', 0))
        if price <= 0:
            return None
        
        # 根据策略规则：单票最高5%，总仓位≤40%
        max_position_value = portfolio_value * risk_per_trade
        quantity = int(max_position_value / price)
        
        # 至少买1股
        if quantity < 1:
            quantity = 1
        
        print(f"📊 仓位计算: {symbol} @ ${price:.2f} x {quantity}股 = ${quantity * price:,.0f}")
        return quantity
    
    def execute_strategy_signal(self, signal, portfolio_value=1000000):
        """
        执行策略信号
        
        Args:
            signal: {
                'symbol': 'NVDA',
                'action': 'BUY',
                'score': 85,
                'confidence': 'high'
            }
            portfolio_value: 总资产
        """
        symbol = signal['symbol']
        action = signal['action']
        score = signal.get('score', 0)
        
        print(f"\n{'='*60}")
        print(f"🎯 执行信号: {action} {symbol} (评分: {score})")
        print(f"{'='*60}")
        
        # 1. 获取当前持仓
        positions = self.get_positions()
        current_position = None
        for pos in positions:
            if pos.get('symbol') == symbol:
                current_position = pos
                break
        
        # 2. 检查持仓情况
        if action == 'BUY':
            if current_position:
                print(f"⚠️ 已有持仓: {current_position.get('quantity', 0)}股")
                return None
            
            # 计算仓位
            quantity = self.calculate_position_size(symbol, portfolio_value)
            if not quantity:
                print(f"❌ 无法计算仓位")
                return None
            
            # 执行买入
            order_id = self.place_order(symbol, 'BUY', quantity, 'MO')
            return order_id
            
        elif action == 'SELL':
            if not current_position:
                print(f"⚠️ 无持仓，无法卖出")
                return None
            
            quantity = current_position.get('quantity', 0)
            if quantity <= 0:
                print(f"❌ 持仓数量为0")
                return None
            
            # 执行卖出
            order_id = self.place_order(symbol, 'SELL', quantity, 'MO')
            return order_id
        
        return None
    
    def check_and_execute_signals(self):
        """检查信号并执行交易"""
        print(f"\n{'='*60}")
        print(f"🤖 美股自动交易检查 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")
        
        # 1. 获取交易信号
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/opportunities.json', 'r') as f:
                data = json.load(f)
            signals = data.get('opportunities', [])
        except:
            print("❌ 无法读取信号文件")
            return
        
        if not signals:
            print("📭 暂无交易信号")
            return
        
        print(f"📊 发现 {len(signals)} 个交易信号")
        
        # 2. 获取账户总资产
        positions = self.get_positions()
        total_value = sum(float(p.get('market_value', 0)) for p in positions)
        total_value = max(total_value, 1000000)  # 默认100万
        
        # 3. 执行高分信号（评分≥70）
        executed = 0
        for signal in signals:
            if signal.get('score', 0) >= 70 and executed < 2:  # 每天最多执行2单
                order_id = self.execute_strategy_signal(signal, total_value)
                if order_id:
                    executed += 1
                    # 记录交易
                    self.record_trade(signal, order_id)
                time.sleep(1)
        
        print(f"\n✅ 本次执行完成: {executed}笔交易")
    
    def record_trade(self, signal, order_id):
        """记录交易到文件"""
        trade = {
            'time': datetime.now().isoformat(),
            'symbol': signal['symbol'],
            'action': signal['action'],
            'score': signal.get('score', 0),
            'order_id': order_id
        }
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades-us.json', 'r') as f:
                trades = json.load(f)
        except:
            trades = {'trades': []}
        
        trades['trades'].append(trade)
        
        with open('/home/admin/.openclaw/workspace-arashi/data/trades-us.json', 'w') as f:
            json.dump(trades, f, indent=2)
        
        print(f"📝 交易已记录")


def main():
    """主函数"""
    trader = LongbridgeTrader()
    
    # 测试连接
    if not trader.get_account_info():
        print("❌ 无法连接长桥API")
        return
    
    # 获取持仓
    positions = trader.get_positions()
    print(f"\n📦 当前持仓:")
    for pos in positions[:5]:
        print(f"  - {pos.get('symbol')}: {pos.get('quantity')}股 @ ${pos.get('cost_price', 0)}")
    
    # 获取待成交订单
    pending_orders = trader.get_orders('Pending')
    print(f"\n⏳ 待成交订单: {len(pending_orders)}")
    
    # 检查并执行信号
    trader.check_and_execute_signals()


if __name__ == '__main__':
    main()
