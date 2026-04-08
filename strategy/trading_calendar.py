#!/usr/bin/env python3
"""
交易日判断工具 v3.0
- 港股：按北京时间判断
- 美股：按美东时间判断（自动夏令时/冬令时）
"""

from datetime import datetime, date, timedelta
import pytz

class TradingCalendar:
    """交易日历 v3.0"""
    
    def __init__(self):
        # 港股非交易日（北京时间）
        self.hk_holidays_2026 = [
            # 元旦
            date(2026, 1, 1),
            # 春节
            date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20),
            # 清明
            date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
            # 劳动节
            date(2026, 5, 1),
            # 佛诞
            date(2026, 5, 2),
            # 端午
            date(2026, 5, 31),
            # 香港回归
            date(2026, 7, 1),
            # 中秋
            date(2026, 10, 1), date(2026, 10, 2),
            # 国庆
            date(2026, 10, 1), date(2026, 10, 2),
            # 重阳
            date(2026, 10, 25),
            # 圣诞
            date(2026, 12, 25), date(2026, 12, 26),
        ]
        
        # 美股非交易日（美东时间）
        self.us_holidays_2026 = [
            # 元旦
            date(2026, 1, 1),
            # 马丁路德金日
            date(2026, 1, 19),
            # 总统日
            date(2026, 2, 16),
            # 耶稣受难日
            date(2026, 4, 3),
            # 阵亡将士日
            date(2026, 5, 25),
            # 六月节
            date(2026, 6, 19),
            # 独立日
            date(2026, 7, 3),
            # 劳动节
            date(2026, 9, 7),
            # 感恩节
            date(2026, 11, 26),
            # 圣诞
            date(2026, 12, 25),
        ]
        
        # 时区
        self.beijing_tz = pytz.timezone('Asia/Shanghai')
        self.newyork_tz = pytz.timezone('America/New_York')
    
    def is_dst(self):
        """判断当前是否为夏令时（美东时间）"""
        newyork_now = datetime.now(self.newyork_tz)
        # DST判断：pytz会自动处理
        return newyork_now.dst() != timedelta(0)
    
    def get_timezone_name(self):
        """获取当前时区名称"""
        if self.is_dst():
            return "EDT（美东夏令时）"
        else:
            return "EST（美东冬令时）"
    
    def get_us_trading_hours_beijing(self):
        """获取美股交易时间（北京时间）- 根据夏令时/冬令时自动调整"""
        if self.is_dst():
            # 夏令时（3月-11月）
            return {
                'pre_market': [(16, 0), (21, 30)],       # 盘前：美东04:00-09:30 → 北京16:00-21:30
                'regular': [(21, 30), (4, 0)],           # 常规盘：美东09:30-16:00 → 北京21:30-次日04:00
                'post_market': [(4, 0), (8, 0)],         # 盘后：美东16:00-20:00 → 北京次日04:00-08:00
                'overnight': [(8, 0), (16, 0)],          # 夜盘：美东20:00-次日04:00 → 北京次日08:00-16:00
            }
        else:
            # 冬令时（11月-次年3月）
            return {
                'pre_market': [(17, 0), (22, 30)],       # 盘前：美东04:00-09:30 → 北京17:00-22:30
                'regular': [(22, 30), (5, 0)],           # 常规盘：美东09:30-16:00 → 北京22:30-次日05:00
                'post_market': [(5, 0), (9, 0)],         # 盘后：美东16:00-20:00 → 北京次日05:00-09:00
                'overnight': [(9, 0), (17, 0)],          # 夜盘：美东20:00-次日04:00 → 北京次日09:00-17:00
            }
    
    def is_hk_trading_day(self, check_date=None):
        """判断港股是否为交易日（北京时间）"""
        if check_date is None:
            check_date = datetime.now(self.beijing_tz).date()
        
        # 周末不交易
        if check_date.weekday() >= 5:
            return False, "周末"
        
        # 节假日不交易
        if check_date in self.hk_holidays_2026:
            return False, "节假日"
        
        return True, "交易日"
    
    def is_us_trading_day(self, check_datetime=None):
        """判断美股是否为交易日（美东时间）"""
        if check_datetime is None:
            beijing_now = datetime.now(self.beijing_tz)
            newyork_now = beijing_now.astimezone(self.newyork_tz)
            check_date = newyork_now.date()
        elif isinstance(check_datetime, datetime):
            if check_datetime.tzinfo is None:
                check_datetime = self.beijing_tz.localize(check_datetime)
            check_date = check_datetime.astimezone(self.newyork_tz).date()
        else:
            check_date = check_datetime
        
        # 周末不交易
        if check_date.weekday() >= 5:
            return False, "周末"
        
        # 节假日不交易
        if check_date in self.us_holidays_2026:
            return False, "节假日"
        
        return True, "交易日"
    
    def get_current_time_info(self):
        """获取当前时间信息"""
        beijing_now = datetime.now(self.beijing_tz)
        newyork_now = beijing_now.astimezone(self.newyork_tz)
        
        return {
            'beijing_time': beijing_now.strftime('%Y-%m-%d %H:%M:%S'),
            'beijing_date': beijing_now.date(),
            'beijing_weekday': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][beijing_now.weekday()],
            'newyork_time': newyork_now.strftime('%Y-%m-%d %H:%M:%S'),
            'newyork_date': newyork_now.date(),
            'newyork_weekday': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][newyork_now.weekday()],
            'is_dst': self.is_dst(),
            'timezone_name': self.get_timezone_name(),
        }


# 测试
if __name__ == '__main__':
    calendar = TradingCalendar()
    
    # 获取当前时间
    info = calendar.get_current_time_info()
    
    print('='*60)
    print('⏰ 当前时间')
    print('='*60)
    print(f"北京时间: {info['beijing_time']} ({info['beijing_weekday']})")
    print(f"美东时间: {info['newyork_time']} ({info['newyork_weekday']})")
    print(f"时区状态: {info['timezone_name']}")
    
    print()
    print('='*60)
    print('📊 交易日判断')
    print('='*60)
    
    # 港股
    is_trading, reason = calendar.is_hk_trading_day()
    print(f"港股: {'✅ 交易日' if is_trading else f'❌ 非交易日 ({reason})'}")
    
    # 美股
    is_trading, reason = calendar.is_us_trading_day()
    print(f"美股: {'✅ 交易日' if is_trading else f'❌ 非交易日 ({reason})'}")
    
    print()
    print('='*60)
    print('⏰ 美股交易时间（北京时间）')
    print('='*60)
    
    hours = calendar.get_us_trading_hours_beijing()
    print(f"当前: {'夏令时' if info['is_dst'] else '冬令时'}")
    print(f"盘前: {hours['pre_market'][0][0]:02d}:{hours['pre_market'][0][1]:02d} - {hours['pre_market'][1][0]:02d}:{hours['pre_market'][1][1]:02d}")
    print(f"常规盘: {hours['regular'][0][0]:02d}:{hours['regular'][0][1]:02d} - {hours['regular'][1][0]:02d}:{hours['regular'][1][1]:02d}")
    print(f"盘后: {hours['post_market'][0][0]:02d}:{hours['post_market'][0][1]:02d} - {hours['post_market'][1][0]:02d}:{hours['post_market'][1][1]:02d}")
    print(f"夜盘: {hours['overnight'][0][0]:02d}:{hours['overnight'][0][1]:02d} - {hours['overnight'][1][0]:02d}:{hours['overnight'][1][1]:02d}")