#!/usr/bin/env python3
"""
综合日报生成器 v8 - 飞书极简版
"""

import sys
import json
import requests
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

class ComprehensiveReportV8:
    """综合日报生成器v8 - 极简版"""
    
    def __init__(self):
        self.load_config()
        self.report = ""
    
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        self.finnhub_key = keys['finnhub']['api_key']
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_open_id = keys['feishu']['openId']
        self.feishu_token = None
    
    def get_feishu_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        res = requests.post(url, json={
            "app_id": self.feishu_app_id,
            "app_secret": self.feishu_app_secret
        }, timeout=10)
        if res.status_code == 200 and res.json().get('code') == 0:
            self.feishu_token = res.json().get('tenant_access_token')
            return True
        return False
    
    def send_to_feishu(self, content):
        if not self.feishu_token:
            if not self.get_feishu_token():
                return False
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {self.feishu_token}", "Content-Type": "application/json"}
        params = {"receive_id_type": "open_id"}
        data = {"receive_id": self.feishu_open_id, "msg_type": "text", "content": json.dumps({"text": content})}
        res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        return res.status_code == 200 and res.json().get('code') == 0
    
    def add_header(self):
        self.report += f"【每日交易报告】{datetime.now().strftime('%Y-%m-%d')}\n\n"
    
    def add_account_summary(self):
        """一、账户核心数据"""
        self.report += "【账户核心数据】\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])
            positions = {}
            cash = 1000000
            initial = 1000000
            
            for t in trades:
                if t['action'] == 'BUY':
                    s = t['symbol']
                    if s not in positions:
                        positions[s] = {'shares': 0, 'cost': 0}
                    positions[s]['shares'] += t['shares']
                    positions[s]['cost'] = t['price']
                    cash = t['cash']
            
            total_position = sum(p['shares'] * p['cost'] for p in positions.values())
            total_asset = total_position + cash
            total_pnl = total_asset - initial
            total_pnl_pct = total_pnl / initial * 100
            
            self.report += f"总资产: ${total_asset:,.0f}\n"
            self.report += f"持仓: ${total_position:,.0f} ({total_position/total_asset*100:.0f}%)\n"
            self.report += f"现金: ${cash:,.0f} ({cash/total_asset*100:.0f}%)\n"
            self.report += f"盈亏: ${total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)\n"
            
        except:
            self.report += "暂无数据\n"
        
        self.report += "\n"
    
    def add_positions(self):
        """二、当前持仓"""
        self.report += "【持仓明细】\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])
            positions = {}
            
            for t in trades:
                if t['action'] == 'BUY':
                    s = t['symbol']
                    if s not in positions:
                        positions[s] = {'shares': 0, 'cost': 0}
                    positions[s]['shares'] += t['shares']
                    positions[s]['cost'] = t['price']
            
            for symbol, pos in list(positions.items())[:10]:
                try:
                    url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        d = r.json()
                        price = d.get('c', 0)
                        pnl_pct = (price - pos['cost']) / pos['cost'] * 100
                        status = "涨" if pnl_pct > 0 else "跌"
                        
                        self.report += f"{symbol} {pos['shares']}股 {pnl_pct:+.1f}%\n"
                    time.sleep(0.5)
                except:
                    pass
            
        except:
            self.report += "暂无持仓\n"
        
        self.report += "\n"
    
    def add_recent_trades(self):
        """三、最近交易"""
        self.report += "【最近交易】\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])[-5:]
            
            for t in trades:
                self.report += f"{t['action']} {t['symbol']} {t['shares']}股\n"
            
        except:
            self.report += "暂无\n"
        
        self.report += "\n"
    
    def add_strategy(self):
        """四、策略"""
        self.report += "【策略】\n"
        self.report += "开仓: 评分70分\n"
        self.report += "止损: -6%\n"
        self.report += "止盈: +15%\n\n"
    
    def add_signals(self):
        """五、交易信号"""
        self.report += "【交易信号】\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/opportunities.json', 'r') as f:
                data = json.load(f)
            
            opps = data.get('opportunities', [])
            
            if opps:
                for o in opps[:5]:
                    self.report += f"{o['symbol']} {o['change_pct']:+.1f}% 评分{o['score']}\n"
            else:
                self.report += "暂无\n"
            
        except:
            self.report += "暂无\n"
        
        self.report += "\n"
    
    def add_market(self):
        """六、市场"""
        self.report += "【市场】\n"
        self.report += "大盘: 震荡\n"
        self.report += "板块: AI 半导体\n\n"
    
    def add_sentiment(self, quote_ctx):
        """七、情绪"""
        self.report += "【情绪】\n"
        
        ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
        if ret == 0 and not data.empty:
            vhsi = data.iloc[0]['last_price']
            status = "恐慌" if vhsi >= 25 else "正常"
            self.report += f"VHSI: {vhsi:.1f} {status}\n"
        
        self.report += "\n"
    
    def add_risk(self):
        """八、风险"""
        self.report += "【风险】\n"
        self.report += "控制仓位\n\n"
        self.report += f"时间: {datetime.now().strftime('%H:%M')}\n"
    
    def generate(self):
        quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        try:
            self.add_header()
            self.add_account_summary()
            self.add_positions()
            self.add_recent_trades()
            self.add_strategy()
            self.add_signals()
            self.add_market()
            self.add_sentiment(quote_ctx)
            self.add_risk()
        finally:
            quote_ctx.close()
        return self.report
    
    def run(self):
        report = self.generate()
        print(report)
        print("\n发送到飞书...")
        if self.send_to_feishu(report):
            print("✅ 已发送")
        else:
            print("❌ 发送失败")


if __name__ == '__main__':
    reporter = ComprehensiveReportV8()
    reporter.run()
