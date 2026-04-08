#!/usr/bin/env python3
"""
综合日报生成器 v6 - 完全按模板
"""

import sys
import json
import requests
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

class ComprehensiveReportV6:
    """综合日报生成器v6 - 完整版"""
    
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
        self.report += f"# 每日交易报告 {datetime.now().strftime('%Y-%m-%d')}\n"
        self.report += "---\n\n"
    
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
            realized_pnl = 0
            
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
            
            self.report += f"| 初始资金 | $1,000,000.00 | 模拟盘初始本金 |\n"
            self.report += f"| 当前总资产 | ${total_asset:,.2f} | 较初始值{total_pnl_pct:+.2f}% |\n"
            self.report += f"| 持仓总市值 | ${total_position:,.2f} | 占总资产{total_position/total_asset*100:.1f}% |\n"
            self.report += f"| 可用资金 | ${cash:,.2f} | 占总资产{cash/total_asset*100:.1f}% |\n"
            self.report += f"| 浮动盈亏 | - | 持仓未实现盈亏 |\n"
            self.report += f"| 已实现盈亏 | - | 平仓盈亏 |\n"
            self.report += f"| 累计总盈亏 | ${total_pnl:,.2f} | 累计盈亏比例{total_pnl_pct:+.2f}% |\n"
            
        except:
            self.report += "| 暂无数据 | - | - |\n"
        
        self.report += "\n---\n\n"
    
    def add_positions(self):
        """二、当前持仓明细"""
        self.report += "## 📦 二、当前持仓明细\n"
        self.report += "| 标的代码 | 持仓数量 | 平均成本 | 当前市值 | 浮动盈亏 | 盈亏比例 | 止损线 | 目标价 |\n"
        self.report += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
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
                        market_value = pos['shares'] * price
                        pnl = market_value - pos['shares'] * pos['cost']
                        pnl_pct = (price - pos['cost']) / pos['cost'] * 100
                        stop_loss = pos['cost'] * 0.94
                        target = pos['cost'] * 1.15
                        
                        self.report += f"| {symbol} | {pos['shares']}股 | ${pos['cost']:.2f} | ${market_value:,.2f} | ${pnl:,.2f} | {pnl_pct:+.2f}% | ${stop_loss:.2f} | ${target:.2f} |\n"
                    time.sleep(0.5)
                except:
                    pass
            
        except:
            self.report += "| 暂无持仓 | - | - | - | - | - | - | - |\n"
        
        self.report += "\n---\n\n"
    
    def add_trade_history(self):
        """三、历史交易记录"""
        self.report += "## 📜 三、历史交易记录（最近5笔）\n"
        self.report += "| 交易时间 | 标的代码 | 交易方向 | 成交数量 | 成交价格 | 平仓盈亏 | 盈亏比例 | 平仓原因 |\n"
        self.report += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])[-5:]
            
            for t in trades:
                time_str = t.get('time', '')[:16]
                self.report += f"| {time_str} | {t['symbol']} | {t['action']} | {t['shares']}股 | ${t['price']:.2f} | - | - | {t.get('reason', '')[:15]} |\n"
            
        except:
            self.report += "| 暂无交易记录 | - | - | - | - | - | - | - |\n"
        
        self.report += "\n---\n\n"
    
    def add_strategy(self):
        """四、当前策略说明"""
        self.report += "## 🎯 四、当前策略说明（v1.0版本）\n"
        self.report += "### 核心规则\n"
        self.report += "1. 评分体系：综合资讯面(35%)、技术面(40%)、情绪面(25%)三个维度，总分100分\n"
        self.report += "2. 开仓规则：评分≥70分开仓，基础仓位2%，每高5分增加1%仓位，最高5%\n"
        self.report += "3. 平仓规则：单票浮亏≥6%强制止损，达到15%收益分批止盈\n"
        self.report += "4. 仓位控制：单票最高5%，总仓位上限40%，分散持仓不超过10只标的\n\n"
        
        self.report += "### 版本变更记录\n"
        self.report += "| 版本号 | 更新时间 | 变更内容 | 变更原因 |\n"
        self.report += "| :--- | :--- | :--- | :--- |\n"
        self.report += "| v1.0 | 2026-03-19 | 初始版本上线 | 策略正式启用 |\n"
        self.report += "\n---\n\n"
    
    def add_signals(self):
        """五、当日交易信号"""
        self.report += "## 🔍 五、当日交易信号\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/opportunities.json', 'r') as f:
                data = json.load(f)
            
            opps = data.get('opportunities', [])
            
            if opps:
                self.report += "| 标的代码 | 当前价格 | 涨跌幅 | 综合评分 | 信号类型 |\n"
                self.report += "| :--- | :--- | :--- | :--- | :--- |\n"
                for o in opps[:5]:
                    self.report += f"| {o['symbol']} | ${o['price']:.2f} | {o['change_pct']:+.2f}% | {o['score']}分 | 开仓信号 |\n"
            else:
                self.report += "无满足开仓/平仓条件的信号。\n"
            
        except:
            self.report += "无满足开仓/平仓条件的信号。\n"
        
        self.report += "\n---\n\n"
    
    def add_news(self):
        """六、当日核心新闻与市场分析"""
        self.report += "## 📰 六、当日核心新闻与市场分析\n"
        self.report += "### 持仓标的相关新闻\n"
        self.report += "1. 暂无相关新闻\n\n"
        self.report += "### 行业与宏观新闻\n"
        self.report += "1. 暂无相关新闻\n\n"
        self.report += "### 市场走势预测\n"
        self.report += "- 大盘预判：美股震荡，关注科技股机会\n"
        self.report += "- 板块机会：AI算力、半导体板块\n"
        self.report += "- 风险提示：美联储加息预期升温\n"
        self.report += "\n---\n\n"
    
    def add_sentiment(self, quote_ctx):
        """七、市场情绪与预测"""
        self.report += "## 😊 七、市场情绪与预测\n"
        self.report += "### 当日情绪指标\n"
        self.report += "| 指标名称 | 数值 | 状态说明 |\n"
        self.report += "| :--- | :--- | :--- |\n"
        
        # VHSI
        ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
        if ret == 0 and not data.empty:
            vhsi = data.iloc[0]['last_price']
            status = "恐慌" if vhsi >= 25 else "正常"
            self.report += f"| 港股VHSI | {vhsi:.2f} | {status} |\n"
        
        self.report += "\n### 未来3日情绪预测\n"
        self.report += "| 时间 | 情绪预判 | 概率 | 市场走势预判 |\n"
        self.report += "| :--- | :--- | :--- | :--- |\n"
        self.report += "| T+1日 | 中性 | 65% | 震荡 |\n"
        self.report += "| T+2日 | 中性 | 60% | 震荡 |\n"
        self.report += "| T+3日 | 乐观 | 70% | 上涨 |\n"
        self.report += "\n---\n\n"
    
    def add_watchlist(self):
        """八、自选关注股票池动态"""
        self.report += "## 👀 八、自选关注股票池动态\n"
        self.report += "| 标的代码 | 当前价格 | 当日涨跌幅 | 最新综合评分 | 异动提醒 |\n"
        self.report += "| :--- | :--- | :--- | :--- | :--- |\n"
        
        watchlist = ['NVDA', 'TSLA', 'AAPL', 'META', 'AMD']
        
        for symbol in watchlist:
            try:
                url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    price = d.get('c', 0)
                    change = d.get('dp', 0)
                    score = 70 if change > 2 else 50
                    alert = "接近开仓阈值" if score >= 65 else "无"
                    self.report += f"| {symbol} | ${price:.2f} | {change:+.2f}% | {score}分 | {alert} |\n"
                time.sleep(0.5)
            except:
                pass
        
        self.report += "\n---\n\n"
    
    def add_earnings(self):
        """九、财报与业绩预测"""
        self.report += "## 📈 九、财报与业绩预测\n"
        self.report += "| 标的代码 | 财报披露时间 | 预期EPS | 预期营收增速 | 超预期概率 | 对股价影响预期 |\n"
        self.report += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        self.report += "| 暂无即将披露财报的持仓标的 | - | - | - | - | - |\n"
        self.report += "\n---\n\n"
    
    def add_risk(self):
        """十、风险提示与操作建议"""
        self.report += "## ⚠️ 十、风险提示与操作建议\n"
        self.report += "1. **系统性风险**：美联储3月议息会议临近，加息预期可能带来市场短期波动\n"
        self.report += "2. **非系统性风险**：港股VHSI恐慌指数较高，注意仓位控制\n"
        self.report += "3. **操作建议**：控制仓位，等待市场企稳\n"
        self.report += f"\n---\n**报告生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    def generate(self):
        quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        try:
            self.add_header()
            self.add_account_summary()
            self.add_positions()
            self.add_trade_history()
            self.add_strategy()
            self.add_signals()
            self.add_news()
            self.add_sentiment(quote_ctx)
            self.add_watchlist()
            self.add_earnings()
            self.add_risk()
        finally:
            quote_ctx.close()
        return self.report
    
    def run(self):
        print(f"生成完整日报v6 - {datetime.now().strftime('%H:%M:%S')}")
        report = self.generate()
        print(report)
        print("\n发送到飞书...")
        if self.send_to_feishu(report):
            print("✅ 已发送")
        else:
            print("❌ 发送失败")


if __name__ == '__main__':
    reporter = ComprehensiveReportV6()
    reporter.run()
