#!/usr/bin/env python3
"""
智能扫描调度系统
根据交易时间自动开启/停止扫描
"""

import sys
import json
import time
from datetime import datetime, time as dt_time

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class SmartScheduler:
    """智能扫描调度器"""
    
    def __init__(self):
        self.scan_interval = 300  # 扫描间隔：5分钟
        self.data_file = '/home/admin/.openclaw/workspace-arashi/data/scan_results.json'
        
        # 交易时间配置（北京时间）
        self.trading_hours = {
            'hk': {
                'name': '港股',
                'timezone': 'Asia/Shanghai',
                'schedule': {
                    'pre_market': [(9, 15), (9, 30)],      # 开盘前15分钟
                    'morning': [(9, 30), (12, 0)],          # 上午盘
                    'afternoon': [(13, 0), (16, 10)],       # 下午盘
                }
            },
            'us': {
                'name': '美股',
                'timezone': 'America/New_York',
                'schedule': {
                    # 冬令时（11月-3月）
                    'pre_market': [(17, 0), (22, 30)],      # 盘前：美东4:00-9:30 → 北京17:00-22:30
                    'regular': [(22, 30), (5, 0)],          # 盘中：美东9:30-16:00 → 北京22:30-05:00
                    'post_market': [(5, 0), (9, 0)],        # 盘后：美东16:00-20:00 → 北京05:00-09:00
                }
            }
        }
    
    def is_trading_time(self, market='hk'):
        """判断是否在交易时间"""
        now = datetime.now()
        current_time = now.time()
        
        schedule = self.trading_hours[market]['schedule']
        
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
    
    def get_next_scan_time(self, market='hk'):
        """获取下次扫描时间"""
        now = datetime.now()
        
        is_trading, session = self.is_trading_time(market)
        
        if is_trading:
            # 在交易时间，5分钟后扫描
            return now.timestamp() + self.scan_interval
        else:
            # 不在交易时间，计算下次开盘时间
            # 简化：返回明天开盘时间
            return None
    
    def scan_market(self, market='hk'):
        """扫描市场（全股票池）"""
        from futu import OpenQuoteContext
        import requests
        
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 扫描 {self.trading_hours[market]['name']}...")
        
        # 加载股票池
        try:
            with open('/home/admin/.openclaw/workspace-arashi/data/stock_pool.json', 'r', encoding='utf-8') as f:
                stock_pool = json.load(f)
        except:
            stock_pool = {'hk_stocks': [], 'us_stocks': []}
        
        results = []
        
        if market == 'hk':
            # 港股扫描
            quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            try:
                stocks = stock_pool['hk_stocks']
                print(f"  股票池: {len(stocks)}只")
                
                for i, stock in enumerate(stocks):
                    try:
                        code = stock['code']
                        name = stock['name']
                        
                        # 每50只显示进度
                        if (i + 1) % 50 == 0:
                            print(f"  进度: {i+1}/{len(stocks)}")
                        
                        ret, snapshot = quote_ctx.get_market_snapshot([code])
                        if ret == 0 and not snapshot.empty:
                            price = snapshot.iloc[0]['last_price']
                            change_pct = snapshot.iloc[0]['change_rate']
                            
                            # 计算评分
                            score = 60
                            if change_pct and change_pct > 2:
                                score += 20
                            elif change_pct and change_pct > 1:
                                score += 10
                            elif change_pct and change_pct < -2:
                                score -= 20
                            
                            results.append({
                                'code': code,
                                'name': name,
                                'price': float(price) if price else 0,
                                'change_pct': float(change_pct) if change_pct else 0,
                                'score': score,
                                'timestamp': datetime.now().isoformat()
                            })
                    except:
                        continue
            finally:
                quote_ctx.close()
        
        else:
            # 美股扫描
            stocks = stock_pool['us_stocks']
            print(f"  股票池: {len(stocks)}只")
            
            for i, stock in enumerate(stocks):
                try:
                    symbol = stock['symbol']
                    name = stock['name']
                    
                    # 每50只显示进度
                    if (i + 1) % 50 == 0:
                        print(f"  进度: {i+1}/{len(stocks)}")
                    
                    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
                    params = {'range': '1d', 'interval': '1d'}
                    headers = {'User-Agent': 'Mozilla/5.0'}
                    
                    res = requests.get(url, params=params, headers=headers, timeout=10)
                    
                    if res.status_code == 200:
                        data = res.json()['chart']['result'][0]['meta']
                        price = data.get('regularMarketPrice', 0)
                        change_pct = data.get('regularMarketChangePercent', 0)
                        
                        # 计算评分
                        score = 60
                        if change_pct > 2:
                            score += 20
                        elif change_pct > 1:
                            score += 10
                        elif change_pct < -2:
                            score -= 20
                        
                        results.append({
                            'symbol': symbol,
                            'name': name,
                            'price': price,
                            'change_pct': change_pct * 100,
                            'score': score,
                            'timestamp': datetime.now().isoformat()
                        })
                    
                    time.sleep(0.1)  # 避免请求过快
                except:
                    continue
        
        # 保存结果
        self.save_results(results, market)
        
        print(f"✅ {self.trading_hours[market]['name']}扫描完成: {len(results)}/{len(stock_pool['hk_stocks' if market=='hk' else 'us_stocks'])}只股票")
        
        return results
    
    def save_results(self, results, market):
        """保存扫描结果"""
        import os
        os.makedirs('/home/admin/.openclaw/workspace-arashi/data', exist_ok=True)
        
        data = {
            'market': market,
            'last_scan': datetime.now().isoformat(),
            'stocks': results
        }
        
        filename = f'/home/admin/.openclaw/workspace-arashi/data/scan_{market}.json'
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def run(self):
        """运行智能调度"""
        print('\n' + '='*60)
        print('🚀 智能扫描调度系统启动')
        print('='*60)
        print('扫描策略：')
        print('  港股：开盘前15分钟 → 收盘 (09:15-16:10)')
        print('  美股：夜盘、盘前、盘中、盘后')
        print('  扫描间隔：5分钟')
        print('='*60)
        
        while True:
            try:
                now = datetime.now()
                
                # 检查港股
                hk_trading, hk_session = self.is_trading_time('hk')
                if hk_trading:
                    print(f"\n🇭🇰 港股交易时段: {hk_session}")
                    self.scan_market('hk')
                else:
                    print(f"\n🇭🇰 港股非交易时段，跳过扫描")
                
                # 检查美股
                us_trading, us_session = self.is_trading_time('us')
                if us_trading:
                    print(f"\n🇺🇸 美股交易时段: {us_session}")
                    self.scan_market('us')
                else:
                    print(f"\n🇺🇸 美股非交易时段，跳过扫描")
                
                # 等待下次扫描
                print(f"\n⏰ 等待 {self.scan_interval//60} 分钟后再次扫描...")
                time.sleep(self.scan_interval)
                
            except KeyboardInterrupt:
                print("\n\n⚠️ 接收到停止信号")
                break
            except Exception as e:
                print(f"\n❌ 错误: {e}")
                time.sleep(60)


if __name__ == '__main__':
    scheduler = SmartScheduler()
    
    # 测试交易时间判断
    print("\n测试交易时间判断:")
    for market in ['hk', 'us']:
        is_trading, session = scheduler.is_trading_time(market)
        print(f"  {market.upper()}: {'交易中' if is_trading else '非交易'} {f'({session})' if session else ''}")
    
    # 启动调度
    scheduler.run()