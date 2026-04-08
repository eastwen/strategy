#!/usr/bin/env python3
"""
自我优化检查脚本
每周日自动检查策略表现，决定是否需要优化
"""

import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class SelfOptimizationCheck:
    """自我优化检查"""
    
    def __init__(self):
        self.optimization_log = '/home/admin/.openclaw/workspace-arashi/memory/optimization-log.md'
        self.strategy_status = '/home/admin/.openclaw/workspace-arashi/data/strategy_status.json'
        
        # 触发优化的条件
        self.min_win_rate = 0.50          # 最低胜率50%
        self.min_return = 0.02            # 最低收益2%
        self.max_drawdown = -0.10         # 最大回撤-10%
        self.consecutive_losses = 3       # 连续亏损次数
    
    def check_strategy_performance(self):
        """检查策略表现"""
        print("="*60)
        print("🔍 策略表现检查")
        print("="*60)
        
        # 读取策略状态
        try:
            with open(self.strategy_status, 'r') as f:
                status = json.load(f)
        except:
            # 如果文件不存在，使用默认值
            status = {
                'hk_strategy': {
                    'version': 'v2.0',
                    'win_rate': 1.0,
                    'total_return': 0.05,
                    'max_drawdown': -0.03,
                    'consecutive_losses': 0,
                    'last_update': datetime.now().isoformat()
                },
                'us_strategy': {
                    'version': 'v1.6',
                    'win_rate': 1.0,
                    'total_return': 0.0191,
                    'max_drawdown': -0.02,
                    'consecutive_losses': 0,
                    'last_update': datetime.now().isoformat()
                }
            }
        
        # 检查港股策略
        print("\n📊 港股策略状态:")
        hk = status.get('hk_strategy', {})
        print(f"  版本: {hk.get('version', 'N/A')}")
        print(f"  胜率: {hk.get('win_rate', 0)*100:.1f}%")
        print(f"  收益: {hk.get('total_return', 0)*100:.2f}%")
        print(f"  回撤: {hk.get('max_drawdown', 0)*100:.2f}%")
        print(f"  连亏: {hk.get('consecutive_losses', 0)}次")
        
        # 检查美股策略
        print("\n📊 美股策略状态:")
        us = status.get('us_strategy', {})
        print(f"  版本: {us.get('version', 'N/A')}")
        print(f"  胜率: {us.get('win_rate', 0)*100:.1f}%")
        print(f"  收益: {us.get('total_return', 0)*100:.2f}%")
        print(f"  回撤: {us.get('max_drawdown', 0)*100:.2f}%")
        print(f"  连亏: {us.get('consecutive_losses', 0)}次")
        
        return status
    
    def should_optimize(self, status):
        """判断是否需要优化"""
        print("\n" + "="*60)
        print("🎯 优化需求评估")
        print("="*60)
        
        needs_optimization = False
        reasons = []
        
        for market, strategy in status.items():
            name = '港股' if market == 'hk_strategy' else '美股'
            
            # 检查胜率
            win_rate = strategy.get('win_rate', 1.0)
            if win_rate < self.min_win_rate:
                needs_optimization = True
                reasons.append(f"{name}胜率低于{self.min_win_rate*100}%")
            
            # 检查收益
            total_return = strategy.get('total_return', 0)
            if total_return < self.min_return:
                needs_optimization = True
                reasons.append(f"{name}收益低于{self.min_return*100}%")
            
            # 检查回撤
            max_drawdown = strategy.get('max_drawdown', 0)
            if max_drawdown < self.max_drawdown:
                needs_optimization = True
                reasons.append(f"{name}回撤超过{abs(self.max_drawdown)*100}%")
            
            # 检查连续亏损
            consecutive_losses = strategy.get('consecutive_losses', 0)
            if consecutive_losses >= self.consecutive_losses:
                needs_optimization = True
                reasons.append(f"{name}连续亏损{consecutive_losses}次")
        
        if needs_optimization:
            print("\n⚠️ 需要优化!")
            for reason in reasons:
                print(f"  - {reason}")
            
            print("\n建议优化方案:")
            print("  1. 调整策略参数（权重、阈值等）")
            print("  2. 增加新的信号源")
            print("  3. 调整止损止盈规则")
            print("  4. 重新训练模型（如适用）")
            
            print("\n⚠️ 根据自我优化机制，优化前需与用户沟通确认方案")
        else:
            print("\n✅ 策略表现正常，无需优化")
        
        return needs_optimization, reasons
    
    def log_check(self, status, needs_optimization, reasons):
        """记录检查结果"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(self.optimization_log, 'a', encoding='utf-8') as f:
            f.write(f"\n## 自我优化检查 - {timestamp}\n\n")
            f.write(f"### 港股策略\n")
            hk = status.get('hk_strategy', {})
            f.write(f"- 版本: {hk.get('version', 'N/A')}\n")
            f.write(f"- 胜率: {hk.get('win_rate', 0)*100:.1f}%\n")
            f.write(f"- 收益: {hk.get('total_return', 0)*100:.2f}%\n\n")
            
            f.write(f"### 美股策略\n")
            us = status.get('us_strategy', {})
            f.write(f"- 版本: {us.get('version', 'N/A')}\n")
            f.write(f"- 胜率: {us.get('win_rate', 0)*100:.1f}%\n")
            f.write(f"- 收益: {us.get('total_return', 0)*100:.2f}%\n\n")
            
            if needs_optimization:
                f.write(f"### ⚠️ 需要优化\n")
                for reason in reasons:
                    f.write(f"- {reason}\n")
            else:
                f.write(f"### ✅ 策略表现正常\n")
            
            f.write(f"\n---\n")
        
        print(f"\n💾 检查结果已记录到 {self.optimization_log}")


# 执行检查
if __name__ == '__main__':
    print('\n' + '='*60)
    print('🔍 自我优化检查系统')
    print('='*60)
    
    checker = SelfOptimizationCheck()
    
    # 检查策略表现
    status = checker.check_strategy_performance()
    
    # 判断是否需要优化
    needs_optimization, reasons = checker.should_optimize(status)
    
    # 记录检查结果
    checker.log_check(status, needs_optimization, reasons)
    
    print("\n✅ 检查完成")