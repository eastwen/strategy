#!/usr/bin/env python3
"""
全自动量化交易系统 v1.0
- 扫描 → 分析 → 下单 全自动
- 不需要人工干预
- 发现机会立即执行
"""

import sys
import json
import time
from datetime import datetime
import requests

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class AutoTradingBot:
    """全自动交易机器人"""
    
    def __init__(self):
        # 配置
        self.scan_interval = 30  # 扫描间隔
        self.min_score = 70  # 最低评分
        self.max_positions = 10  # 最大持仓数
        
        # API
        self.finnhub_key = self.load_api_key()
        
        # 监控股票池
        self.watch_list = [
            # 指数
            'QQQ', 'SPY', 'IWM',
            # 科技龙头
            'NVDA', 'TSLA', 'AAPL', 'META', 'AMD', 'GOOGL', 'MSFT', 'AMZN',
            # 热门
            'VRT', 'SMCI', 'PLTR', 'ARM', 'AI', 'COIN', 'SOXL', 'SOXS',
        ]
        
        # 持仓
        self.positions = []
        self.cash = 1000000  # 初始资金
        
        # 警报和机会文件
        self.opportunities_file = '/home/admin/.openclaw/workspace-arashi/data/opportunities.json'
        self.trades_file = '/home/admin/.openclaw/workspace-arashi/data/trades.json'
        
    def load_api_key(self):
        with open('/home/admin/.openclaw/workspace-arashi/.api-keys.json', 'r') as f:
            return json.load(f)['finnhub']['api_key']
    
    def get_quote(self, symbol):
        """获取行情"""
        try:
            url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                return res.json()
        except:
            pass
        return None
    
    def analyze(self, symbol, quote):
        """分析股票，返回评分和信号"""
        if not quote or 'c' not in quote:
            return None
        
        price = quote.get('c', 0)
        change_pct = quote.get('dp', 0)
        volume = quote.get('v', 0)
        
        # 评分逻辑
        score = 50
        
        # 趋势
        if change_pct > 3:
            score += 30  # 强势拉升
        elif change_pct > 2:
            score += 20
        elif change_pct > 1:
            score += 10
        elif change_pct < -3:
            score -= 30  # 强势下跌
        elif change_pct < -2:
            score -= 20
        
        # 成交量
        if volume > 10000000:
            score += 10  # 成交量大
        
        # 信号
        signal = None
        if score >= self.min_score and change_pct > 2:
            signal = 'BUY'
        elif score < 40 or change_pct < -5:
            signal = 'SELL'
        
        return {
            'symbol': symbol,
            'price': price,
            'change_pct': change_pct,
            'volume': volume,
            'score': score,
            'signal': signal,
            'time': datetime.now().isoformat()
        }
    
    def execute_trade(self, analysis):
        """执行交易"""
        if not analysis or not analysis['signal']:
            return None
        
        symbol = analysis['symbol']
        signal = analysis['signal']
        price = analysis['price']
        
        trade = None
        
        if signal == 'BUY':
            # 检查是否已持仓
            if symbol in [p['symbol'] for p in self.positions]:
                return None
            
            # 检查持仓数量
            if len(self.positions) >= self.max_positions:
                return None
            
            # 计算仓位
            position_size = min(self.cash * 0.1, 100000)  # 单只股票最多10%资金
            shares = int(position_size / price)
            
            if shares > 0 and self.cash >= shares * price:
                # 模拟买入
                self.cash -= shares * price
                self.positions.append({
                    'symbol': symbol,
                    'shares': shares,
                    'price': price,
                    'time': datetime.now().isoformat()
                })
                
                trade = {
                    'action': 'BUY',
                    'symbol': symbol,
                    'shares': shares,
                    'price': price,
                    'value': shares * price,
                    'cash': self.cash,
                    'time': datetime.now().isoformat(),
                    'reason': f"评分:{analysis['score']} 涨幅:{analysis['change_pct']:+.2f}%"
                }
                
                print(f"\n{'='*60}")
                print(f"🟢 买入执行!")
                print(f"{'='*60}")
                print(f"  股票: {symbol}")
                print(f"  数量: {shares}股")
                print(f"  价格: ${price:.2f}")
                print(f"  金额: ${shares*price:.2f}")
                print(f"  原因: {trade['reason']}")
                print(f"  现金: ${self.cash:.2f}")
        
        elif signal == 'SELL':
            # 检查持仓
            for i, pos in enumerate(self.positions):
                if pos['symbol'] == symbol:
                    # 模拟卖出
                    sell_value = pos['shares'] * price
                    self.cash += sell_value
                    
                    trade = {
                        'action': 'SELL',
                        'symbol': symbol,
                        'shares': pos['shares'],
                        'price': price,
                        'value': sell_value,
                        'cash': self.cash,
                        'profit': (price - pos['price']) / pos['price'] * 100,
                        'time': datetime.now().isoformat()
                    }
                    
                    self.positions.pop(i)
                    
                    print(f"\n{'='*60}")
                    print(f"🔴 卖出执行!")
                    print(f"{'='*60}")
                    print(f"  股票: {symbol}")
                    print(f"  数量: {trade['shares']}股")
                    print(f"  价格: ${price:.2f}")
                    print(f"  收益: {trade['profit']:+.2f}%")
                    print(f"  现金: ${self.cash:.2f}")
                    break
        
        return trade
    
    def save_opportunities(self, opportunities):
        """保存交易机会"""
        if opportunities:
            with open(self.opportunities_file, 'w') as f:
                json.dump({
                    'time': datetime.now().isoformat(),
                    'opportunities': opportunities
                }, f, indent=2)
    
    def save_trade(self, trade):
        """保存交易记录"""
        if not trade:
            return
        
        try:
            with open(self.trades_file, 'r') as f:
                data = json.load(f)
        except:
            data = {'trades': []}
        
        data['trades'].append(trade)
        data['last_update'] = datetime.now().isoformat()
        
        with open(self.trades_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def run(self):
        """运行交易机器人"""
        print("=" * 60)
        print("🤖 全自动交易机器人 v1.0")
        print("=" * 60)
        print(f"监控股票: {len(self.watch_list)}只")
        print(f"扫描间隔: {self.scan_interval}秒")
        print(f"最低评分: {self.min_score}分")
        print(f"最大持仓: {self.max_positions}只")
        print(f"初始资金: ${self.cash:,.0f}")
        print("=" * 60)
        
        while True:
            try:
                now = datetime.now()
                print(f"\n⏰ [{now.strftime('%H:%M:%S')}] 扫描...")
                
                opportunities = []
                
                for symbol in self.watch_list:
                    quote = self.get_quote(symbol)
                    analysis = self.analyze(symbol, quote)
                    
                    if analysis and analysis['score'] >= 60:
                        opportunities.append(analysis)
                        
                        # 发现机会立即执行
                        if analysis['signal']:
                            trade = self.execute_trade(analysis)
                            if trade:
                                self.save_trade(trade)
                    
                    time.sleep(0.5)  # API限流
                
                # 保存机会
                self.save_opportunities(opportunities)
                
                # 显示结果
                if opportunities:
                    sorted_opp = sorted(opportunities, key=lambda x: x['score'], reverse=True)
                    print(f"\n发现 {len(opportunities)} 个机会:")
                    for i, opp in enumerate(sorted_opp[:5], 1):
                        emoji = '🟢' if opp['change_pct'] > 0 else '🔴'
                        alert = ' ⚡' if opp['signal'] else ''
                        print(f"  {i}. {emoji} {opp['symbol']:6s} ${opp['price']:.2f} ({opp['change_pct']:>+6.2f}%) 评分:{opp['score']}{alert}")
                
                # 显示持仓
                if self.positions:
                    print(f"\n当前持仓 ({len(self.positions)}只):")
                    for pos in self.positions:
                        print(f"  - {pos['symbol']:6s} {pos['shares']}股 @${pos['price']:.2f}")
                    print(f"  现金: ${self.cash:.2f}")
                
                # 等待下次扫描
                time.sleep(self.scan_interval)
                
            except KeyboardInterrupt:
                print("\n\n✋ 停止交易")
                break
            except Exception as e:
                print(f"\n❌ 错误: {e}")
                time.sleep(10)


if __name__ == '__main__':
    bot = AutoTradingBot()
    bot.run()
