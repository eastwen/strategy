#!/usr/bin/env python3
"""测试交易时间判断"""

from datetime import datetime, time as dt_time

# 交易时间配置（北京时间）
trading_hours = {
    'hk': {
        'name': '港股',
        'schedule': {
            'pre_market': [(9, 15), (9, 30)],      # 开盘前15分钟
            'morning': [(9, 30), (12, 0)],          # 上午盘
            'afternoon': [(13, 0), (16, 10)],       # 下午盘
        }
    },
    'us': {
        'name': '美股',
        'schedule': {
            'after_hours': [(4, 0), (6, 0)],        # 夜盘（盘后）
            'pre_market': [(16, 0), (22, 30)],      # 盘前
            'regular': [(22, 30), (5, 0)],          # 盘中
            'post_market': [(5, 0), (6, 0)],        # 盘后
        }
    }
}

def is_trading_time(market='hk'):
    """判断是否在交易时间"""
    now = datetime.now()
    current_time = now.time()
    
    schedule = trading_hours[market]['schedule']
    
    for session, (start, end) in schedule.items():
        start_time = dt_time(start[0], start[1])
        end_time = dt_time(end[0], end[1])
        
        # 处理跨午夜的情况（美股盘中）
        if start_time > end_time:
            # 跨午夜：22:30-05:00
            if current_time >= start_time or current_time <= end_time:
                return True, session
        else:
            # 正常时段
            if start_time <= current_time <= end_time:
                return True, session
    
    return False, None


# 测试
print('='*60)
print('📊 交易时间判断测试')
print('='*60)
print(f'当前时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
print()

for market in ['hk', 'us']:
    is_trading, session = is_trading_time(market)
    config = trading_hours[market]
    
    print(f'{config["name"]}:')
    print(f'  状态: {"✅ 交易中" if is_trading else "❌ 非交易"} {f"({session})" if session else ""}')
    print(f'  交易时段:')
    for session_name, (start, end) in config['schedule'].items():
        print(f'    - {session_name}: {start[0]:02d}:{start[1]:02d} - {end[0]:02d}:{end[1]:02d}')
    print()