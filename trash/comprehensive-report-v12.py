#!/usr/bin/env python3
"""
综合日报生成器 v11 - 飞书卡片表格版
支持交互式卡片，表格更美观
"""

import sys
import json
import requests
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext

class ComprehensiveReportV11:
    """综合日报生成器v11 - 飞书卡片版"""
    
    def __init__(self, us_mode=False):
        self.load_config()
        self.us_mode = us_mode
        self.account_data = {}
        self.positions = []
        self.trades = []
        self.signals = []
        self.sentiment = {}
    
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-stock/.api-keys.json', 'r') as f:
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
    
    def fetch_data(self):
        """获取所有数据"""
        # 获取交易数据
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/trades.json', 'r') as f:
                data = json.load(f)
            
            trades = data.get('trades', [])
            self.trades = trades[-10:]  # 最近10条
            
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
                    cash = t.get('cash', cash)
            
            total_position = sum(p['shares'] * p['cost'] for p in positions.values())
            total_asset = total_position + cash
            total_pnl = total_asset - initial
            total_pnl_pct = total_pnl / initial * 100 if initial > 0 else 0
            
            self.account_data = {
                'initial': initial,
                'total_asset': total_asset,
                'position_value': total_position,
                'cash': cash,
                'total_pnl': total_pnl,
                'total_pnl_pct': total_pnl_pct
            }
            
            # 获取持仓现价
            for symbol, pos in positions.items():
                try:
                    url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        d = r.json()
                        price = d.get('c', pos['cost'])
                        pnl_pct = (price - pos['cost']) / pos['cost'] * 100 if pos['cost'] > 0 else 0
                        self.positions.append({
                            'symbol': symbol,
                            'shares': pos['shares'],
                            'cost': pos['cost'],
                            'price': price,
                            'pnl_pct': pnl_pct
                        })
                    time.sleep(0.3)
                except:
                    self.positions.append({
                        'symbol': symbol,
                        'shares': pos['shares'],
                        'cost': pos['cost'],
                        'price': pos['cost'],
                        'pnl_pct': 0
                    })
            
        except Exception as e:
            print(f"获取交易数据失败: {e}")
            self.account_data = {
                'initial': 1000000,
                'total_asset': 1000000,
                'position_value': 0,
                'cash': 1000000,
                'total_pnl': 0,
                'total_pnl_pct': 0
            }
        
        # 获取信号数据
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/opportunities.json', 'r') as f:
                data = json.load(f)
            self.signals = data.get('opportunities', [])[:5]
        except:
            self.signals = []
        
        # 获取情绪数据
        try:
            quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            ret, data = quote_ctx.get_market_snapshot(['HK.800125'])
            if ret == 0 and not data.empty:
                vhsi = data.iloc[0]['last_price']
                self.sentiment['vhsi'] = vhsi
            quote_ctx.close()
        except:
            self.sentiment['vhsi'] = 20
    
    def build_card(self):
        """构建飞书卡片"""
        title = "🇺🇸 美股日报" if self.us_mode else "🇭🇰 港股日报"
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        # 盈亏颜色
        pnl_color = "green" if self.account_data['total_pnl'] >= 0 else "red"
        pnl_icon = "📈" if self.account_data['total_pnl'] >= 0 else "📉"
        
        elements = []
        
        # 1. 账户概览表格
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📊 账户概览**"
            }
        })
        
        account_table = {
            "tag": "table",
            "page_size": 10,
            "column_sizes": [2, 2, 1],
            "header": {
                "template": "blue",
                "values": [
                    {"text": "指标"},
                    {"text": "数值"},
                    {"text": "备注"}
                ]
            },
            "rows": []
        }
        
        rows_data = [
            ("初始资金", f"${self.account_data['initial']:,.0f}", "模拟盘本金"),
            ("总资产", f"${self.account_data['total_asset']:,.0f}", f"{self.account_data['total_pnl_pct']:+.1f}%"),
            ("持仓市值", f"${self.account_data['position_value']:,.0f}", f"{self.account_data['position_value']/self.account_data['total_asset']*100:.0f}%" if self.account_data['total_asset'] > 0 else "0%"),
            ("可用资金", f"${self.account_data['cash']:,.0f}", f"{self.account_data['cash']/self.account_data['total_asset']*100:.0f}%" if self.account_data['total_asset'] > 0 else "100%"),
        ]
        
        for label, value, note in rows_data:
            account_table["rows"].append({
                "values": [
                    {"text": label},
                    {"text": value},
                    {"text": note}
                ]
            })
        
        elements.append(account_table)
        
        # 2. 当前持仓表格
        if self.positions:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"\n**📦 当前持仓**"
                }
            })
            
            position_table = {
                "tag": "table",
                "page_size": 10,
                "column_sizes": [1, 1, 1, 1, 1],
                "header": {
                    "template": "blue",
                    "values": [
                        {"text": "标的"},
                        {"text": "数量"},
                        {"text": "成本"},
                        {"text": "现价"},
                        {"text": "盈亏"}
                    ]
                },
                "rows": []
            }
            
            for pos in self.positions[:5]:
                pnl_text = f"{pos['pnl_pct']:+.1f}%"
                position_table["rows"].append({
                    "values": [
                        {"text": pos['symbol']},
                        {"text": f"{pos['shares']}股"},
                        {"text": f"${pos['cost']:.2f}"},
                        {"text": f"${pos['price']:.2f}"},
                        {"text": pnl_text}
                    ]
                })
            
            elements.append(position_table)
        
        # 3. 最近交易
        if self.trades:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"\n**📜 最近交易**"
                }
            })
            
            trade_table = {
                "tag": "table",
                "page_size": 10,
                "column_sizes": [1, 1, 1, 1, 1],
                "header": {
                    "template": "wathet",
                    "values": [
                        {"text": "时间"},
                        {"text": "标的"},
                        {"text": "方向"},
                        {"text": "数量"},
                        {"text": "价格"}
                    ]
                },
                "rows": []
            }
            
            for t in self.trades[-5:]:
                time_str = t.get('time', '')[-12:-7] if len(t.get('time', '')) > 5 else t.get('time', '')
                trade_table["rows"].append({
                    "values": [
                        {"text": time_str},
                        {"text": t['symbol']},
                        {"text": "买入" if t['action'] == 'BUY' else "卖出"},
                        {"text": f"{t['shares']}股"},
                        {"text": f"${t['price']:.2f}"}
                    ]
                })
            
            elements.append(trade_table)
        
        # 4. 交易信号
        if self.signals:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"\n**🎯 交易信号**"
                }
            })
            
            signal_table = {
                "tag": "table",
                "page_size": 10,
                "column_sizes": [2, 1, 1],
                "header": {
                    "template": "green",
                    "values": [
                        {"text": "标的"},
                        {"text": "涨幅"},
                        {"text": "评分"}
                    ]
                },
                "rows": []
            }
            
            for s in self.signals:
                signal_table["rows"].append({
                    "values": [
                        {"text": s['symbol']},
                        {"text": f"{s['change_pct']:+.1f}%"},
                        {"text": f"{s['score']}分"}
                    ]
                })
            
            elements.append(signal_table)
        
        # 5. 市场情绪
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"\n**🌡️ 市场情绪**"
            }
        })
        
        vhsi = self.sentiment.get('vhsi', 20)
        status = "恐慌" if vhsi >= 25 else ("正常" if vhsi >= 18 else "平静")
        status_color = "red" if vhsi >= 25 else ("blue" if vhsi >= 18 else "green")
        
        sentiment_table = {
            "tag": "table",
            "page_size": 10,
            "column_sizes": [2, 2, 1],
            "header": {
                "template": "purple",
                "values": [
                    {"text": "指标"},
                    {"text": "数值"},
                    {"text": "状态"}
                ]
            },
            "rows": [
                {
                    "values": [
                        {"text": "VHSI"},
                        {"text": f"{vhsi:.1f}"},
                        {"text": status}
                    ]
                }
            ]
        }
        
        elements.append(sentiment_table)
        
        # 6. 策略说明（折叠）
        elements.append({
            "tag": "hr"
        })
        
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"策略：评分≥70分开仓 | 止损-6% | 止盈+15% | 单票≤5% | 总仓位≤40%"
                },
                {
                    "tag": "plain_text",
                    "content": f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"
                }
            ]
        })
        
        # 构建完整卡片
        card = {
            "type": "template",
            "data": {
                "template_id": "AAqk6NRdIkvG",  # 基础卡片模板
                "template_variable": {
                    "title": f"{title} {date_str}",
                    "elements": elements
                }
            }
        }
        
        # 如果模板不可用，使用自定义卡片
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{title} {date_str} {pnl_icon} {self.account_data['total_pnl_pct']:+.1f}%"
                },
                "template": pnl_color
            },
            "elements": elements
        }
        
        return card
    
    def send_to_feishu(self, card):
        """发送飞书卡片"""
        if not self.feishu_token:
            if not self.get_feishu_token():
                return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.feishu_token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "interactive",
            "content": json.dumps(card)
        }
        
        res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        
        result = res.json() if res.status_code == 200 else {}
        print(f"API响应: {json.dumps(result, ensure_ascii=False)[:500]}")
        
        if res.status_code == 200 and result.get('code') == 0:
            return True
        else:
            print(f"错误: {result.get('msg', '未知错误')}")
            # 如果卡片发送失败，回退到纯文本
            return self.send_text_fallback()
    
    def send_text_fallback(self):
        """回退到纯文本发送"""
        content = f"""# {'美股' if self.us_mode else '港股'}日报 {datetime.now().strftime('%Y-%m-%d')}

## 📊 账户概览
- 总资产: ${self.account_data['total_asset']:,.0f}
- 持仓: ${self.account_data['position_value']:,.0f}
- 现金: ${self.account_data['cash']:,.0f}
- 盈亏: {self.account_data['total_pnl_pct']:+.1f}%

## 📦 当前持仓
{chr(10).join([f"- {p['symbol']}: {p['shares']}股, 盈亏 {p['pnl_pct']:+.1f}%" for p in self.positions[:5]]) if self.positions else '暂无持仓'}

## 🎯 交易信号
{chr(10).join([f"- {s['symbol']}: {s['change_pct']:+.1f}%, 评分 {s['score']}" for s in self.signals]) if self.signals else '暂无信号'}

生成时间: {datetime.now().strftime('%H:%M')}
"""
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.feishu_token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": content})
        }
        
        res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        return res.status_code == 200 and res.json().get('code') == 0
    
    def run(self):
        print("📊 获取数据...")
        self.fetch_data()
        
        print("📝 构建卡片...")
        card = self.build_card()
        
        if '--no-send' not in sys.argv:
            print("📤 发送到飞书...")
            if self.send_to_feishu(card):
                print("✅ 已发送")
            else:
                print("❌ 发送失败")
        else:
            print("📤 已跳过发送（--no-send）")


if __name__ == '__main__':
    us_mode = '--us' in sys.argv
    reporter = ComprehensiveReportV11(us_mode=us_mode)
    reporter.run()
