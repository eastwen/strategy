#!/usr/bin/env python3
"""
自动交易机器人 v2.0 - 带飞书推送
- 扫描 → 分析 → 下单 → 推送 全自动
"""

import sys
import json
import time
from datetime import datetime
import requests

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class AutoTradingBotV2:
    """自动交易机器人 v2.0"""
    
    def __init__(self):
        # 加载配置
        self.load_config()
        
        # 监控股票池
        self.watch_list = [
            'QQQ', 'SPY', 'IWM',
            'NVDA', 'TSLA', 'AAPL', 'META', 'AMD', 'GOOGL', 'MSFT', 'AMZN',
            'VRT', 'SMCI', 'PLTR', 'ARM', 'AI', 'COIN', 'SOXL', 'SOXS',
        ]
        
        # 持仓和资金
        self.positions = []
        self.cash = 1000000
        
    def load_config(self):
        """加载配置"""
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        
        self.finnhub_key = keys['finnhub']['api_key']
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_open_id = keys['feishu']['openId']
        
        self.feishu_token = None
        self.feishu_token_expire = 0
        
    def get_feishu_token(self):
        """获取飞书token"""
        if self.feishu_token and time.time() < self.feishu_token_expire:
            return self.feishu_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={
            "app_id": self.feishu_app_id,
            "app_secret": self.feishu_app_secret
        }, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data.get('code') == 0:
                self.feishu_token = data.get('tenant_access_token')
                self.feishu_token_expire = time.time() + data.get('expire', 7200) - 300
                return self.feishu_token
        
        return None
    
    def send_feishu_message(self, content):
        """发送飞书消息"""
        token = self.get_feishu_token()
        if not token:
            print("❌ 获取飞书token失败")
            return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": content})
        }
        
        try:
            res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
            if res.status_code == 200:
                result = res.json()
                if result.get('code') == 0:
                    print("✅ 飞书消息已发送")
                    return True
        except Exception as e:
            print(f"❌ 发送失败: {e}")
        
        return False
    
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
        print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] 扫描...")
        
        opportunities = []
        
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
            elif change_pct < -3:
                score -= 30
            
            # 发现机会
            if score >= 70 and change_pct > 2:
                opportunities.append({
                    'symbol': symbol,
                    'price': price,
                    'change_pct': change_pct,
                    'score': score
                })
                
                # 主动推送
                self.send_feishu_message(
                    f"🔥 发现交易机会！\n\n"
                    f"股票: {symbol}\n"
                    f"价格: ${price:.2f}\n"
                    f"涨幅: {change_pct:+.2f}%\n"
                    f"评分: {score}分\n\n"
                    f"时间: {datetime.now().strftime('%H:%M:%S')}"
                )
            
            time.sleep(0.5)
        
        # 保存机会
        if opportunities:
            with open('/home/admin/.openclaw/workspace-arashi/data/opportunities.json', 'w') as f:
                json.dump({
                    'time': datetime.now().isoformat(),
                    'opportunities': opportunities
                }, f, indent=2)
        
        return opportunities
    
    def run(self):
        """运行"""
        print("=" * 60)
        print("🤖 自动交易机器人 v2.0 (带飞书推送)")
        print("=" * 60)
        print(f"监控: {len(self.watch_list)}只")
        print(f"飞书推送: 已启用 ✅")
        print("=" * 60)
        
        while True:
            try:
                self.scan_and_trade()
                time.sleep(30)
            except KeyboardInterrupt:
                print("\n✋ 停止")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")
                time.sleep(10)


if __name__ == '__main__':
    bot = AutoTradingBotV2()
    bot.run()
