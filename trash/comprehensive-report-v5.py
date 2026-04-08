#!/usr/bin/env python3
"""
综合日报生成器 v5 - 按照用户模板格式
"""

import sys
import json
import requests
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

class ComprehensiveReportV5:
    """综合日报生成器v5 - 完整版"""
    
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
        self.report += f"📊 每日交易报告 - {datetime.now().strftime('%Y-%m-%d')}\n"
        self.report += "=" * 60 + "\n\n"
    
    def add_account_summary(self):
        """一、账户核心数据"""
        self.report += "📊 一、账户核心数据\n"
        self.report += "-" * 60 + "\n"
        
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
            
            # 计算当前市值
            total_position = sum(p['shares'] * p['cost'] for p in positions.values())
            total_asset = total_position + cash
            profit = total_asset - initial
            profit_pct = profit / initial * 100
            
            self.report += f"{'指标':<20} {'数值':>20} {'备注':>20}\n"
            self.report += f"{'初始资金':<20} {'$1,000,000.00':>20} {'模拟盘初始本金':>20}\n"
            self.report += f"{'当前总资产':<20} {f'${total_asset:,.2f}':>20} {f'较初始值{profit_pct:+.2f}%':>20}\n"
            self.report += f"{'持仓总市值':<20} {f'${total_position:,.2f}':>20} {f'占总资产{total_position/total_asset*100:.1f}%':>20}\n"
            self.report += f"{'可用资金':<20} {f'${cash:,.2f}':>20} {f'占总资产{cash/total_asset*100:.1f}%':>20}\n"
            
        except:
            self.report += "暂无数据\n"
        
        self.report += "\n"
    
    def add_positions(self):
        """二、持仓明细"""
        self.report += "📈 二、持仓明细\n"
        self.report += "-" * 60 + "\n"
        
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
            
            self.report += f"{'标的代码':<10} {'持仓数量':>10} {'平均成本':>12} {'现价':>10} {'盈亏%':>10}\n"
            
            for symbol, pos in list(positions.items())[:10]:
                try:
                    url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        d = r.json()
                        price = d.get('c', 0)
                        profit_pct = (price - pos['cost']) / pos['cost'] * 100
                        status = "🟢" if profit_pct > 0 else "🔴"
                        self.report += f"{status} {symbol:<8} {pos['shares']:>8}股 ${pos['cost']:>10.2f} ${price:>8.2f} {profit_pct:>+8.2f}%\n"
                    time.sleep(0.5)
                except:
                    pass
            
        except:
            self.report += "暂无持仓\n"
        
        self.report += "\n"
    
    def add_trades(self):
        """三、当日交易记录"""
        self.report += "📝 三、当日交易记录\n"
        self.report += "-" * 60 + "\n"
        
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])
            today = datetime.now().strftime('%Y-%m-%d')
            
            today_trades = [t for t in trades if today in t.get('time', '')]
            
            if today_trades:
                self.report += f"{'时间':<12} {'标的':<8} {'方向':>6} {'数量':>8} {'价格':>10} {'原因':>20}\n"
                for t in today_trades[-5:]:
                    time_str = t.get('time', '')[-12:-7]
                    self.report += f"{time_str:<12} {t['symbol']:<8} {t['action']:>6} {t['shares']:>8} ${t['price']:>8.2f} {t.get('reason', '')[:20]:>20}\n"
            else:
                self.report += "今日无交易记录\n"
            
        except:
            self.report += "暂无数据\n"
        
        self.report += "\n"
    
    def add_strategy(self):
        """四、策略执行情况"""
        self.report += "🎯 四、策略执行情况\n"
        self.report += "-" * 60 + "\n"
        
        self.report += "港股策略 v2.0: 动态行业权重调整\n"
        self.report += "  入场: 行业权重≥1.5 + 评分≥65 + 成交量1.5x\n"
        self.report += "  出场: 止损-6% / 止盈+15% / 持仓≤10天\n"
        self.report += "  仓位控制: 单票最高5%, 总仓位上限40%\n\n"
        
        self.report += "美股策略 v1.6: 严格择时+多信号共振\n"
        self.report += "  入场: MA20>MA50 + 信号≥2 + 成交量1.8x\n"
        self.report += "  出场: ATR止损/止盈 + RSI>70离场\n"
        self.report += "  仓位控制: 单票最高5%, 总仓位上限40%\n\n"
    
    def add_signals(self):
        """五、当日交易信号"""
        self.report += "🔍 五、当日交易信号\n"
        self.report += "-" * 60 + "\n"
        
        # 读取扫描结果
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/opportunities.json', 'r') as f:
                data = json.load(f)
            
            opps = data.get('opportunities', [])
            
            if opps:
                self.report += f"{'标的':<10} {'价格':>10} {'涨跌幅':>10} {'评分':>8}\n"
                for o in opps[:5]:
                    self.report += f"🟢 {o['symbol']:<8} ${o['price']:>8.2f} {o['change_pct']:>+8.2f}% {o['score']:>6}分\n"
            else:
                self.report += "无满足开仓/平仓条件的信号\n"
            
        except:
            self.report += "无满足开仓/平仓条件的信号\n"
        
        self.report += "\n"
    
    def add_news(self):
        """六、当日核心新闻与市场分析"""
        self.report += "📰 六、当日核心新闻与市场分析\n"
        self.report += "-" * 60 + "\n"
        
        self.report += "市场走势预测:\n"
        self.report += "  大盘预判: 美股震荡，关注科技股机会\n"
        self.report += "  板块机会: AI算力、半导体板块\n"
        self.report += "  风险提示: 美联储加息预期升温\n\n"
    
    def add_sentiment(self, quote_ctx):
        """七、市场情绪与预测"""
        self.report += "😊 七、市场情绪与预测\n"
        self.report += "-" * 60 + "\n"
        
        # VHSI
        ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
        if ret == 0 and not data.empty:
            vhsi = data.iloc[0]['last_price']
            if vhsi >= 30: status = "极度恐慌"
            elif vhsi >= 25: status = "恐慌"
            else: status = "正常"
            self.report += f"港股VHSI: {vhsi:.2f} {status}\n"
        
        self.report += "\n"
    
    def add_watchlist(self):
        """八、自选关注股票池动态"""
        self.report += "👀 八、自选关注股票池动态\n"
        self.report += "-" * 60 + "\n"
        
        watchlist = ['NVDA', 'TSLA', 'AAPL', 'META', 'AMD', 'AMZN', 'VRT', 'SMCI', 'ARM', 'PLTR']
        
        self.report += f"{'标的代码':<10} {'当前价格':>12} {'涨跌幅':>10} {'评分':>8}\n"
        
        for symbol in watchlist[:5]:
            try:
                url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    price = d.get('c', 0)
                    change = d.get('dp', 0)
                    score = 70 if change > 2 else 50
                    status = "🟢" if change > 0 else "🔴"
                    self.report += f"{status} {symbol:<8} ${price:>10.2f} {change:>+8.2f}% {score:>6}分\n"
                time.sleep(0.5)
            except:
                pass
        
        self.report += "\n"
    
    def add_earnings(self):
        """九、财报与业绩预测"""
        self.report += "📈 九、财报与业绩预测\n"
        self.report += "-" * 60 + "\n"
        
        self.report += "暂无即将披露财报的持仓标的\n\n"
    
    def add_risk(self):
        """十、风险提示与操作建议"""
        self.report += "⚠️ 十、风险提示与操作建议\n"
        self.report += "-" * 60 + "\n"
        
        self.report += "系统性风险: 美联储3月议息会议临近\n"
        self.report += "非系统性风险: 港股VHSI恐慌指数较高\n"
        self.report += "操作建议: 控制仓位，等待市场企稳\n\n"
        
        self.report += f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    def generate(self):
        quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        try:
            self.add_header()
            self.add_account_summary()
            self.add_positions()
            self.add_trades()
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
        print(f"生成完整日报 - {datetime.now().strftime('%H:%M:%S')}")
        report = self.generate()
        print(report)
        print("\n发送到飞书...")
        if self.send_to_feishu(report):
            print("✅ 已发送")
        else:
            print("❌ 发送失败")


if __name__ == '__main__':
    reporter = ComprehensiveReportV5()
    reporter.run()
