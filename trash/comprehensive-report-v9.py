#!/usr/bin/env python3
"""
综合日报生成器 v9 - 飞书富文本版（支持表格）
"""

import sys
import json
import requests
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

class ComprehensiveReportV9:
    """综合日报生成器v9 - 飞书富文本版"""
    
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
        """发送Markdown消息（飞书会自动渲染）"""
        if not self.feishu_token:
            if not self.get_feishu_token():
                return False
        
        # 使用post类型发送富文本
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.feishu_token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "open_id"}
        
        # 构建飞书富文本消息
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "post",
            "content": json.dumps({
                "zh_cn": {
                    "title": f"每日交易报告 {datetime.now().strftime('%Y-%m-%d')}",
                    "content": self._parse_to_feishu_format(content)
                }
            })
        }
        
        res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        return res.status_code == 200 and res.json().get('code') == 0
    
    def _parse_to_feishu_format(self, markdown_content):
        """将Markdown转换为飞书富文本格式"""
        lines = markdown_content.split('\n')
        content = []
        
        for line in lines:
            if line.startswith('# '):
                continue  # 标题单独处理
            elif line.startswith('## '):
                content.append([{"tag": "h3", "text": line[3:]}])
            elif line.startswith('|'):
                # 表格行
                cells = [c.strip() for c in line.split('|')[1:-1]]
                if cells and not all(c.replace('-', '').replace(':', '') == '' for c in cells):
                    row = [{"tag": "text", "text": " | ".join(cells)}]
                    content.append(row)
            elif line.strip():
                content.append([{"tag": "text", "text": line}])
        
        return content
    
    def add_header(self):
        self.report += f"# 每日交易报告 {datetime.now().strftime('%Y-%m-%d')}\n\n"
    
    def add_account_summary(self):
        """一、账户核心数据"""
        self.report += "## 📊 一、账户核心数据\n"
        self.report += "| 指标 | 数值 | 备注 |\n"
        self.report += "| :--- | :--- | :--- |\n"
        
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
            
            self.report += f"| 初始资金 | $1,000,000 | 模拟盘本金 |\n"
            self.report += f"| 总资产 | ${total_asset:,.0f} | {total_pnl_pct:+.1f}% |\n"
            self.report += f"| 持仓市值 | ${total_position:,.0f} | {total_position/total_asset*100:.0f}% |\n"
            self.report += f"| 可用资金 | ${cash:,.0f} | {cash/total_asset*100:.0f}% |\n"
            
        except:
            self.report += "| 暂无数据 | - | - |\n"
        
        self.report += "\n"
    
    def add_positions(self):
        """二、持仓明细"""
        self.report += "## 📦 二、当前持仓明细\n"
        self.report += "| 标的 | 数量 | 成本 | 现价 | 盈亏 |\n"
        self.report += "| :--- | :--- | :--- | :--- | :--- |\n"
        
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
                        
                        self.report += f"| {symbol} | {pos['shares']}股 | ${pos['cost']:.2f} | ${price:.2f} | {pnl_pct:+.1f}% |\n"
                    time.sleep(0.5)
                except:
                    pass
            
        except:
            self.report += "| 暂无持仓 | - | - | - | - |\n"
        
        self.report += "\n"
    
    def add_recent_trades(self):
        """三、最近交易"""
        self.report += "## 📜 三、历史交易记录\n"
        self.report += "| 时间 | 标的 | 方向 | 数量 | 价格 |\n"
        self.report += "| :--- | :--- | :--- | :--- | :--- |\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])[-5:]
            
            for t in trades:
                time_str = t.get('time', '')[-12:-7]
                self.report += f"| {time_str} | {t['symbol']} | {t['action']} | {t['shares']}股 | ${t['price']:.2f} |\n"
            
        except:
            self.report += "| 暂无 | - | - | - | - |\n"
        
        self.report += "\n"
    
    def add_strategy(self):
        """四、策略"""
        self.report += "## 🎯 四、策略说明\n"
        self.report += "- 开仓：评分≥70分，仓位2-5%\n"
        self.report += "- 止损：浮亏≥6%\n"
        self.report += "- 止盈：收益≥15%\n"
        self.report += "- 仓位：单票最高5%，总仓位≤40%\n\n"
    
    def add_signals(self):
        """五、交易信号"""
        self.report += "## 🔍 五、交易信号\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/opportunities.json', 'r') as f:
                data = json.load(f)
            
            opps = data.get('opportunities', [])
            
            if opps:
                self.report += "| 标的 | 涨幅 | 评分 |\n"
                self.report += "| :--- | :--- | :--- |\n"
                for o in opps[:5]:
                    self.report += f"| {o['symbol']} | {o['change_pct']:+.1f}% | {o['score']}分 |\n"
            else:
                self.report += "暂无交易信号\n"
            
        except:
            self.report += "暂无交易信号\n"
        
        self.report += "\n"
    
    def add_market(self):
        """六、市场"""
        self.report += "## 📰 六、市场分析\n"
        self.report += "- 大盘：震荡\n"
        self.report += "- 板块：AI、半导体\n"
        self.report += "- 风险：加息预期\n\n"
    
    def add_sentiment(self, quote_ctx):
        """七、情绪"""
        self.report += "## 😊 七、市场情绪\n"
        self.report += "| 指标 | 数值 | 状态 |\n"
        self.report += "| :--- | :--- | :--- |\n"
        
        ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
        if ret == 0 and not data.empty:
            vhsi = data.iloc[0]['last_price']
            status = "恐慌" if vhsi >= 25 else "正常"
            self.report += f"| VHSI | {vhsi:.1f} | {status} |\n"
        
        self.report += "\n"
    
    def add_risk(self):
        """八、风险"""
        self.report += "## ⚠️ 八、风险提示\n"
        self.report += "- 系统性：加息预期波动\n"
        self.report += "- 建议：控制仓位\n\n"
        self.report += f"生成时间：{datetime.now().strftime('%H:%M')}\n"
    
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
    reporter = ComprehensiveReportV9()
    reporter.run()
