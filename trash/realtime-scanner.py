#!/usr/bin/env python3
"""
实时监控 + 主动汇报
扫描完成后自动发送通知
"""

import sys
import json
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import requests

class RealtimeScanner:
    """实时扫描器 - 扫描完主动汇报"""
    
    def __init__(self):
        self.scan_interval = 30  # 30秒扫描一次
        self.finnhub_key = self.load_api_key()
        self.last_results = []
        
        # 关注的股票池
        self.watch_list = [
            'QQQ', 'SPY', 'NVDA', 'TSLA', 'AAPL', 'META', 'AMD', 'GOOGL', 'AMZN', 'MSFT',
            'VRT', 'SMCI', 'PLTR', 'AI', 'ARM', 'COIN', 'HOOD', 'MSTR', 'MARA', 'RIOT'
        ]
    
    def load_api_key(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            return json.load(f)['finnhub']['api_key']
    
    def scan(self):
        """快速扫描关注股票"""
        results = []
        
        for symbol in self.watch_list:
            try:
                url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                res = requests.get(url, timeout=5)
                
                if res.status_code == 200:
                    data = res.json()
                    price = data.get('c', 0)
                    change_pct = data.get('dp', 0)
                    
                    results.append({
                        'symbol': symbol,
                        'price': price,
                        'change_pct': change_pct,
                        'time': datetime.now().strftime('%H:%M:%S')
                    })
                    
            except:
                continue
        
        return results
    
    def check_alerts(self, results):
        """检查是否有重大变化"""
        alerts = []
        
        for stock in results:
            symbol = stock['symbol']
            change = stock['change_pct']
            
            # 涨幅超过3%
            if change > 3:
                alerts.append(f"🔥 {symbol} ${stock['price']:.2f} (+{change:.2f}%)")
            
            # 跌幅超过3%
            elif change < -3:
                alerts.append(f"❄️ {symbol} ${stock['price']:.2f} ({change:.2f}%)")
        
        return alerts
    
    def run(self):
        """运行实时监控"""
        print("=" * 60)
        print("🚀 实时监控启动")
        print(f"监控股票: {len(self.watch_list)}只")
        print(f"扫描间隔: {self.scan_interval}秒")
        print("=" * 60)
        
        while True:
            try:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"\n⏰ [{now}] 扫描中...")
                
                # 扫描
                results = self.scan()
                
                # 检查警报
                alerts = self.check_alerts(results)
                
                if alerts:
                    print("\n" + "=" * 60)
                    print("⚠️ 发现重大变化！")
                    print("=" * 60)
                    for alert in alerts:
                        print(alert)
                    
                    # 保存警报
                    self.save_alerts(alerts)
                
                # 显示涨幅TOP5
                sorted_results = sorted(results, key=lambda x: x['change_pct'], reverse=True)
                print(f"\n涨幅TOP5:")
                for i, r in enumerate(sorted_results[:5], 1):
                    status = "🟢" if r['change_pct'] > 0 else "🔴"
                    print(f"  {i}. {status} {r['symbol']:6s} ${r['price']:.2f} ({r['change_pct']:+.2f}%)")
                
                # 等待
                time.sleep(self.scan_interval)
                
            except KeyboardInterrupt:
                print("\n停止监控")
                break
            except Exception as e:
                print(f"错误: {e}")
                time.sleep(10)
    
    def save_alerts(self, alerts):
        """保存警报"""
        with open('/home/admin/.openclaw/workspace-arashi/data/alerts.json', 'w') as f:
            json.dump({
                'time': datetime.now().isoformat(),
                'alerts': alerts
            }, f)


if __name__ == '__main__':
    scanner = RealtimeScanner()
    scanner.run()
