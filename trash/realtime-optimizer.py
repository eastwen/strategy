#!/usr/bin/env python3
"""
实时自我优化系统 v1.0 - 修复版
- 实时监控策略表现
- 自动计算胜率、收益率、回撤
- 触发优化时立即通知
"""

import json
import sys
import requests
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class RealtimeOptimizer:
    """实时自我优化器"""
    
    def __init__(self):
        self.load_config()
        
        # 优化触发阈值
        self.thresholds = {
            'min_win_rate': 0.50,
            'min_daily_return': 0.005,
            'max_drawdown': -0.06,
            'max_consecutive_losses': 3,
            'min_signals_per_week': 3,
        }
        
        self.status_file = '/home/admin/.openclaw/workspace-arashi/data/strategy_performance.json'
        self.trades_file = '/home/admin/.openclaw/workspace-arashi/data/trades.json'
        
        self.performance = self.load_performance()
        
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            keys = json.load(f)
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
    
    def send_notification(self, title, content, urgency='normal'):
        token = self.get_feishu_token()
        if not token:
            print("❌ 无法获取飞书token")
            return False
        
        urgency_emoji = {"urgent": "🚨", "warning": "⚠️", "normal": "ℹ️"}
        emoji = urgency_emoji.get(urgency, "ℹ️")
        
        msg = f"""{emoji} {title}

{content}

时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": msg})
        }
        
        try:
            res = requests.post(url, headers=headers, params=params, json=data, timeout=10)
            return res.status_code == 200
        except Exception as e:
            print(f"❌ 发送通知失败: {e}")
            return False
    
    def load_trades(self):
        try:
            with open(self.trades_file, 'r') as f:
                data = json.load(f)
            return data.get('trades', [])
        except:
            return []
    
    def load_performance(self):
        try:
            with open(self.status_file, 'r') as f:
                return json.load(f)
        except:
            return {
                'hk_strategy': {'trades': [], 'win_rate': 0, 'total_return': 0, 'max_drawdown': 0, 'last_update': datetime.now().isoformat()},
                'us_strategy': {'trades': [], 'win_rate': 0, 'total_return': 0, 'max_drawdown': 0, 'last_update': datetime.now().isoformat()}
            }
    
    def save_performance(self):
        with open(self.status_file, 'w') as f:
            json.dump(self.performance, f, indent=2)
    
    def classify_symbol(self, symbol):
        if not symbol:
            return 'us_strategy'
        if len(symbol) == 5 and symbol.isdigit():
            return 'hk_strategy'
        return 'us_strategy'
    
    def calculate_performance(self, trades, market_key):
        """计算策略表现 - 支持仅持仓"""
        if not trades:
            return None
        
        market_trades = [t for t in trades if self.classify_symbol(t.get('symbol', '')) == market_key]
        
        if not market_trades:
            return None
        
        market_trades.sort(key=lambda x: x.get('time', ''))
        
        positions = {}
        completed_trades = []
        
        for trade in market_trades:
            symbol = trade.get('symbol')
            action = trade.get('action')
            shares = trade.get('shares', 0)
            price = trade.get('price', 0)
            
            if action == 'BUY':
                if symbol not in positions:
                    positions[symbol] = {'shares': 0, 'total_cost': 0}
                
                positions[symbol]['shares'] += shares
                positions[symbol]['total_cost'] += shares * price
                positions[symbol]['avg_cost'] = positions[symbol]['total_cost'] / positions[symbol]['shares']
                
            elif action == 'SELL':
                if symbol in positions and positions[symbol]['shares'] > 0:
                    avg_cost = positions[symbol]['avg_cost']
                    profit = (price - avg_cost) * shares
                    completed_trades.append({'profit': profit, 'time': trade.get('time')})
                    positions[symbol]['shares'] -= shares
                    positions[symbol]['total_cost'] = positions[symbol]['shares'] * avg_cost
        
        initial_capital = 1000000
        total_trades = len(completed_trades)
        
        # 计算持仓统计
        active_positions = {s: p for s, p in positions.items() if p['shares'] > 0}
        position_count = len(active_positions)
        position_cost = sum(p['total_cost'] for p in active_positions.values())
        
        if total_trades == 0:
            # 仅持仓状态
            return {
                'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'total_return': 0, 'max_drawdown': 0, 'consecutive_losses': 0,
                'max_consecutive_losses': 0, 'total_profit': 0,
                'position_count': position_count, 'position_cost': position_cost,
                'status': 'holding_only', 'last_update': datetime.now().isoformat()
            }
        
        wins = sum(1 for t in completed_trades if t['profit'] > 0)
        losses = total_trades - wins
        win_rate = wins / total_trades
        realized_profit = sum(t['profit'] for t in completed_trades)
        total_return = realized_profit / initial_capital
        
        # 计算连续亏损
        consecutive_losses = 0
        max_consecutive = 0
        for trade in sorted(completed_trades, key=lambda x: x['time']):
            if trade['profit'] < 0:
                consecutive_losses += 1
                max_consecutive = max(max_consecutive, consecutive_losses)
            else:
                consecutive_losses = 0
        
        # 计算最大回撤
        cumulative = 0
        peak = 0
        max_drawdown = 0
        for trade in sorted(completed_trades, key=lambda x: x['time']):
            cumulative += trade['profit']
            if cumulative > peak:
                peak = cumulative
            drawdown = cumulative - peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        max_drawdown_pct = max_drawdown / initial_capital
        
        return {
            'total_trades': total_trades, 'wins': wins, 'losses': losses,
            'win_rate': win_rate, 'total_return': total_return,
            'max_drawdown': max_drawdown_pct, 'consecutive_losses': 0,
            'max_consecutive_losses': max_consecutive, 'total_profit': realized_profit,
            'position_count': position_count, 'position_cost': position_cost,
            'status': 'active', 'last_update': datetime.now().isoformat()
        }
    
    def check_optimization_needed(self, market_key, perf):
        issues = []
        if not perf:
            return issues, 'normal'
        
        if perf.get('win_rate', 0) < self.thresholds['min_win_rate'] and perf.get('total_trades', 0) > 5:
            issues.append(f"胜率{perf['win_rate']*100:.1f}%低于{self.thresholds['min_win_rate']*100}%")
        
        if perf.get('total_return', 0) < -0.05:
            issues.append(f"总收益为负({perf['total_return']*100:.2f}%)")
        
        if perf.get('max_drawdown', 0) < self.thresholds['max_drawdown']:
            issues.append(f"最大回撤{perf['max_drawdown']*100:.1f}%超过阈值")
        
        if perf.get('max_consecutive_losses', 0) >= self.thresholds['max_consecutive_losses']:
            issues.append(f"连续亏损{perf['max_consecutive_losses']}次")
        
        urgency = 'urgent' if any('回撤' in i or '连续' in i for i in issues) else 'warning' if issues else 'normal'
        return issues, urgency
    
    def run_check(self):
        print("="*60)
        print("🔍 实时策略优化检查")
        print("="*60)
        
        trades = self.load_trades()
        print(f"\n📊 交易记录: {len(trades)}笔")
        
        for market_key in ['hk_strategy', 'us_strategy']:
            market_name = '🇭🇰 港股' if market_key == 'hk_strategy' else '🇺🇸 美股'
            print(f"\n{market_name}:")
            
            perf = self.calculate_performance(trades, market_key)
            
            if perf:
                print(f"  交易: {perf['total_trades']}笔")
                print(f"  胜率: {perf['win_rate']*100:.1f}%")
                print(f"  收益: {perf['total_return']*100:.2f}%")
                print(f"  回撤: {perf['max_drawdown']*100:.2f}%")
                print(f"  持仓: {perf.get('position_count', 0)}只")
                
                self.performance[market_key].update(perf)
                
                issues, urgency = self.check_optimization_needed(market_key, perf)
                
                if issues:
                    print(f"  ⚠️ 问题: {', '.join(issues)}")
                    # 发送通知
                    content = f"发现的问题:\n" + "\n".join(f"• {i}" for i in issues)
                    self.send_notification(f"{market_name} 需要优化！", content, urgency)
                else:
                    print(f"  ✅ 正常")
            else:
                print(f"  ℹ️ 无数据")
        
        self.save_performance()
        print(f"\n💾 已保存")
        print("="*60)


def main():
    optimizer = RealtimeOptimizer()
    optimizer.run_check()


if __name__ == '__main__':
    main()
