#!/usr/bin/env python3
"""
简单趋势跟踪策略回测
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from futu import *

class TrendStrategy(bt.Strategy):
    """简单趋势跟踪策略"""
    
    params = (
        ('ma_short', 5),
        ('ma_long', 20),
        ('stop_loss', 0.08),
        ('take_profit', 0.20),
        ('position_pct', 0.05),
    )
    
    def __init__(self):
        self.ma_short = bt.indicators.SMA(self.data.close, period=self.params.ma_short)
        self.ma_long = bt.indicators.SMA(self.data.close, period=self.params.ma_long)
        self.order = None
        self.entry_price = None
        
    def next(self):
        if self.order:
            return
        
        if not self.position:
            # 入场：短期均线上穿长期均线
            if self.ma_short[0] > self.ma_long[0] and self.ma_short[-1] <= self.ma_long[-1]:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                    self.entry_price = self.data.close[0]
                    print(f'{self.data.datetime.date(0)}: 买入 {self.data.close[0]:.2f}')
        else:
            # 止损止盈
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price
            if pnl_pct <= -self.params.stop_loss:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 止损 {pnl_pct*100:.2f}%')
            elif pnl_pct >= self.params.take_profit:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 止盈 {pnl_pct*100:.2f}%')

def get_data(code, days=365):
    """获取历史数据"""
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    ret, data, _ = quote_ctx.request_history_kline(
        code=code,
        start=start_date,
        end=end_date,
        ktype=KLType.K_DAY,
        autype=AuType.QFQ
    )
    
    quote_ctx.close()
    
    if ret != RET_OK:
        return None
    
    data = data[['time_key', 'open', 'high', 'low', 'close', 'volume']]
    data.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
    data['datetime'] = pd.to_datetime(data['datetime'])
    data.set_index('datetime', inplace=True)
    
    return data

def run_backtest(code, name, days=365):
    """运行回测"""
    print(f'\n{"="*60}')
    print(f'📊 {name} ({code}) 回测')
    print(f'{"="*60}')
    
    df = get_data(code, days)
    if df is None or len(df) < 30:
        print('数据不足')
        return None
    
    print(f'数据范围: {df.index[0]} ~ {df.index[-1]}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TrendStrategy)
    
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
    
    print(f'\n夏普比率: {sharpe.get("sharperatio", "N/A")}')
    print(f'最大回撤: {drawdown.get("max", {}).get("drawdown", 0):.2f}%')
    
    if trades.get('total', {}).get('total', 0) > 0:
        print(f'\n交易统计:')
        print(f'  总交易次数: {trades["total"]["total"]}')
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        print(f'  盈利次数: {won}')
        print(f'  亏损次数: {lost}')
        if won + lost > 0:
            print(f'  胜率: {won/(won+lost)*100:.1f}%')
    
    return {
        'code': code,
        'name': name,
        'initial': initial_value,
        'final': final_value,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'sharpe': sharpe.get('sharperatio'),
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'trades': trades
    }

if __name__ == '__main__':
    stocks = [
        ('US.NVDA', '英伟达', 90),
        ('US.VRT', 'Vertiv', 90),
        ('HK.00700', '腾讯控股', 90),
        ('HK.09988', '阿里巴巴', 90),
        ('US.TSLA', '特斯拉', 90),
        ('US.AAPL', '苹果', 90),
        ('US.META', 'Meta', 90),
    ]
    
    results = []
    for code, name, days in stocks:
        try:
            result = run_backtest(code, name, days)
            if result:
                results.append(result)
        except Exception as e:
            print(f'{name} 回测失败: {e}')
    
    if results:
        print(f'\n{"="*60}')
        print('📊 回测汇总')
        print(f'{"="*60}')
        print(f'\n{"标的":<15} {"收益率":<12} {"最大回撤":<12} {"夏普比率":<12} {"胜率":<10}')
        print('-'*70)
        for r in results:
            sharpe_str = f'{r["sharpe"]:.2f}' if r['sharpe'] else 'N/A'
            won = r['trades'].get('won', {}).get('total', 0)
            lost = r['trades'].get('lost', {}).get('total', 0)
            win_rate = f'{won/(won+lost)*100:.1f}%' if (won + lost) > 0 else 'N/A'
            print(f'{r["name"]:<15} {r["pnl_pct"]:>+.2f}%     {r["max_drawdown"]:>+.2f}%     {sharpe_str:<12} {win_rate}')
        
        print(f'\n{"="*60}')
        print('📈 总体统计')
        print(f'{"="*60}')
        avg_return = np.mean([r['pnl_pct'] for r in results])
        avg_sharpe = np.mean([r['sharpe'] for r in results if r['sharpe']])
        print(f'平均收益率: {avg_return:+.2f}%')
        print(f'平均夏普比率: {avg_sharpe:.2f}')
