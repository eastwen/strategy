#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
智能扫描调度系统 v2.0
- 全市场扫描（3980只股票）
- 交易日判断
- 交易时间判断
- 非交易日/非交易时间自动跳过
"""

import sys
import json
import time
from datetime import datetime, date, time as dt_time, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')

# 导入交易日历
from trading_calendar import TradingCalendar

class SmartSchedulerV2:
    """智能扫描调度器 v2.0"""
    
    def __init__(self):
        self.scan_interval = 300  # 扫描间隔：5分钟
        self.stock_pool_file = '/home/admin/.openclaw/workspace-stock/data/stock_pool_full.json'
        self.calendar = TradingCalendar()
        
        # 加载股票池
        self.load_stock_pool()
    
    def get_hk_trading_hours(self):
        """港股交易时间（北京时间）"""
        return {
            'pre_market': [(9, 15), (9, 30)],      # 开盘前15分钟
            'morning': [(9, 30), (12, 0)],         # 上午盘
            'afternoon': [(13, 0), (16, 10)],      # 下午盘（12:00-13:00午休）
        }
    
    def load_stock_pool(self):
        """加载股票池"""
        try:
            with open(self.stock_pool_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.hk_stocks = data.get('hk_stocks', [])
            self.us_stocks = data.get('us_stocks', [])
            print(f"✅ 股票池加载成功: 港股{len(self.hk_stocks)}只, 美股{len(self.us_stocks)}只")
        except Exception as e:
            print(f"❌ 股票池加载失败: {e}")
            self.hk_stocks = []
            self.us_stocks = []
    
    def is_trading_time(self, market='hk'):
        """判断是否在交易时间（自动夏令时/冬令时）"""
        now = datetime.now()
        current_time = now.time()
        
        if market == 'hk':
            # 港股：固定交易时间
            schedule = self.get_hk_trading_hours()
            for session, (start, end) in schedule.items():
                start_time = dt_time(start[0], start[1])
                end_time = dt_time(end[0], end[1])
                if start_time <= current_time <= end_time:
                    return True, session
        else:
            # 美股：根据夏令时/冬令时自动调整
            schedule = self.calendar.get_us_trading_hours_beijing()
            for session, (start, end) in schedule.items():
                start_time = dt_time(start[0], start[1])
                end_time = dt_time(end[0], end[1])
                
                # 处理跨午夜的情况
                if start_time > end_time:
                    if current_time >= start_time or current_time <= end_time:
                        return True, session
                else:
                    if start_time <= current_time <= end_time:
                        return True, session
        
        return False, None
    
    def should_scan(self, market='hk'):
        """判断是否应该扫描（交易日 + 交易时间）"""
        # 1. 判断是否为交易日
        is_trading_day, day_reason = self.calendar.is_hk_trading_day() if market == 'hk' else self.calendar.is_us_trading_day()
        
        if not is_trading_day:
            return False, f"非交易日({day_reason})"
        
        # 2. 判断是否在交易时间
        is_trading_time, session = self.is_trading_time(market)
        
        if not is_trading_time:
            return False, "非交易时间"
        
        return True, f"交易时间({session})"
    
    def scan_market(self, market='hk'):
        """扫描市场（全股票池）"""
        from futu import OpenQuoteContext
        import requests
        
        market_name = '港股' if market == 'hk' else '美股'
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 扫描 {market_name}...")
        
        results = []
        stocks = self.hk_stocks if market == 'hk' else self.us_stocks
        total = len(stocks)
        
        print(f"  股票池: {total}只")
        
        if market == 'hk':
            # 港股扫描
            quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
            try:
                for i, stock in enumerate(stocks):
                    try:
                        code = stock['code']
                        name = stock.get('name', code)
                        
                        # 每100只显示进度
                        if (i + 1) % 100 == 0:
                            print(f"  进度: {i+1}/{total} ({(i+1)/total*100:.1f}%)")
                        
                        ret, snapshot = quote_ctx.get_market_snapshot([code])
                        if ret == 0 and not snapshot.empty:
                            price = snapshot.iloc[0]['last_price']
                            prev_close = snapshot.iloc[0]['prev_close_price']
                            
                            # 跳过无效数据
                            if price is None or price == 'N/A':
                                continue
                            if prev_close is None or prev_close == 'N/A' or prev_close == 0:
                                continue
                            
                            # 计算涨跌幅
                            price_float = float(price)
                            prev_close_float = float(prev_close)
                            change_pct = (price_float - prev_close_float) / prev_close_float * 100
                            
                            # 计算评分
                            score = 60
                            if change_pct > 2:
                                score += 20
                            elif change_pct > 1:
                                score += 10
                            elif change_pct < -2:
                                score -= 20
                            
                            results.append({
                                'code': code,
                                'name': name,
                                'price': price_float,
                                'change_pct': change_pct,
                                'score': score,
                                'timestamp': datetime.now().isoformat()
                            })
                    except:
                        continue
            finally:
                quote_ctx.close()
        
        else:
            # 美股扫描 - 使用Finnhub API获取夜盘数据
            import json
            with open('/home/admin/.openclaw/workspace-stock/.api-keys.json', 'r') as f:
                api_keys = json.load(f)
            finnhub_key = api_keys['finnhub']['api_key']
            
            for i, stock in enumerate(stocks):
                try:
                    symbol = stock['symbol']
                    name = stock.get('name', symbol)
                    
                    # 每50只显示进度
                    if (i + 1) % 50 == 0:
                        print(f"  进度: {i+1}/{total} ({(i+1)/total*100:.1f}%)")
                    
                    # 使用Finnhub API获取实时行情
                    url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={finnhub_key}'
                    res = requests.get(url, timeout=10)
                    
                    if res.status_code == 200:
                        data = res.json()
                        price = data.get('c', 0)  # current price
                        change_pct = data.get('dp', 0)  # change percent
                        
                        # 跳过无效数据
                        if price is None or price == 0:
                            continue
                        
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
                            'price': float(price),
                            'change_pct': float(change_pct),
                            'score': score,
                            'timestamp': datetime.now().isoformat()
                        })
                    
                    time.sleep(0.05)  # 避免请求过快
                except:
                    continue
        
        # 保存结果
        self.save_results(results, market)
        
        print(f"✅ 扫描完成: {len(results)}/{total}只 ({len(results)/total*100:.1f}%)")
        
        return results
    
    def save_results(self, results, market):
        """保存扫描结果"""
        import os
        os.makedirs('/home/admin/.openclaw/workspace-stock/data', exist_ok=True)
        
        data = {
            'market': market,
            'last_scan': datetime.now().isoformat(),
            'total_scanned': len(results),
            'stocks': results
        }
        
        filename = f'/home/admin/.openclaw/workspace-stock/data/scan_{market}.json'
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def run(self):
        """运行智能调度"""
        import sys
        
        print('\n' + '='*60, flush=True)
        print('🚀 智能扫描调度系统 v2.0', flush=True)
        print('='*60, flush=True)
        print(f'股票池: 港股{len(self.hk_stocks)}只 + 美股{len(self.us_stocks)}只 = {len(self.hk_stocks)+len(self.us_stocks)}只', flush=True)
        print(f'扫描间隔: {self.scan_interval//60}分钟', flush=True)
        print('='*60, flush=True)
        sys.stdout.flush()
        
        while True:
            try:
                print(f"\n{'='*60}", flush=True)
                print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
                print('='*60, flush=True)
                sys.stdout.flush()
                
                # 显示当前时间
                info = self.calendar.get_current_time_info()
                print(f"北京时间: {info['beijing_time']} ({info['beijing_weekday']})", flush=True)
                print(f"美东时间: {info['newyork_time']} ({info['newyork_weekday']}) - {info['timezone_name']}", flush=True)
                sys.stdout.flush()
                
                # 美股交易时间
                if info['is_dst']:
                    print(f"美股: 夏令时交易时间", flush=True)
                else:
                    print(f"美股: 冬令时交易时间", flush=True)
                sys.stdout.flush()
                
                # 港股
                should, reason = self.should_scan('hk')
                if should:
                    print(f"🇭🇰 港股: ✅ {reason}", flush=True)
                    self.scan_market('hk')
                else:
                    print(f"🇭🇰 港股: ⏸️ {reason}，跳过", flush=True)
                
                # 美股
                should, reason = self.should_scan('us')
                if should:
                    print(f"🇺🇸 美股: ✅ {reason}", flush=True)
                    self.scan_market('us')
                else:
                    print(f"🇺🇸 美股: ⏸️ {reason}，跳过", flush=True)
                
                sys.stdout.flush()
                
                # 等待下次扫描
                next_scan = datetime.now() + timedelta(seconds=self.scan_interval)
                print(f"\n⏰ 下次扫描: {next_scan.strftime('%H:%M:%S')}", flush=True)
                time.sleep(self.scan_interval)
                
            except KeyboardInterrupt:
                print("\n\n⚠️ 接收到停止信号", flush=True)
                break
            except Exception as e:
                print(f"\n❌ 错误: {e}", flush=True)
                import traceback
                traceback.print_exc()
                time.sleep(60)


if __name__ == '__main__':
    scheduler = SmartSchedulerV2()
    scheduler.run()