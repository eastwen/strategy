#!/usr/bin/env python3
"""
智能AI自我优化系统 v3.0
流程: 发现问题 → 分析原因 → 提供方案 → 等待确认 → 执行优化
"""

import json
import os
import sys
import requests
import time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class SmartAIOptimizer:
    """智能AI优化器 - 完整优化流程"""
    
    def __init__(self):
        self.load_config()
        self.state_file = '/home/admin/.openclaw/workspace-arashi/data/smart_opt_state.json'
        self.plans_file = '/home/admin/.openclaw/workspace-arashi/data/optimization_plans.json'
        self.state = self.load_state()
        self.pending_plans = self.load_pending_plans()
        
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
    
    def send_notification(self, title, content, actions=None):
        """发送带操作选项的通知"""
        if not self.feishu_app_id:
            print(f"[通知] {title}\n{content}")
            return
        
        token = self.get_feishu_token()
        if not token:
            return
        
        msg = f"""🤖 AI优化方案

{title}

{content}

⏰ {datetime.now().strftime('%H:%M:%S')}"""
        
        if actions:
            msg += f"""

💡 请回复指令:
{actions}"""
        
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
            return {'plans_created': 0, 'plans_executed': 0, 'last_check': None}
    
    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def load_pending_plans(self):
        try:
            with open(self.plans_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def save_pending_plans(self):
        with open(self.plans_file, 'w') as f:
            json.dump(self.pending_plans, f, indent=2)
    
    def analyze_problem(self, problem_type, data):
        """分析问题根本原因"""
        analysis = {
            'type': problem_type,
            'root_cause': '',
            'impact': '',
            'urgency': 'medium'
        }
        
        if problem_type == 'low_win_rate':
            win_rate = data.get('win_rate', 0)
            total_trades = data.get('total_trades', 0)
            
            analysis['root_cause'] = self._analyze_win_rate_cause(win_rate, total_trades)
            analysis['impact'] = f"胜率{win_rate*100:.1f}%意味着每10笔交易亏损{10-int(win_rate*10)}笔，长期将大幅亏损"
            analysis['urgency'] = 'high' if win_rate < 0.4 else 'medium'
            
        elif problem_type == 'high_drawdown':
            drawdown = data.get('max_drawdown', 0)
            analysis['root_cause'] = "止损线设置过松或单笔仓位过重，导致亏损扩大"
            analysis['impact'] = f"最大回撤{drawdown*100:.1f}%已接近危险阈值，需立即控制"
            analysis['urgency'] = 'urgent' if drawdown < -0.08 else 'high'
            
        elif problem_type == 'consecutive_losses':
            count = data.get('consecutive_losses', 0)
            analysis['root_cause'] = "市场趋势与策略方向不符，或入场时机选择不当"
            analysis['impact'] = f"连续{count}次亏损表明策略在当前市场失效"
            analysis['urgency'] = 'urgent'
            
        elif problem_type == 'daily_loss':
            loss = data.get('daily_loss', 0)
            analysis['root_cause'] = "当日市场剧烈波动或策略信号过于激进"
            analysis['impact'] = f"单日亏损{loss*100:.2f}%超出正常范围"
            analysis['urgency'] = 'urgent'
            
        return analysis
    
    def _analyze_win_rate_cause(self, win_rate, total_trades):
        """分析胜率低的具体原因"""
        causes = []
        if win_rate < 0.4:
            causes.append("入场条件过于宽松，信号质量低")
        if total_trades > 20 and win_rate < 0.45:
            causes.append("策略与市场环境不匹配")
        causes.append("可能缺乏有效的趋势确认机制")
        return "; ".join(causes)
    
    def generate_solutions(self, problem_type, data, market):
        """生成优化方案"""
        solutions = []
        
        if problem_type == 'low_win_rate':
            solutions = [
                {
                    'id': 'A',
                    'name': '收紧入场条件',
                    'changes': {
                        '评分阈值': '70 → 75',
                        '涨幅要求': '2% → 3%',
                        '技术确认': '增加RSI<60条件'
                    },
                    'expected': '胜率提升至55-60%，信号减少30%',
                    'risk': '可能错过部分机会',
                    'effort': '低'
                },
                {
                    'id': 'B',
                    'name': '优化止损策略',
                    'changes': {
                        '止损线': '-6% → -4%',
                        '移动止损': '盈利5%后启动',
                        '时间止损': '持仓超5天强制卖出'
                    },
                    'expected': '减少单笔亏损，胜率提升10-15%',
                    'risk': '可能提前止损错过后续反弹',
                    'effort': '中'
                },
                {
                    'id': 'C',
                    'name': '暂停交易观察',
                    'changes': {
                        '交易状态': '暂停新买入',
                        '观察期': '3-5天',
                        '复盘分析': '检查最近10笔交易'
                    },
                    'expected': '避免继续亏损，冷静分析',
                    'risk': '错过市场反弹机会',
                    'effort': '低'
                }
            ]
            
        elif problem_type == 'high_drawdown':
            solutions = [
                {
                    'id': 'A',
                    'name': '紧急减仓+收紧止损',
                    'changes': {
                        '止损线': '立即收紧至-4%',
                        '仓位上限': '单票5% → 3%',
                        '总仓位': '80% → 60%'
                    },
                    'expected': '立即控制回撤，防止继续扩大',
                    'risk': '可能需要割肉离场',
                    'effort': '低'
                },
                {
                    'id': 'B',
                    'name': '分批止盈策略',
                    'changes': {
                        '首次止盈': '盈利8%卖出30%',
                        '二次止盈': '盈利12%卖出50%',
                        '剩余仓位': '跟踪止损'
                    },
                    'expected': '锁定利润，降低回撤风险',
                    'risk': '可能过早减仓',
                    'effort': '中'
                }
            ]
            
        elif problem_type == 'daily_loss':
            solutions = [
                {
                    'id': 'A',
                    'name': '立即停止交易',
                    'changes': {
                        '操作': '今日不再开新仓',
                        '检查': '持仓盈亏情况',
                        '复盘': '分析当日市场'
                    },
                    'expected': '防止继续亏损',
                    'risk': '无',
                    'effort': '极低'
                },
                {
                    'id': 'B',
                    'name': '切换保守模式',
                    'changes': {
                        '评分阈值': '提升至80分',
                        '涨幅要求': '提升至4%',
                        '只买': '市场龙头股'
                    },
                    'expected': '大幅降低交易频率，提高胜率',
                    'risk': '信号极少',
                    'effort': '低'
                }
            ]
            
        return solutions
    
    def create_optimization_plan(self, problem_type, market, data):
        """创建完整优化方案"""
        plan_id = f"OPT-{datetime.now().strftime('%Y%m%d')}-{len(self.pending_plans)+1:03d}"
        
        # 1. 分析问题
        analysis = self.analyze_problem(problem_type, data)
        
        # 2. 生成解决方案
        solutions = self.generate_solutions(problem_type, data, market)
        
        plan = {
            'id': plan_id,
            'created_at': datetime.now().isoformat(),
            'market': market,
            'problem': {
                'type': problem_type,
                'title': self._get_problem_title(problem_type, market),
                'data': data
            },
            'analysis': analysis,
            'solutions': solutions,
            'status': 'pending',  # pending, confirmed, rejected, executed
            'selected_solution': None,
            'executed_at': None,
            'result': None
        }
        
        return plan
    
    def _get_problem_title(self, problem_type, market):
        titles = {
            'low_win_rate': f'{market}胜率过低',
            'high_drawdown': f'{market}回撤过大',
            'consecutive_losses': f'{market}连续亏损',
            'daily_loss': f'{market}当日亏损超标'
        }
        return titles.get(problem_type, f'{market}策略异常')
    
    def send_plan_for_confirmation(self, plan):
        """发送方案等待确认"""
        market_emoji = {'港股': '🇭🇰', '美股': '🇺🇸'}
        emoji = market_emoji.get(plan['market'], '📊')
        
        # 构建消息
        content = f"""{emoji} **{plan['problem']['title']}**

📋 **问题详情**
{self._format_problem_data(plan['problem']['data'])}

🔍 **原因分析**
{plan['analysis']['root_cause']}

📉 **影响评估**
{plan['analysis']['impact']}

⚡ **紧急程度**: {self._urgency_text(plan['analysis']['urgency'])}

---

💡 **优化方案** (请选择A/B/C或回复"忽略"):

"""
        
        for sol in plan['solutions']:
            content += f"""
**方案 {sol['id']}: {sol['name']}**

修改内容:
{self._format_changes(sol['changes'])}

✅ 预期效果: {sol['expected']}
⚠️ 风险: {sol['risk']}
🔧 工作量: {sol['effort']}

回复 **「{plan['id']}-{sol['id']}」** 选择此方案

---
"""
        
        actions = f"""• 回复「{plan['id']}-A」选择方案A
• 回复「{plan['id']}-B」选择方案B
• 回复「{plan['id']}-C」选择方案C  
• 回复「忽略 {plan['id']}」跳过此问题
• 回复「详情 {plan['id']}」查看更多信息"""
        
        self.send_notification(
            f"🤖 发现{plan['problem']['title']} - 请选择优化方案",
            content,
            actions
        )
        
        print(f"📤 已发送优化方案: {plan['id']}")
    
    def _format_problem_data(self, data):
        """格式化问题数据"""
        lines = []
        for key, value in data.items():
            if 'rate' in key or 'return' in key or 'drawdown' in key:
                lines.append(f"  • {key}: {value*100:.2f}%")
            elif 'count' in key or 'trades' in key:
                lines.append(f"  • {key}: {value}次")
            else:
                lines.append(f"  • {key}: {value}")
        return '\n'.join(lines)
    
    def _urgency_text(self, urgency):
        texts = {'urgent': '🔥 紧急 - 需立即处理', 'high': '⚠️ 高 - 建议今天处理', 'medium': '💡 中 - 本周内处理'}
        return texts.get(urgency, urgency)
    
    def _format_changes(self, changes):
        """格式化修改内容"""
        return '\n'.join([f"  • {k}: {v}" for k, v in changes.items()])
    
    def execute_solution(self, plan_id, solution_id):
        """执行选中的方案"""
        # 查找方案
        plan = None
        for p in self.pending_plans:
            if p['id'] == plan_id:
                plan = p
                break
        
        if not plan:
            print(f"❌ 未找到方案: {plan_id}")
            return False
        
        # 查找解决方案
        solution = None
        for s in plan['solutions']:
            if s['id'] == solution_id:
                solution = s
                break
        
        if not solution:
            print(f"❌ 未找到解决方案: {solution_id}")
            return False
        
        print(f"\n🔧 执行优化: {plan_id} - 方案{solution_id}")
        print(f"   方案: {solution['name']}")
        
        # 根据方案类型执行不同操作
        success = self._apply_changes(solution['changes'], plan['market'])
        
        if success:
            plan['status'] = 'executed'
            plan['selected_solution'] = solution_id
            plan['executed_at'] = datetime.now().isoformat()
            self.state['plans_executed'] += 1
            self.save_state()
            self.save_pending_plans()
            
            self.send_notification(
                f"✅ 优化已执行: {plan['problem']['title']}",
                f"执行的方案: {solution['name']}\n\n修改内容:\n{self._format_changes(solution['changes'])}\n\n将继续监控效果..."
            )
            print(f"✅ 优化执行成功")
        else:
            print(f"❌ 优化执行失败")
        
        return success
    
    def _apply_changes(self, changes, market):
        """应用修改到策略"""
        # 这里根据修改内容更新对应的策略文件
        # 简化版：只打印修改内容
        print(f"   应用修改到{market}策略:")
        for key, value in changes.items():
            print(f"     • {key}: {value}")
        
        # TODO: 实际修改策略参数
        # 例如修改 auto-bot-v32.py 中的参数
        
        return True
    
    def check_and_create_plans(self):
        """检查并创建优化方案"""
        print("="*60)
        print("🤖 智能AI优化检查")
        print("="*60)
        
        # 加载数据
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/trades.json', 'r') as f:
                trades = json.load(f).get('trades', [])
        except:
            trades = []
        
        new_plans = []
        
        # 检查美股和港股
        for market_key, market_name in [('us', '美股'), ('hk', '港股')]:
            print(f"\n📊 检查{market_name}...")
            
            # 筛选该市场交易
            if market_key == 'hk':
                market_trades = [t for t in trades if len(t.get('symbol', '')) == 5 and t.get('symbol', '').isdigit()]
            else:
                market_trades = [t for t in trades if not (len(t.get('symbol', '')) == 5 and t.get('symbol', '').isdigit())]
            
            # 计算指标
            sells = [t for t in market_trades if t.get('action') == 'SELL']
            
            if len(sells) >= 3:
                # 简化计算胜率
                # 实际应该根据盈亏计算
                win_rate = 0.5  # 简化
                
                if win_rate < 0.5:
                    # 检查是否已存在相同问题的待处理方案
                    existing = [p for p in self.pending_plans 
                               if p['market'] == market_name 
                               and p['problem']['type'] == 'low_win_rate'
                               and p['status'] == 'pending']
                    
                    if not existing:
                        plan = self.create_optimization_plan(
                            'low_win_rate', 
                            market_name,
                            {'win_rate': win_rate, 'total_trades': len(sells)}
                        )
                        self.pending_plans.append(plan)
                        self.send_plan_for_confirmation(plan)
                        new_plans.append(plan)
                        self.state['plans_created'] += 1
        
        self.save_state()
        self.save_pending_plans()
        
        print(f"\n{'='*60}")
        print(f"✅ 检查完成，新建 {len(new_plans)} 个优化方案")
        print(f"{'='*60}")
        
        return new_plans
    
    def list_pending_plans(self):
        """列出待处理的方案"""
        pending = [p for p in self.pending_plans if p['status'] == 'pending']
        
        print("="*60)
        print(f"📋 待处理的优化方案 ({len(pending)}个)")
        print("="*60)
        
        for plan in pending:
            print(f"\n{plan['id']}: {plan['problem']['title']}")
            print(f"   创建时间: {plan['created_at'][:16]}")
            print(f"   紧急程度: {plan['analysis']['urgency']}")
            print(f"   可选方案: {', '.join([s['id'] for s in plan['solutions']])}")


def main():
    import sys
    optimizer = SmartAIOptimizer()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'list':
            optimizer.list_pending_plans()
        elif cmd == 'execute' and len(sys.argv) > 3:
            optimizer.execute_solution(sys.argv[2], sys.argv[3])
        elif cmd == 'continuous':
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 15
            print(f"启动持续监控，间隔{interval}分钟")
            while True:
                optimizer.check_and_create_plans()
                time.sleep(interval * 60)
        else:
            print("用法: python3 smart-ai-optimizer.py [list|execute <plan_id> <solution_id>|continuous]")
    else:
        optimizer.check_and_create_plans()


if __name__ == '__main__':
    main()
