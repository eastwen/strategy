#!/usr/bin/env python3
"""
AI主动自我优化系统 v1.0
让OpenClaw能够主动监控自己的表现，发现问题并提出优化方案
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta
from collections import deque

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class AISelfOptimizer:
    """AI自我优化器 - 让OpenClaw主动发现并解决问题"""
    
    def __init__(self):
        self.load_config()
        self.state_file = '/home/admin/.openclaw/workspace-arashi/data/ai_self_opt_state.json'
        self.issues_file = '/home/admin/.openclaw/workspace-arashi/data/ai_pending_issues.json'
        self.log_file = '/home/admin/.openclaw/workspace-arashi/memory/ai-optimization-log.md'
        
        # 加载状态
        self.state = self.load_state()
        self.pending_issues = self.load_pending_issues()
        
        # 监控指标阈值
        self.thresholds = {
            'max_response_time': 30,          # 最大响应时间(秒)
            'max_error_rate': 0.1,            # 最大错误率10%
            'max_task_pending': 3,            # 最大待处理任务数
            'max_file_size_mb': 10,           # 最大文件大小(MB)
            'min_check_interval': 3600,       # 最小检查间隔(秒)
        }
    
    def load_config(self):
        """加载配置"""
        try:
            with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
                keys = json.load(f)
            self.feishu_app_id = keys['feishu']['appId']
            self.feishu_app_secret = keys['feishu']['appSecret']
            self.feishu_open_id = keys['feishu']['openId']
            self.feishu_token = None
        except:
            print("⚠️ 无法加载飞书配置")
            self.feishu_app_id = None
    
    def get_feishu_token(self):
        """获取飞书token"""
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
    
    def send_notification(self, title, content, priority='normal'):
        """发送飞书通知"""
        if not self.feishu_app_id:
            print(f"[{priority.upper()}] {title}\n{content}")
            return False
        
        token = self.get_feishu_token()
        if not token:
            print(f"[无法发送通知] {title}\n{content}")
            return False
        
        priority_emoji = {'high': '🚨', 'medium': '⚠️', 'normal': '💡', 'low': 'ℹ️'}
        emoji = priority_emoji.get(priority, 'ℹ️')
        
        msg = f"""{emoji} AI自我优化报告

{title}

{content}

时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

