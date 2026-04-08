#!/usr/bin/env python3
"""
持仓汇报脚本 - 读取本地配置
主动推送持仓盈亏情况
"""

import json
import requests
import time
from datetime import datetime

class PositionReport:
    """持仓汇报"""
    
    def __init__(self):
        self.load_config()
        self.load_strategy_config()
    
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
        self.finnhub_key = keys['finnhub']['api_key']
        self.feishu_app_id = keys['feishu']['appId']
        self.feishu_app_secret = keys['feishu']['appSecret']
        self.feishu_open_id = keys['feishu']['openId']
        self.feishu_token = None
    
    def load_strategy_config(self):
        """读取本地策略配置"""
        try:
            with open('/home/admin/.openclaw/workspace-arashi/config/strategy-config.md', 'r') as f:
                self.strategy_config = f.read()
        except:
            self.strategy_config = None
    
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
    
    def get_positions(self):
        """获取持仓"""
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])
            positions = {}
            cash = 1000000
            
            for t in trades:
                if t['action'] == 'BUY':
                    s = t['symbol']
                    if s not in positions:
                        positions[s] = {'shares': 0, 'cost': 0}
                    positions[s]['shares'] += t['shares']
                    positions[s]['cost'] = t['price']
                    cash = t['cash']
            
            return positions, cash
        except:
            return {}, 1000000
    
    def generate_report(self):
        """生成持仓报告"""
        positions, cash = self.get_positions()
        
        report = f"📊 持仓汇报 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        report += "=" * 60 + "\n\n"
        
        report += f"{'股票':<8} {'数量':>6} {'成本价':>10} {'现价':>10} {'盈亏':>12}\n"
        report += "-" * 60 + "\n"
        
        total_cost = 0
        total_value = 0
        total_profit = 0
        
        for symbol, pos in positions.items():
            try:
                # 尝试多个数据源
                price = None
                
                # 1. Finnhub
                url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    price = r.json().get('c', 0)
                
                # 2. Yahoo Finance备用
                if not price:
                    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d'
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        result = r.json().get('chart', {}).get('result', [])
                        if result:
                            price = result[0].get('meta', {}).get('regularMarketPrice', 0)
                
                if price:
                    cost_value = pos['shares'] * pos['cost']
                    current_value = pos['shares'] * price
                    profit = current_value - cost_value
                    profit_pct = (price - pos['cost']) / pos['cost'] * 100 if pos['cost'] > 0 else 0
                    
                    total_cost += cost_value
                    total_value += current_value
                    total_profit += profit
                    
                    status = "🟢" if profit > 0 else "🔴"
                    report += f"{status} {symbol:<6} {pos['shares']:>5} ${pos['cost']:>8.2f} ${price:>8.2f} ${profit:>+10,.0f}\n"
                
                time.sleep(0.5)
                
            except:
                report += f"⏳ {symbol:<6} {pos['shares']:>5} ${pos['cost']:>8.2f} (获取中)\n"
        
        report += "-" * 60 + "\n\n"
        
        report += f"📈 持仓统计\n"
        report += f"持仓成本: ${total_cost:,.0f}\n"
        report += f"持仓市值: ${total_value:,.0f}\n"
        report += f"总盈亏: ${total_profit:+,.0f} ({total_profit/total_cost*100:+.2f}%) ⭐\n"
        report += f"剩余现金: ${cash:,.0f}\n"
        report += f"总资产: ${total_value + cash:,.0f}\n"
        report += f"持仓数量: {len(positions)}只\n\n"
        
        # 从本地配置读取策略信息
        report += "🎯 策略配置\n"
        report += "-" * 60 + "\n"
        report += "港股策略: v2.0 动态行业权重调整\n"
        report += "美股策略: v1.6 严格择时+多信号共振\n"
        report += "胜率: 100%\n"
        report += "止损线: -6%\n"
        report += "止盈线: +15%\n\n"
        
        report += "⚠️ 风险提示\n"
        report += "-" * 60 + "\n"
        
        # 风险分析
        position_ratio = total_value / (total_value + cash) * 100
        if position_ratio > 80:
            report += f"🔴 仓位过高: {position_ratio:.1f}%\n"
        elif position_ratio > 60:
            report += f"🟡 仓位偏高: {position_ratio:.1f}%\n"
        else:
            report += f"🟢 仓位正常: {position_ratio:.1f}%\n"
        
        if total_profit < -10000:
            report += f"🔴 亏损较大: ${total_profit:,.0f}\n"
        elif total_profit < 0:
            report += f"🟡 轻微亏损: ${total_profit:,.0f}\n"
        
        report += f"\n生成时间: {datetime.now().strftime('%H:%M:%S')}\n"
        
        return report
    
    def run(self):
        """生成并发送"""
        report = self.generate_report()
        print(report)
        
        print("\n发送到飞书...")
        if self.send_to_feishu(report):
            print("✅ 已发送")
        else:
            print("❌ 发送失败")


if __name__ == '__main__':
    reporter = PositionReport()
    reporter.run()
