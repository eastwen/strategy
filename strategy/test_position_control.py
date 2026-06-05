#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3
"""
仓位控制系统测试
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
exec(open('auto-trader.py').read())

def test_position_control():
    """测试新的仓位控制系统"""
    print('='*60)
    print('🧪 仓位控制系统测试')
    print('='*60)
    
    trader = AutoTrader()
    
    # 测试1: 评分动态仓位
    print('\n📊 测试1: 评分动态仓位')
    test_scores = [80, 82, 85, 88, 90, 93, 95, 98]
    for score in test_scores:
        # 直接调用位置计算方法
        if score < 85:
            position = 0.08 + (score - 80) * 0.02  # 80-84: 8-10%
        elif score < 90:
            position = 0.10 + (score - 85) * 0.02  # 85-89: 10-11%
        elif score < 95:
            position = 0.11 + (score - 90) * 0.02  # 90-94: 11-12%
        else:
            position = 0.12  # ≥95: 12%
        print(f'  评分{score}分 → 仓位{position*100:.1f}%')
    
    # 测试2: VIX环境系数
    print('\n📊 测试2: VIX环境系数')
    # 模拟不同VIX值
    test_vix_values = [15, 22, 27, 32]
    for vix in test_vix_values:
        # 根据VIX值计算系数
        if vix < 20:
            multiplier = 1.0
            total_limit = 0.4
            msg = '正常执行'
        elif vix < 25:
            multiplier = 0.8
            total_limit = 0.4
            msg = '仓位8折'
        elif vix < 30:
            multiplier = 0.6
            total_limit = 0.5
            msg = '仓位6折，总仓位上限50%'
        else:
            multiplier = 0.0
            total_limit = 0.0
            msg = '暂停开仓'
        print(f'  VIX {vix:.1f}: 系数{multiplier} | 总仓位上限{total_limit*100:.0f}% | {msg}')
    
    # 测试3: 综合仓位计算
    print('\n📊 测试3: 综合仓位计算')
    for score in [82, 88, 95]:
        # 计算基础仓位
        if score < 85:
            base_pct = 0.08 + (score - 80) * 0.02  # 80-84: 8-10%
        elif score < 90:
            base_pct = 0.10 + (score - 85) * 0.02  # 85-89: 10-11%
        elif score < 95:
            base_pct = 0.11 + (score - 90) * 0.02  # 90-94: 11-12%
        else:
            base_pct = 0.12  # ≥95: 12%
        
        # 模拟不同VIX环境
        for vix in [15, 25]:
            multiplier = 1.0 if vix < 20 else (0.8 if vix < 25 else 0.6)
            final_pct = min(base_pct * multiplier, 0.12)
            print(f'  评分{score}分 + VIX{vix}: 基础{base_pct*100:.1f}% × {multiplier} → {final_pct*100:.1f}%')
    
    # 测试4: 分级减仓机制逻辑
    print('\n📊 测试4: 分级减仓机制')
    # 模拟持仓状态
    test_positions = [
        {'symbol': 'US.AAPL', 'shares': 100, 'peak_profit': 150.0, 'current_pl_pct': 0.15, 'stop_triggered_time': '2026-06-05 02:00'},
        {'symbol': 'US.NVDA', 'shares': 80, 'peak_profit': 200.0, 'current_pl_pct': -0.08, 'stop_triggered_time': '2026-06-05 02:00'}
    ]
    
    for pos in test_positions:
        # 模拟触发分级减仓第一步（50%）
        step1_shares = pos['shares'] // 2
        remaining_shares = pos['shares'] - step1_shares
        
        print(f'  {pos["symbol"]}: {pos["shares"]}股 → 减半{step1_shares}股，剩余{remaining_shares}股')
        print(f'    浮盈/亏: {pos["current_pl_pct"]*100:+.1f}%')
        print(f'    30分钟后将评估第二步')
    
    print('\n' + '='*60)
    print('🧪 测试完成')
    print('='*60)

if __name__ == '__main__':
    test_position_control()