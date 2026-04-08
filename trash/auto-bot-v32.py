#!/usr/bin/env python3
"""
自动交易机器人 v3.2
- 多数据源备份
- 单只股票持仓限制
- 防止重复购买
"""

import sys
import json
import time
from datetime import datetime
import requests

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class AutoTradingBotV32:
    """自动交易机器人 v3.2"""
    
    def __init__(self):
        self.load_config()
        
        # 监控股票池
        self.watch_list = [
            'QQQ', 'SPY', 'IWM',
            'NVDA', 'TSLA', 'AAPL', 'META', 'AMD', 'GOOGL', 'MSFT', 'AMZN',
            'VRT', 'SMCI', 'PLTR', 'ARM', 'AI', 'COIN', 'SOXL', 'SOXS',
        ]
        
        # 持仓和资金
        self.positions = {}
        self.cash = 1000000
        self.initial_cash = 1000000
        
        # 🎯 持仓限制配置
        self.max_position_value = 100000      # 单只股票最大持仓金额
        self.max_position_ratio = 0.15        # 单只股票最大持仓比例（15%）
        self.max_total_position = 0.80        # 总仓位上限（80%）
        
        # 从文件加载已有持仓
        self.load_positions()
        
        # API状态追踪
        self.api_status = {
            'finnhub': {'available': True, 'reset_time': 0},
            'alphavantage': {'available': True, 'reset_time': 0},
            'yahoo': {'available': True, 'reset_time': 0}
        }
        
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        
        self.finnhub_key = keys['finnhub']['api_key']
        self.alphavantage_key = keys['alphavantage']['api_key']
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_open_id = keys['feishu']['openId']
        self.feishu_token = None
    
    def load_positions(self):
        """从交易记录加载已有持仓 - 修复版：去重计算"""
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            # 使用字典去重：每个symbol只保留最后一次买入记录
            latest_buys = {}
            for trade in data.get('trades', []):
                if trade['action'] == 'BUY':
                    symbol = trade['symbol']
                    # 只保留最新的买入记录（按时间排序后的最后一个）
                    latest_buys[symbol] = trade
            
            # 重新计算持仓和现金
            total_cost = 0
            for symbol, trade in latest_buys.items():
                shares = trade['shares']
                price = trade['price']
                cost = shares * price
                
                self.positions[symbol] = {'shares': shares, 'cost': price}
                total_cost += cost
            
            # 正确计算剩余现金
            self.cash = self.initial_cash - total_cost
            
            print(f"✅ 已加载持仓: {len(self.positions)}只股票")
            print(f"   现金: ${self.cash:,.0f}")
            print(f"   总投入: ${total_cost:,.0f}")
            
        except Exception as e:
            print(f"⚠️ 加载持仓失败: {e}")
    
    def get_feishu_token(self):
        if self.feishu_token:
            return self.feishu_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={
            "app_id": self.feishu_app_id,
            "app_secret": self.feishu_app_secret
        }, timeout=10)
        
        if res.status_code == 200 and res.json().get('code') == 0:
            self.feishu_token = res.json().get('tenant_access_token')
            return self.feishu_token
        return None
    
    def send_buy_notification(self, symbol, shares, price, reason):
        """买入后推送通知"""
        token = self.get_feishu_token()
        if not token:
            return
        
        # 计算当前持仓
        position_value = self.positions.get(symbol, {}).get('shares', 0) * price
        total_position = sum(p['shares'] * p['cost'] for p in self.positions.values())
        position_ratio = position_value / self.initial_cash * 100
        
        msg = f"""🟢 买入执行通知

股票: {symbol}
数量: {shares}股
价格: ${price:.2f}
金额: ${shares * price:,.2f}
原因: {reason}

当前持仓: {position_ratio:.1f}%
总仓位: {total_position / self.initial_cash * 100:.1f}%

时间: {datetime.now().strftime('%H:%M:%S')}"""
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": msg})
        }
        requests.post(url, headers=headers, params=params, json=data, timeout=10)
    
    def send_sell_notification(self, symbol, shares, price, cost_price, reason):
        """卖出后推送通知"""
        token = self.get_feishu_token()
        if not token:
            return
        
        # 计算盈亏
        cost_value = shares * cost_price
        sell_value = shares * price
        pnl = sell_value - cost_value
        pnl_pct = (pnl / cost_value) * 100 if cost_value > 0 else 0
        
        # 盈亏表情
        if pnl > 0:
            emoji = "📈"
            result = "盈利"
        elif pnl < 0:
            emoji = "📉"
            result = "亏损"
        else:
            emoji = "➖"
            result = "持平"
        
        # 计算剩余持仓
        remaining_shares = self.positions.get(symbol, {}).get('shares', 0)
        total_position = sum(p['shares'] * p['cost'] for p in self.positions.values())
        
        msg = f"""🔴 卖出执行通知 {emoji}

股票: {symbol}
数量: {shares}股
卖出价格: ${price:.2f}
成本价格: ${cost_price:.2f}
卖出金额: ${sell_value:,.2f}

盈亏: ${pnl:+.2f} ({pnl_pct:+.2f}%) {result}
原因: {reason}

剩余持仓: {remaining_shares}股
总仓位: {total_position / self.initial_cash * 100:.1f}%
现金: ${self.cash:,.0f}

时间: {datetime.now().strftime('%H:%M:%S')}"""
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": msg})
        }
        requests.post(url, headers=headers, params=params, json=data, timeout=10)
    
    def get_quote_finnhub(self, symbol):
        if not self.api_status['finnhub']['available']:
            return None
        try:
            url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
            res = requests.get(url, timeout=10)
            if res.status_code == 429:
                self.api_status['finnhub']['available'] = False
                self.api_status['finnhub']['reset_time'] = time.time() + 60
                return None
            if res.status_code == 200:
                data = res.json()
                if data.get('c'):
                    return {'price': data['c'], 'change_pct': data.get('dp', 0)}
        except:
            pass
        return None
    
    def get_quote_alphavantage(self, symbol):
        if not self.api_status['alphavantage']['available']:
            return None
        try:
            url = f'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={self.alphavantage_key}'
            res = requests.get(url, timeout=10)
            if res.status_code == 429:
                self.api_status['alphavantage']['available'] = False
                self.api_status['alphavantage']['reset_time'] = time.time() + 60
                return None
            if res.status_code == 200:
                data = res.json()
                quote = data.get('Global Quote', {})
                if quote:
                    price = float(quote.get('05. price', 0))
                    change_pct = float(quote.get('10. change percent', '0%').replace('%', ''))
                    return {'price': price, 'change_pct': change_pct}
        except:
            pass
        return None
    
    def get_quote_yahoo(self, symbol):
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d'
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                result = data.get('chart', {}).get('result', [])
                if result:
                    meta = result[0].get('meta', {})
                    price = meta.get('regularMarketPrice', 0)
                    prev = meta.get('previousClose', 0)
                    change_pct = ((price - prev) / prev * 100) if prev > 0 else 0
                    return {'price': price, 'change_pct': change_pct}
        except:
            pass
        return None
    
    def get_quote(self, symbol):
        """获取行情（自动切换数据源）"""
        now = time.time()
        for api_name in self.api_status:
            if not self.api_status[api_name]['available'] and now > self.api_status[api_name]['reset_time']:
                self.api_status[api_name]['available'] = True
        
        result = self.get_quote_finnhub(symbol)
        if result:
            return result
        
        result = self.get_quote_alphavantage(symbol)
        if result:
            return result
        
        result = self.get_quote_yahoo(symbol)
        if result:
            return result
        
        return None
    
    def can_buy(self, symbol, price):
        """检查是否可以买入"""
        # 1. 已有持仓则不买
        if symbol in self.positions:
            return False, "已有持仓"
        
        # 2. 检查现金
        if self.cash < 5000:
            return False, "现金不足"
        
        # 3. 检查总仓位
        total_position = sum(p['shares'] * p['cost'] for p in self.positions.values())
        if total_position / self.initial_cash > self.max_total_position:
            return False, f"总仓位已达{self.max_total_position*100:.0f}%"
        
        return True, "OK"
    
    def check_and_sell(self, symbol, price):
        """检查是否需要卖出（止损/止盈）"""
        if symbol not in self.positions:
            return False
        
        position = self.positions[symbol]
        shares = position['shares']
        cost_price = position['cost']
        
        if shares <= 0 or cost_price <= 0:
            return False
        
        # 计算盈亏比例
        pnl_pct = ((price - cost_price) / cost_price) * 100
        
        sell_reason = None
        
        # 止损: 浮亏 >= 6%
        if pnl_pct <= -6:
            sell_reason = f"触发止损线 (-{abs(pnl_pct):.1f}%)"
        
        # 止盈: 浮盈 >= 15%
        elif pnl_pct >= 15:
            sell_reason = f"达到止盈线 (+{pnl_pct:.1f}%)"
        
        if sell_reason:
            # 执行卖出
            sell_value = shares * price
            self.cash += sell_value
            
            # 发送通知
            self.send_sell_notification(symbol, shares, price, cost_price, sell_reason)
            print(f"🔴 卖出 {symbol} {shares}股 @${price:.2f} - {sell_reason}")
            
            # 保存交易记录
            self.save_trade('SELL', symbol, shares, price, sell_reason)
            
            # 从持仓中移除
            del self.positions[symbol]
            
            return True
        
        return False
    
    def scan_and_trade(self):
        """扫描并交易"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描...")
        
        # 第一步：检查持仓是否需要卖出
        for symbol in list(self.positions.keys()):
            quote = self.get_quote(symbol)
            if quote:
                price = quote.get('price', 0)
                self.check_and_sell(symbol, price)
                time.sleep(0.3)
        
        # 第二步：扫描买入机会
        for symbol in self.watch_list:
            quote = self.get_quote(symbol)
            if not quote:
                continue
            
            price = quote.get('price', 0)
            change_pct = quote.get('change_pct', 0)
            
            # 评分
            score = 50
            if change_pct > 3:
                score += 30
            elif change_pct > 2:
                score += 20
            elif change_pct > 1:
                score += 10
            
            # 买入条件
            if score >= 70 and change_pct > 2:
                # 检查是否可买
                can_buy, reason = self.can_buy(symbol, price)
                
                if can_buy:
                    shares = int(50000 / price)
                    cost = shares * price
                    
                    # 限制单只股票最大持仓
                    if cost > self.max_position_value:
                        shares = int(self.max_position_value / price)
                        cost = shares * price
                    
                    if cost <= self.cash:
                        self.positions[symbol] = {'shares': shares, 'cost': price}
                        self.cash -= cost
                        
                        buy_reason = f"评分:{score} 涨幅:{change_pct:+.2f}%"
                        
                        self.send_buy_notification(symbol, shares, price, buy_reason)
                        print(f"🟢 买入 {symbol} {shares}股 @${price:.2f}")
                        
                        self.save_trade('BUY', symbol, shares, price, buy_reason)
            
            time.sleep(0.5)
    
    def save_trade(self, action, symbol, shares, price, reason):
        import os
        os.makedirs('/home/admin/.openclaw/workspace-arashi/data', exist_ok=True)
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
        except:
            data = {'trades': []}
        
        data['trades'].append({
            'action': action,
            'symbol': symbol,
            'shares': shares,
            'price': price,
            'value': shares * price,
            'cash': self.cash,
            'reason': reason,
            'time': datetime.now().isoformat()
        })
        
        with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'w') as f:
            json.dump(data, f, indent=2)
        
        # 🎯 每次交易后触发智能优化检查（后台运行，不阻塞）
        import threading
        threading.Thread(target=self.run_smart_optimization, daemon=True).start()
    
    def run_smart_optimization(self):
        """运行智能优化检查（发现问题→分析→提供方案→等你确认）"""
        try:
            import subprocess
            # 使用新的智能优化器
            subprocess.run(
                ['python3', '/home/admin/.openclaw/workspace-arashi/smart-ai-optimizer.py'],
                timeout=30, capture_output=True
            )
        except:
            pass
    
    def run(self):
        print("=" * 60)
        print("🤖 自动交易机器人 v3.2 (持仓限制)")
        print("=" * 60)
        print(f"监控: {len(self.watch_list)}只")
        print(f"数据源: Finnhub → AlphaVantage → Yahoo")
        print(f"单只上限: ${self.max_position_value:,.0f} ({self.max_position_ratio*100:.0f}%)")
        print(f"总仓位上限: {self.max_total_position*100:.0f}%")
        print(f"当前持仓: {len(self.positions)}只")
        print(f"当前现金: ${self.cash:,.0f}")
        print("=" * 60)
        
        while True:
            try:
                self.scan_and_trade()
                time.sleep(60)
            except KeyboardInterrupt:
                print("\n✋ 停止")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
                time.sleep(30)


if __name__ == '__main__':
    bot = AutoTradingBotV32()
    bot.run()
