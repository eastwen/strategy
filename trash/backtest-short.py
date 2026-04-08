#!/usr/bin/env python3
"""
短线趋势策略 v2.0 - 快进快出
- 成交量放大确认
- MACD金叉确认
- 更积极的入场信号
- 紧止损快止盈
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests

class FastTrendStrategy(bt.Strategy):
    """快进快出短线策略"""
    
    params = (
        ('stop_loss', 0.03),      # 3%止损
        ('take_profit', 0.05),    # 5%止盈
        ('position_pct', 0.05),   # 5%仓位
        ('volume_mult', 1.3),     # 成交量放大倍数（降低）
        ('hold_days', 3),         # 最大持仓天数（缩短）
    )
    
    def __init__(self):
        # MACD指标
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=12,
            period_me2=26,
            period_signal=9
        )
        
        # 成交量均线
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        
        # RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        
        # 价格均线
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        
        self.order = None
        self.entry_price = None
        self.entry_bar = None
        self.trades_log = []
        
    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None  # 订单完成，清空
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self.data)
                
    def next(self):
        # 有挂单就等待
        if self.order:
            return
        
        current_bar = len(self.data)
        
        # ===== 持仓管理 =====
        if self.position:
            hold_days = current_bar - self.entry_bar if self.entry_bar else 0
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price if self.entry_price else 0
            
            # 1. 止损 (3%)
            if pnl_pct <= -self.params.stop_loss:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 🛑 止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 2. 止盈 (5%)
            if pnl_pct >= self.params.take_profit:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ✅ 止盈 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 3. MACD死叉离场
            if self.macd.macd[0] < self.macd.signal[0] and self.macd.macd[-1] >= self.macd.signal[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 MACD离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 4. 均线死叉离场
            if self.ma5[0] < self.ma10[0] and self.ma5[-1] >= self.ma10[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 均线离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 5. 最大持仓天数 (3天)
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ⏰ 超时离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
        
        # ===== 入场信号 =====
        else:
            # MACD金叉
            macd_cross = (
                self.macd.macd[0] > self.macd.signal[0] and 
                self.macd.macd[-1] <= self.macd.signal[-1]
            )
            
            # 成交量放大
            volume_surge = (
                self.data.volume[0] > self.vol_ma[0] * self.params.volume_mult and
                self.vol_ma[0] > 0
            )
            
            # 价格多头
            price_bull = self.data.close[0] > self.ma5[0]
            
            # 均线金叉
            ma_cross = self.ma5[0] > self.ma10[0] and self.ma5[-1] <= self.ma10[-1]
            
            # RSI不超买
            rsi_ok = self.rsi[0] < 75
            
            # 组合信号 (更激进)
            signal = macd_cross or ma_cross or (volume_surge and price_bull)
            
            if signal and rsi_ok:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                
                if size > 0:
                    if macd_cross:
                        reason = 'MACD金叉'
                    elif ma_cross:
                        reason = '均线金叉'
                    else:
                        reason = '成交量突破'
                    
                    self.order = self.buy(size=size)
                    print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} ({reason}, RSI:{self.rsi[0]:.0f})')


def get_yahoo_data(symbol, days=90):
    """从Yahoo Finance获取数据"""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    params = {
        'range': f'{days}d',
        'interval': '1d'
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
        if res.status_code != 200:
            return None
        
        data = res.json()['chart']['result'][0]
        timestamps = data['timestamp']
        quote = data['indicators']['quote'][0]
        
        df = pd.DataFrame({
            'datetime': pd.to_datetime(timestamps, unit='s'),
            'open': quote['open'],
            'high': quote['high'],
            'low': quote['low'],
            'close': quote['close'],
            'volume': quote['volume']
        })
        df.set_index('datetime', inplace=True)
        df.dropna(inplace=True)
        
        return df
    except Exception as e:
        print(f'获取数据失败: {e}')
        return None


def run_backtest(symbol, name, days=90):
    """运行回测"""
    print(f'\n{"="*60}')
    print(f'📊 {name} ({symbol}) 回测 ({days}天)')
    print(f'{"="*60}')
    
    df = get_yahoo_data(symbol, days)
    if df is None or len(df) < 30:
        print(f'数据不足 (仅{len(df) if df is not None else 0}条)')
        return None
    
    print(f'数据范围: {df.index[0].date()} ~ {df.index[-1].date()}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(FastTrendStrategy)
    
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)
    
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print('\n运行回测...')
    results = cerebro.run()
    strat = results[0]
    
    final_value = cerebro.broker.getvalue()
    initial_value = 1000000
    pnl = final_value - initial_value
    pnl_pct = (final_value / initial_value - 1) * 100
    
    print(f'\n{"="*60}')
    print('📈 回测结果')
    print(f'{"="*60}')
    print(f'初始资金: ${initial_value:,.2f}')
    print(f'最终资金: ${final_value:,.2f}')
    print(f'总收益: ${pnl:,.2f} ({pnl_pct:+.2f}%)')
    
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    
    sharpe_val = sharpe.get('sharperatio')
    print(f'\n夏普比率: {sharpe_val:.2f}' if sharpe_val else '夏普比率: N/A')
    print(f'最大回撤: {drawdown.get("max", {}).get("drawdown", 0):.2f}%')
    
    total_trades = trades.get('total', {}).get('total', 0)
    if total_trades > 0:
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        pnl_won = trades.get('won', {}).get('pnl', {}).get('total', 0)
        pnl_lost = trades.get('lost', {}).get('pnl', {}).get('total', 0)
        
        print(f'\n📊 交易统计:')
        print(f'  总交易次数: {total_trades}')
        print(f'  盈利次数: {won} (总盈利: ${pnl_won:,.2f})')
        print(f'  亏损次数: {lost} (总亏损: ${pnl_lost:,.2f})')
        if won + lost > 0:
            win_rate = won / (won + lost) * 100
            avg_win = pnl_won / won if won > 0 else 0
            avg_lost = abs(pnl_lost / lost) if lost > 0 else 0
            print(f'  胜率: {win_rate:.1f}%')
            print(f'  平均盈利: ${avg_win:,.2f}')
            print(f'  平均亏损: ${avg_lost:,.2f}')
            print(f'  盈亏比: {avg_win/avg_lost:.2f}' if avg_lost > 0 else '  盈亏比: N/A')
    
    return {
        'symbol': symbol,
        'name': name,
        'pnl_pct': pnl_pct,
        'sharpe': sharpe_val,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'trades': trades,
        'total_trades': total_trades
    }


if __name__ == '__main__':
    stocks = [
        ('NVDA', '英伟达', 90),
        ('VRT', 'Vertiv', 90),
        ('TSLA', '特斯拉', 90),
        ('AAPL', '苹果', 90),
        ('META', 'Meta', 90),
        ('AMD', 'AMD', 90),
    ]
    
    results = []
    for symbol, name, days in stocks:
        try:
            result = run_backtest(symbol, name, days)
            if result:
                results.append(result)
        except Exception as e:
            print(f'{name} 回测失败: {e}')
    
    if results:
        print(f'\n{"="*60}')
        print('📊 回测汇总')
        print(f'{"="*60}')
        print(f'\n{"标的":<10} {"收益率":>10} {"最大回撤":>10} {"交易次数":>10} {"胜率":>10}')
        print('-'*55)
        for r in results:
            won = r['trades'].get('won', {}).get('total', 0)
            lost = r['trades'].get('lost', {}).get('total', 0)
            win_rate = f'{won/(won+lost)*100:.1f}%' if (won + lost) > 0 else 'N/A'
            print(f'{r["name"]:<10} {r["pnl_pct"]:>+9.2f}% {r["max_drawdown"]:>+9.2f}% {r["total_trades"]:>10} {win_rate:>10}')
        
        avg_pnl = np.mean([r["pnl_pct"] for r in results])
        total_trades = sum([r["total_trades"] for r in results])
        print(f'\n📈 平均收益率: {avg_pnl:+.2f}%')
        print(f'📊 总交易次数: {total_trades}')
