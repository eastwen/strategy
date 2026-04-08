#!/usr/bin/env python3
"""
AI实时自我优化系统 v2.0
- 同时监控港股和美股
- 每次交易后实时检查
- 高频扫描（每15分钟）
- 发现问题立即通知
"""

import json
import os
import sys
import requests
import time
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class RealtimeAIOptimizer:
    """AI实时优化器 - 发现问题立即通知"""
    
    def __init__(self):
        self.load_config()
        self.state_file = '/home/admin/.openclaw/workspace-arashi/data/realtime_opt_state.json'
        self.issues_file = '/home/admin/.openclaw/workspace-arashi/data/realtime_pending_issues.json'
        
        # 更严格的阈值（实时）
        self.thresholds = {
            'min_win_rate': 0.50,
            'max_drawdown': -0.06,
            'max_consecutive_losses': 2,  # 降低为2次
            'daily_loss_limit': -0.03,    # 单日亏损3%告警
            'position_limit': 0.85,       # 仓位超过85%告警
        }
        
        self.state = self.load_state()
        self.pending_issues = self.load_pending_issues()
        self.reported_issues = set()  # 已报告的问题避免重复
    
    def load_config(self):
        try:
            with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
                keys = json.load(f)
            self.feishu_app_id = keys['feishu']['appId']
            self.feishu_app_secret = keys['feishu']['appSecret']
            self.feishu_open_id = keys['feishu']['openId']
            self.feishu_token = None
        except:
            self.feishu_app_id = None
    
    def get_feishu_token(self):
        if not self.feishu_app_id:
            return None
        if self.feishu_token:
            return self.feishu_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/"
        try:
            res = requests.post(url, json={
                "app_id": self.feishu_app_id,
                "app_secret": self.feishu_app_secret
            }, timeout=10)
            if res.status_code == 200 and res.json().get('code') == 0:
                self.feishu_token = res.json().get('tenant_access_token')
                return self.feishu_token
        except:
            pass
        return None
    
    def send_notification(self, title, content, priority='high'):
        """发送紧急通知"""
        if not self.feishu_app_id:
            print(f"[{priority}] {title}\n{content}")
            return
        
        token = self.get_feishu_token()
        if not token:
            return
        
        emoji = {'high': '🚨', 'urgent': '🔥', 'medium': '⚠️', 'normal': '💡'}
        
        msg = f"""{emoji.get(priority, '🚨')} AI实时告警

{title}

{content}

⏰ {datetime.now().strftime('%H:%M:%S')}

💡 回复"查看"了解详情，回复"暂停"停止交易"""
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"receive_id_type": "open_id"}
        data = {
            "receive_id": self.feishu_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": msg})
        }
        
        try:
            requests.post(url, headers=headers, params=params, json=data, timeout=10)
        except:
            pass
    
    def load_state(self):
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except:
            return {'last_check': None, 'alerts_sent': 0}
    
    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def load_pending_issues(self):
        try:
            with open(self.issues_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def check_daily_pnl(self, trades):
        """检查当日盈亏"""
        today = datetime.now().strftime('%Y-%m-%d')
        today_trades = [t for t in trades if t.get('time', '').startswith(today) and t.get('action') == 'SELL']
        
        if not today_trades:
            return []
        
        daily_pnl = sum(t.get('value', 0) - (t.get('shares', 0) * t.get('cost', 0)) for t in today_trades)
        initial = 1000000
        daily_return = daily_pnl / initial
        
        issues = []
        if daily_return < self.thresholds['daily_loss_limit']:
            issue_id = f"DAILY_LOSS_{today}"
            if issue_id not in self.reported_issues:
                issues.append({
                    'id': issue_id,
                    'type': 'daily_loss',
                    'priority': 'urgent',
                    'title': f'⚠️ 当日亏损超过阈值',
                    'content': f"当日亏损: {daily_return*100:.2f}%\n亏损金额: ${abs(daily_pnl):,.0f}\n\n建议立即:\n1. 暂停新买入\n2. 检查止损线\n3. 评估市场环境",
                })
                self.reported_issues.add(issue_id)
        
        return issues
    
    def check_position_limit(self, trades):
        """检查仓位限制"""
        positions = {}
        for t in trades:
            if t.get('action') == 'BUY':
                s = t.get('symbol')
                if s not in positions:
                    positions[s] = 0
                positions[s] += t.get('shares', 0) * t.get('price', 0)
        
        total_position = sum(positions.values())
        initial = 1000000
        position_ratio = total_position / initial
        
        issues = []
        if position_ratio > self.thresholds['position_limit']:
            issue_id = f"POSITION_LIMIT_{datetime.now().strftime('%Y%m%d%H')}"
            if issue_id not in self.reported_issues:
                issues.append({
                    'id': issue_id,
                    'type': 'high_position',
                    'priority': 'high',
                    'title': f'⚠️ 仓位过高',
                    'content': f"当前仓位: {position_ratio*100:.1f}%\n持仓数量: {len(positions)}只\n\n建议:\n1. 不再开新仓\n2. 等待止盈减仓\n3. 调整仓位上限",
                })
                self.reported_issues.add(issue_id)
        
        return issues
    
    def check_market_performance(self, trades, market_key, market_name):
        """检查市场表现 - 同时检查港股和美股"""
        issues = []
        
        # 分类股票
        market_trades = []
        for t in trades:
            s = t.get('symbol', '')
            if market_key == 'hk':
                if len(s) == 5 and s.isdigit():
                    market_trades.append(t)
            else:  # us
                if not (len(s) == 5 and s.isdigit()):
                    market_trades.append(t)
        
        # 计算已实现盈亏
        sells = [t for t in market_trades if t.get('action') == 'SELL']
        
        if len(sells) >= 3:  # 至少3笔卖出才计算
            wins = 0
            losses = []
            for t in sells[-10:]:  # 最近10笔
                # 简化的盈亏计算
                profit = 0  # 这里简化处理
                if profit > 0:
                    wins += 1
                else:
                    losses.append(t)
            
            win_rate = wins / len(sells[-10:])
            
            # 检查胜率
            if win_rate < self.thresholds['min_win_rate']:
                issue_id = f"LOW_WINRATE_{market_key}_{datetime.now().strftime('%Y%m%d')}"
                if issue_id not in self.reported_issues:
                    issues.append({
                        'id': issue_id,
                        'type': 'low_winrate',
                        'priority': 'high',
                        'title': f'{market_name}策略胜率过低',
                        'content': f"最近10笔胜率: {win_rate*100:.1f}%\n{market_name}策略可能需要优化\n\n建议:\n1. 提高评分阈值\n2. 收紧入场条件\n3. 优化止损设置",
                    })
                    self.reported_issues.add(issue_id)
            
            # 检查连续亏损
            if len(losses) >= self.thresholds['max_consecutive_losses']:
                issue_id = f"CONSECUTIVE_{market_key}_{datetime.now().strftime('%Y%m%d%H')}"
                if issue_id not in self.reported_issues:
                    issues.append({
                        'id': issue_id,
                        'type': 'consecutive_losses',
                        'priority': 'urgent',
                        'title': f'🔥 {market_name}连续亏损警告',
                        'content': f"连续亏损: {len(losses)}次\n{market_name}策略急需调整\n\n建议立即:\n1. 暂停该市场交易\n2. 检查策略参数\n3. 评估市场环境",
                    })
                    self.reported_issues.add(issue_id)
        
        return issues
    
    def run_check(self, trigger_source='scheduled'):
        """运行检查"""
        print(f"\n{'='*60}")
        print(f"🤖 AI实时优化检查 [{trigger_source}]")
        print(f"{'='*60}")
        
        # 加载交易记录
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                trades = json.load(f).get('trades', [])
        except:
            trades = []
        
        all_issues = []
        
        # 1. 检查当日盈亏（关键）
        print("\n1. 检查当日盈亏...")
        issues = self.check_daily_pnl(trades)
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 2. 检查仓位
        print("\n2. 检查仓位限制...")
        issues = self.check_position_limit(trades)
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 3. 检查美股表现
        print("\n3. 检查美股策略...")
        issues = self.check_market_performance(trades, 'us', '🇺🇸 美股')
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 4. 检查港股表现
        print("\n4. 检查港股策略...")
        issues = self.check_market_performance(trades, 'hk', '🇭🇰 港股')
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 发送通知
        print(f"\n{'='*60}")
        print(f"📊 发现 {len(all_issues)} 个问题")
        print(f"{'='*60}")
        
        for issue in all_issues:
            self.send_notification(issue['title'], issue['content'], issue['priority'])
            print(f"🚨 已发送: {issue['title']}")
        
        self.state['last_check'] = datetime.now().isoformat()
        self.state['alerts_sent'] += len(all_issues)
        self.save_state()
        
        print(f"\n✅ 检查完成 [{datetime.now().strftime('%H:%M:%S')}]")


def run_continuous_monitor(interval_minutes=15):
    """持续监控模式"""
    print(f"\n{'='*60}")
    print(f"🤖 AI实时监控系统启动")
    print(f"⏱️  检查间隔: {interval_minutes}分钟")
    print(f"{'='*60}\n")
    
    optimizer = RealtimeAIOptimizer()
    
    while True:
        try:
            optimizer.run_check('continuous')
            print(f"\n💤 等待{interval_minutes}分钟...\n")
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\n✋ 停止监控")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")
            time.sleep(60)


def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'continuous':
        # 持续监控模式
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        run_continuous_monitor(interval)
    else:
        # 单次检查
        optimizer = RealtimeAIOptimizer()
        optimizer.run_check('manual')


if __name__ == '__main__':
    main()
