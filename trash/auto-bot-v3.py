#!/usr/bin/env python3
"""
自动交易机器人 v3.0
- 发现机会 → 不通知
- 执行买入 → 推送通知
- 减少API调用
"""

import sys
import json
import time
from datetime import datetime
import requests

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class AutoTradingBotV3:
    """自动交易机器人 v3.0"""
    
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
        
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        
        self.finnhub_key = keys['finnhub']['api_key']
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
    
    def get_quote(self, symbol):
        """获取行情"""
        try:
            url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
        except:
            pass
        return None
    
    def scan_and_trade(self):
        """扫描并交易"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描...")
        
        for symbol in self.watch_list:
            quote = self.get_quote(symbol)
            if not quote or 'c' not in quote:
                continue
            
            price = quote.get('c', 0)
            change_pct = quote.get('dp', 0)
            
            # 评分
            score = 50
            if change_pct > 3:
                score += 30
            elif change_pct > 2:
                score += 20
            elif change_pct > 1:
                score += 10
            
            # 买入条件：评分≥70 且 涨幅>2% 且 没持仓
            if score >= 70 and change_pct > 2 and symbol not in self.positions:
                shares = int(50000 / price)  # 每只约5万
                cost = shares * price
                
                if cost <= self.cash:
                    # 执行买入
                    self.positions[symbol] = {'shares': shares, 'cost': price}
                    self.cash -= cost
                    
                    reason = f"评分:{score} 涨幅:{change_pct:+.2f}%"
                    
                    # 买入后推送通知
                    self.send_buy_notification(symbol, shares, price, reason)
                    
                    print(f"🟢 买入 {symbol} {shares}股 @${price:.2f}")
                    
                    # 记录交易
                    self.save_trade('BUY', symbol, shares, price, reason)
            
            time.sleep(1.1)  # 避免API限流
    
    def save_trade(self, action, symbol, shares, price, reason):
        """保存交易记录"""
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
        print("🤖 自动交易机器人 v3.0")
        print("=" * 60)
        print(f"监控: {len(self.watch_list)}只")
        print(f"推送: 仅买入时通知")
        print("=" * 60)
        
        while True:
            try:
                self.scan_and_trade()
                time.sleep(60)  # 60秒扫描一次，减少API调用
            except KeyboardInterrupt:
                print("\n✋ 停止")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
                time.sleep(30)


if __name__ == '__main__':
    bot = AutoTradingBotV3()
    bot.run()
