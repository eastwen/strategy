#!/usr/bin/env python3
"""
自动交易机器人 v3.1
- 多数据源备份
- 自动切换API
- Finnhub → AlphaVantage → Yahoo Finance
"""

import sys
import json
import time
from datetime import datetime
import requests

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class AutoTradingBotV31:
    """自动交易机器人 v3.1 - 多数据源"""
    
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
        
        msg = f"""🟢 买入执行通知

股票: {symbol}
数量: {shares}股
价格: ${price:.2f}
金额: ${shares * price:,.2f}
原因: {reason}

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
        """Finnhub数据源"""
        if not self.api_status['finnhub']['available']:
            return None
        
        try:
            url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
            res = requests.get(url, timeout=10)
            
            if res.status_code == 429:
                # 限流，标记为不可用
                self.api_status['finnhub']['available'] = False
                self.api_status['finnhub']['reset_time'] = time.time() + 60
                print("⚠️ Finnhub限流，切换备用源")
                return None
            
            if res.status_code == 200:
                data = res.json()
                if data.get('c'):
                    return {'price': data['c'], 'change_pct': data.get('dp', 0)}
        except:
            pass
        
        return None
    
    def get_quote_alphavantage(self, symbol):
        """AlphaVantage数据源（备用）"""
        if not self.api_status['alphavantage']['available']:
            return None
        
        try:
            url = f'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={self.alphavantage_key}'
            res = requests.get(url, timeout=10)
            
            if res.status_code == 429:
                self.api_status['alphavantage']['available'] = False
                self.api_status['alphavantage']['reset_time'] = time.time() + 60
                print("⚠️ AlphaVantage限流，切换备用源")
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
        """Yahoo Finance数据源（免费，无API限制）"""
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
        # 检查并重置API状态
        now = time.time()
        for api_name in self.api_status:
            if not self.api_status[api_name]['available'] and now > self.api_status[api_name]['reset_time']:
                self.api_status[api_name]['available'] = True
                print(f"✅ {api_name} 已恢复")
        
        # 按优先级尝试
        # 1. Finnhub（最快）
        result = self.get_quote_finnhub(symbol)
        if result:
            return result
        
        # 2. AlphaVantage（备用）
        result = self.get_quote_alphavantage(symbol)
        if result:
            return result
        
        # 3. Yahoo Finance（免费无限制）
        result = self.get_quote_yahoo(symbol)
        if result:
            return result
        
        return None
    
    def scan_and_trade(self):
        """扫描并交易"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描...")
        
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
            if score >= 70 and change_pct > 2 and symbol not in self.positions:
                shares = int(50000 / price)
                cost = shares * price
                
                if cost <= self.cash:
                    self.positions[symbol] = {'shares': shares, 'cost': price}
                    self.cash -= cost
                    
                    reason = f"评分:{score} 涨幅:{change_pct:+.2f}%"
                    
                    self.send_buy_notification(symbol, shares, price, reason)
                    print(f"🟢 买入 {symbol} {shares}股 @${price:.2f}")
                    
                    self.save_trade('BUY', symbol, shares, price, reason)
            
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
    
    def run(self):
        print("=" * 60)
        print("🤖 自动交易机器人 v3.1 (多数据源)")
        print("=" * 60)
        print(f"监控: {len(self.watch_list)}只")
        print(f"数据源: Finnhub → AlphaVantage → Yahoo")
        print(f"推送: 仅买入时通知")
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
    bot = AutoTradingBotV31()
    bot.run()