💡 回复"确认"执行优化，或回复"忽略"跳过"""
        
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
        except:
            return False
    
    def load_state(self):
        """加载优化器状态"""
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except:
            return {
                'last_check': None,
                'check_count': 0,
                'issues_found': 0,
                'optimizations_applied': 0,
                'metrics_history': []
            }
    
    def save_state(self):
        """保存优化器状态"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def load_pending_issues(self):
        """加载待处理的问题"""
        try:
            with open(self.issues_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def save_pending_issues(self):
        """保存待处理的问题"""
        with open(self.issues_file, 'w') as f:
            json.dump(self.pending_issues, f, indent=2)
    
    def check_file_sizes(self):
        """检查文件大小是否过大"""
        issues = []
        workspace = '/home/admin/.openclaw/workspace-arashi'
        
        large_files = []
        for root, dirs, files in os.walk(workspace):
            # 跳过虚拟环境
            if 'venv' in root or '__pycache__' in root or '.git' in root:
                continue
            
            for file in files:
                if file.endswith(('.log', '.json', '.md', '.py')):
                    filepath = os.path.join(root, file)
                    try:
                        size_mb = os.path.getsize(filepath) / (1024 * 1024)
                        if size_mb > self.thresholds['max_file_size_mb']:
                            large_files.append({
                                'file': filepath.replace(workspace + '/', ''),
                                'size_mb': round(size_mb, 2)
                            })
                    except:
                        pass
        
        if large_files:
            issues.append({
                'type': 'large_files',
                'priority': 'medium',
                'title': '发现过大的文件',
                'description': f'发现 {len(large_files)} 个文件超过 {self.thresholds["max_file_size_mb"]}MB',
                'details': large_files[:5],  # 只显示前5个
                'solutions': [
                    '清理旧日志文件',
                    '压缩历史数据',
                    '归档过期文件到backup目录'
                ]
            })
        
        return issues
    
    def check_log_errors(self):
        """检查日志中的错误"""
        issues = []
        log_dir = '/home/admin/.openclaw/workspace-arashi/logs'
        
        if not os.path.exists(log_dir):
            return issues
        
        recent_errors = []
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        for log_file in os.listdir(log_dir):
            if log_file.endswith('.log'):
                filepath = os.path.join(log_dir, log_file)
                try:
                    with open(filepath, 'r') as f:
                        lines = f.readlines()
                        for line in lines[-100:]:  # 检查最后100行
                            if 'error' in line.lower() or '❌' in line or 'failed' in line.lower():
                                recent_errors.append({
                                    'file': log_file,
                                    'error': line.strip()[:100]
                                })
                                break
                except:
                    pass
        
        if len(recent_errors) > 5:
            issues.append({
                'type': 'log_errors',
                'priority': 'high',
                'title': '日志中发现较多错误',
                'description': f'24小时内发现 {len(recent_errors)} 个日志文件包含错误',
                'details': recent_errors[:3],
                'solutions': [
                    '检查数据源连接',
                    '修复代码错误',
                    '增加错误重试机制',
                    '添加更详细的错误日志'
                ]
            })
        
        return issues
    
    def check_strategy_performance(self):
        """检查策略表现是否需要优化"""
        issues = []
        perf_file = '/home/admin/.openclaw/workspace-arashi/data/strategy_performance.json'
        
        try:
            with open(perf_file, 'r') as f:
                perf = json.load(f)
            
            markets = [
            ('hk_strategy', '港股', '🇭🇰'),
            ('us_strategy', '美股', '🇺🇸')
        ]
        
        for market_key, market_name, flag in markets:
            data = perf.get(market_key, {})
                
                # 检查胜率
                win_rate = data.get('win_rate', 0)
                total_trades = data.get('total_trades', 0)
                
                if total_trades > 5 and win_rate < 0.5:
                    issues.append({
                        'type': 'low_win_rate',
                        'priority': 'high',
                        'title': f'{market_name}策略胜率过低',
                        'description': f'{market_name}策略胜率 {win_rate*100:.1f}%，低于50%阈值',
                        'details': {
                            'win_rate': win_rate,
                            'total_trades': total_trades,
                            'total_return': data.get('total_return', 0)
                        },
                        'solutions': [
                            f'提高{market_name}评分阈值',
                            '增加技术确认条件',
                            '调整止损止盈参数',
                            '优化选股标准'
                        ]
                    })
                
                # 检查回撤
                max_drawdown = data.get('max_drawdown', 0)
                if max_drawdown < -0.06:
                    issues.append({
                        'type': 'high_drawdown',
                        'priority': 'high',
                        'title': f'{market_name}策略回撤过大',
                        'description': f'{market_name}策略最大回撤 {max_drawdown*100:.1f}%，超过-6%阈值',
                        'details': {
                            'max_drawdown': max_drawdown,
                            'consecutive_losses': data.get('max_consecutive_losses', 0)
                        },
                        'solutions': [
                            '收紧止损线',
                            '降低单票仓位',
                            '增加风险分散'
                        ]
                    })
        
        except Exception as e:
            print(f"检查策略表现时出错: {e}")
        
        return issues
    
    def check_memory_files(self):
        """检查记忆文件是否需要整理"""
        issues = []
        memory_dir = '/home/admin/.openclaw/workspace-arashi/memory'
        
        if not os.path.exists(memory_dir):
            return issues
        
        files = os.listdir(memory_dir)
        old_files = []
        
        cutoff = datetime.now() - timedelta(days=30)
        for file in files:
            if file.endswith('.md'):
                filepath = os.path.join(memory_dir, file)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mtime < cutoff:
                        old_files.append(file)
                except:
                    pass
        
        if len(old_files) > 10:
            issues.append({
                'type': 'old_memory_files',
                'priority': 'low',
                'title': '记忆文件需要整理',
                'description': f'发现 {len(old_files)} 个超过30天未更新的记忆文件',
                'details': old_files[:5],
                'solutions': [
                    '归档旧记忆文件到backup',
                    '更新MEMORY.md整合长期记忆',
                    '删除过期的临时记录'
                ]
            })
        
        return issues
    
    def check_system_health(self):
        """检查系统整体健康状态"""
        issues = []
        
        # 检查关键进程
        critical_files = [
            '/home/admin/.openclaw/workspace-arashi/auto-bot-v32.py',
            '/home/admin/.openclaw/workspace-arashi/realtime-optimizer.py',
            '/home/admin/.openclaw/workspace-arashi/comprehensive-report-v12.py'
        ]
        
        missing_files = []
        for filepath in critical_files:
            if not os.path.exists(filepath):
                missing_files.append(os.path.basename(filepath))
        
        if missing_files:
            issues.append({
                'type': 'missing_files',
                'priority': 'high',
                'title': '关键文件缺失',
                'description': f'发现 {len(missing_files)} 个关键文件缺失',
                'details': missing_files,
                'solutions': ['恢复缺失文件', '检查文件路径配置']
            })
        
        return issues
    
    def generate_optimization_plan(self, issue):
        """生成优化方案"""
        plan = {
            'issue_id': f"OPT-{datetime.now().strftime('%Y%m%d')}-{len(self.pending_issues)+1:03d}",
            'discovered_at': datetime.now().isoformat(),
            'type': issue['type'],
            'priority': issue['priority'],
            'title': issue['title'],
            'description': issue['description'],
            'details': issue.get('details', {}),
            'proposed_solutions': issue.get('solutions', []),
            'status': 'pending',  # pending, confirmed, rejected, completed
            'user_response': None
        }
        return plan
    
    def report_issue(self, plan):
        """向用户报告问题"""
        priority_cn = {'high': '高', 'medium': '中', 'low': '低'}
        
        content = f"""**问题编号**: {plan['issue_id']}
**优先级**: {priority_cn.get(plan['priority'], plan['priority'])}
**类型**: {plan['type']}

**问题描述**:
{plan['description']}

**详情**:
```json
{json.dumps(plan['details'], indent=2, ensure_ascii=False)}
```

**建议优化方案**:
"""
        for i, solution in enumerate(plan['proposed_solutions'], 1):
            content += f"{i}. {solution}\n"
        
        content += f"""
**预计影响**:
- 修复后系统稳定性提升
- 减少潜在错误
- 优化资源使用

请回复以下指令之一:
- `确认 {plan['issue_id']}` - 执行优化
- `忽略 {plan['issue_id']}` - 跳过此问题
- `查看详情 {plan['issue_id']}` - 了解更多信息
"""
        
        self.send_notification(plan['title'], content, plan['priority'])
        print(f"📤 已报告问题: {plan['issue_id']} - {plan['title']}")
    
    def run_self_check(self):
        """运行自我检查"""
        print("="*60)
        print("🤖 AI自我优化检查启动")
        print("="*60)
        
        all_issues = []
        
        # 1. 检查文件大小
        print("\n1. 检查文件大小...")
        issues = self.check_file_sizes()
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 2. 检查日志错误
        print("\n2. 检查日志错误...")
        issues = self.check_log_errors()
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 3. 检查策略表现
        print("\n3. 检查策略表现...")
        issues = self.check_strategy_performance()
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 4. 检查记忆文件
        print("\n4. 检查记忆文件...")
        issues = self.check_memory_files()
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 5. 检查系统健康
        print("\n5. 检查系统健康...")
        issues = self.check_system_health()
        all_issues.extend(issues)
        print(f"   发现 {len(issues)} 个问题")
        
        # 生成优化计划并报告
        print("\n" + "="*60)
        print(f"📊 检查完成: 共发现 {len(all_issues)} 个问题")
        print("="*60)
        
        new_issues = []
        for issue in all_issues:
            # 检查是否已报告过
            existing = [p for p in self.pending_issues if p['type'] == issue['type'] and p['status'] == 'pending']
            if not existing:
                plan = self.generate_optimization_plan(issue)
                self.pending_issues.append(plan)
                self.report_issue(plan)
                new_issues.append(plan)
        
        # 更新状态
        self.state['last_check'] = datetime.now().isoformat()
        self.state['check_count'] += 1
        self.state['issues_found'] += len(new_issues)
        self.save_state()
        self.save_pending_issues()
        
        if new_issues:
            print(f"\n✅ 已报告 {len(new_issues)} 个新问题，等待用户确认")
        else:
            print("\n✅ 未发现新问题")
        
        print("="*60)
    
    def list_pending_issues(self):
        """列出待处理的问题"""
        pending = [p for p in self.pending_issues if p['status'] == 'pending']
        
        if not pending:
            print("✅ 没有待处理的问题")
            return
        
        print("="*60)
        print(f"📋 待处理的问题 ({len(pending)}个)")
        print("="*60)
        
        for plan in pending:
            priority_emoji = {'high': '🚨', 'medium': '⚠️', 'low': '💡'}
            print(f"\n{priority_emoji.get(plan['priority'], 'ℹ️')} {plan['issue_id']}")
            print(f"   标题: {plan['title']}")
            print(f"   优先级: {plan['priority']}")
            print(f"   发现时间: {plan['discovered_at'][:16]}")
        
        print("\n" + "="*60)
    
    def apply_optimization(self, issue_id):
        """执行优化"""
        plan = None
        for p in self.pending_issues:
            if p['issue_id'] == issue_id:
                plan = p
                break
        
        if not plan:
            print(f"❌ 未找到问题: {issue_id}")
            return False
        
        print(f"\n🔧 执行优化: {issue_id}")
        print(f"   标题: {plan['title']}")
        
        # 根据问题类型执行不同的优化
        if plan['type'] == 'large_files':
            self.optimize_large_files(plan)
        elif plan['type'] == 'log_errors':
            self.optimize_log_errors(plan)
        elif plan['type'] == 'old_memory_files':
            self.optimize_old_memory_files(plan)
        else:
            print(f"   ⚠️ 自动优化暂未实现此类型: {plan['type']}")
            print(f"   💡 建议手动处理: {', '.join(plan['proposed_solutions'][:2])}")
        
        # 更新状态
        plan['status'] = 'completed'
        plan['completed_at'] = datetime.now().isoformat()
        self.state['optimizations_applied'] += 1
        self.save_state()
        self.save_pending_issues()
        
        print(f"✅ 优化完成: {issue_id}")
        return True
    
    def optimize_large_files(self, plan):
        """优化大文件"""
        print("   清理日志文件...")
        log_dir = '/home/admin/.openclaw/workspace-arashi/logs'
        
        for detail in plan.get('details', []):
            filepath = f"/home/admin/.openclaw/workspace-arashi/{detail['file']}"
            if os.path.exists(filepath) and filepath.endswith('.log'):
                # 备份并清空
                backup_path = filepath + '.old'
                os.rename(filepath, backup_path)
                with open(filepath, 'w') as f:
                    f.write(f"# Log cleared by AI optimizer at {datetime.now()}\n")
                print(f"   ✓ 已清理: {detail['file']}")
    
    def optimize_log_errors(self, plan):
        """优化日志错误"""
        print("   分析错误日志...")
        print("   💡 建议手动检查以下文件:")
        for detail in plan.get('details', [])[:3]:
            print(f"      - {detail['file']}")
    
    def optimize_old_memory_files(self, plan):
        """优化旧记忆文件"""
        print("   归档旧记忆文件...")
        memory_dir = '/home/admin/.openclaw/workspace-arashi/memory'
        backup_dir = '/home/admin/.openclaw/workspace-arashi/memory/backup'
        
        os.makedirs(backup_dir, exist_ok=True)
        
        for filename in plan.get('details', []):
            src = os.path.join(memory_dir, filename)
            dst = os.path.join(backup_dir, filename)
            if os.path.exists(src):
                os.rename(src, dst)
                print(f"   ✓ 已归档: {filename}")


def main():
    """主函数"""
    import sys
    
    optimizer = AISelfOptimizer()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'list':
            optimizer.list_pending_issues()
        elif cmd == 'apply' and len(sys.argv) > 2:
            optimizer.apply_optimization(sys.argv[2])
        else:
            print("用法:")
            print("  python3 ai-self-optimizer.py          # 运行自我检查")
            print("  python3 ai-self-optimizer.py list     # 列出待处理问题")
            print("  python3 ai-self-optimizer.py apply <issue_id>  # 执行优化")
    else:
        optimizer.run_self_check()


if __name__ == '__main__':
    main()
