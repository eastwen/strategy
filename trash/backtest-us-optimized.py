#!/usr/bin/env python3
"""
美股策略 1.5 - 优化版多信号共振（仅做多）
适合美股市场：效率高、资讯驱动、机构主导

版本历史:
- 1.0: 基础均线策略 (3/7均线金叉)
- 1.1: 参数优化
- 1.2: 多信号共振 (MACD+均线+成交量+布林带) ✅ +0.55%
- 1.3: 双向交易 (已废弃) -0.01%
- 1.4: 回滚单向 (bug)
- 1.5: 优化版 (提高仓位+动态止损+RSI背离)
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests

class USMomentumStrategy(bt.Strategy):
    """美股动量策略 1.5 - 优化版"""
    
    params = (
        ('position_pct', 0.15),      # 15%仓位（提高）
        ('hold_days', 5),            # 最大持仓5天
        ('stop_loss_atr', 1.5),      # ATR 1.5倍动态止损
        ('take_profit_atr', 3.0),    # ATR 3倍动态止盈
    )
    
    def __init__(self):
        # 技术指标
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.macd = bt.indicators.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        self.atr = bt.indicators.ATR(self.data, period=14)
        
        # 价格新低检测
        self.price_low_20 = bt.indicators.Lowest(self.data.close, period=20)
        self.rsi_low_20 = bt.indicators.Lowest(self.rsi, period=20)
        
        self.order = None
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        
    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self.data)
                atr = self.atr[0]
                self.stop_price = self.entry_price - atr * self.params.stop_loss_atr
                self.target_price = self.entry_price + atr * self.params.take_profit_atr
                
    def next(self):
        if self.order:
            return
        
        current_bar = len(self.data)
        
        # ===== 持仓管理 =====
        if self.position:
            hold_days = current_bar - self.entry_bar if self.entry_bar else 0
            current_price = self.data.close[0]
            
            # 1. ATR动态止损
            if current_price <= self.stop_price:
                pnl_pct = (current_price - self.entry_price) / self.entry_price
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 🛑 止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 2. ATR动态止盈
            if current_price >= self.target_price:
                pnl_pct = (current_price - self.entry_price) / self.entry_price
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ✅ 止盈 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 3. 移动止损（盈利超过5%后，保本+2%）
            pnl_pct = (current_price - self.entry_price) / self.entry_price
            if pnl_pct > 0.05:
                new_stop = self.entry_price * 1.02
                if new_stop > self.stop_price:
                    self.stop_price = new_stop
            
            # 4. RSI超买离场 (>75)
            if self.rsi[0] > 75:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📊 RSI超买 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 5. MACD死叉离场
            if self.macd.macd[0] < self.macd.signal[0] and self.macd.macd[-1] >= self.macd.signal[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 MACD离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 6. 均线死叉
            if self.ma5[0] < self.ma10[0] and self.ma5[-1] >= self.ma10[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 均线离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 7. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ⏰ 超时离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
        
        # ===== 入场信号 =====
        else:
            # 信号1: MACD金叉
            macd_cross = self.macd.macd[0] > self.macd.signal[0] and self.macd.macd[-1] <= self.macd.signal[-1]
            
            # 信号2: 均线金叉
            ma_cross = self.ma5[0] > self.ma10[0] and self.ma5[-1] <= self.ma10[-1]
            
            # 信号3: 成交量放大
            vol_surge = self.data.volume[0] > self.vol_ma[0] * 1.5
            
            # 信号4: 价格突破布林带中轨
            bb_break = self.data.close[0] > self.bb.mid[0] and self.data.close[-1] <= self.bb.mid[-1]
            
            # 信号5: RSI背离（价格新低但RSI不创新低）
            price_near_low = self.data.close[0] <= self.price_low_20[-1] * 1.02  # 价格接近20日低点
            rsi_not_low = self.rsi[0] > self.rsi_low_20[-1] * 1.1  # RSI比20日低点高10%
            rsi_divergence = price_near_low and rsi_not_low
            
            # 信号6: RSI超卖反弹
            rsi_oversold = self.rsi[0] < 40 and self.rsi[-1] < 35
            
            # RSI不过热
            rsi_ok = self.rsi[0] < 70
            
            # 组合信号：至少2个技术信号
            signals = [macd_cross, ma_cross, vol_surge, bb_break]
            signal_count = sum(signals)
            
            # 入场条件A：技术信号（≥2）+ RSI不过热
            condition_a = signal_count >= 2 and rsi_ok
            
            # 入场条件B：技术信号（1）+ RSI背离
            condition_b = signal_count >= 1 and rsi_divergence and rsi_ok
            
            if condition_a or condition_b:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                
                if size > 0:
                    reasons = []
                    if macd_cross:
                        reasons.append('MACD金叉')
                    if ma_cross:
                        reasons.append('均线金叉')
                    if vol_surge:
                        reasons.append('量能放大')
                    if bb_break:
                        reasons.append('突破中轨')
                    if rsi_divergence:
                        reasons.append('RSI背离')
                    if rsi_oversold:
                        reasons.append('RSI超卖')
                    
                    self.order = self.buy(size=size)
                    print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} ({", ".join(reasons)}, RSI:{self.rsi[0]:.0f})')


def get_yahoo_data(symbol, days=90):
    """从Yahoo Finance获取数据"""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    params = {'range': f'{days}d', 'interval': '1d'}
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
    cerebro.addstrategy(USMomentumStrategy)
    
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.0004)  # 美股费率
    
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print('\n运行回测...')
    results = cerebro.run()
    strat = results[0]
    
    final_value = cerebro.broker.getvalue()
    pnl_pct = (final_value / 1000000 - 1) * 100
    
    print(f'\n📈 最终资金: ${final_value:,.2f}')
    print(f'📈 总收益: {pnl_pct:+.2f}%')
    
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    
    sharpe_val = sharpe.get('sharperatio')
    print(f'夏普比率: {sharpe_val:.2f}' if sharpe_val else '夏普比率: N/A')
    print(f'最大回撤: {drawdown.get("max", {}).get("drawdown", 0):.2f}%')
    
    total_trades = trades.get('total', {}).get('total', 0)
    if total_trades > 0:
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        pnl_won = trades.get('won', {}).get('pnl', {}).get('total', 0)
        pnl_lost = trades.get('lost', {}).get('pnl', {}).get('total', 0)
        
        print(f'\n📊 交易统计:')
        print(f'  总交易: {total_trades}')
        print(f'  盈利: {won}次 (${pnl_won:,.2f})')
        print(f'  亏损: {lost}次 (${pnl_lost:,.2f})')
        if won + lost > 0:
            win_rate = won / (won + lost) * 100
            avg_win = pnl_won / won if won > 0 else 0
            avg_lost = abs(pnl_lost / lost) if lost > 0 else 0
            print(f'  胜率: {win_rate:.1f}%')
            print(f'  盈亏比: {avg_win/avg_lost:.2f}' if avg_lost > 0 else '  盈亏比: N/A')
    
    return {
        'symbol': symbol, 'name': name, 'pnl_pct': pnl_pct,
        'sharpe': sharpe_val, 'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'trades': trades, 'total_trades': total_trades
    }


if __name__ == '__main__':
    us_stocks = [
        ('NVDA', '英伟达', 90),
        ('VRT', 'Vertiv', 90),
        ('TSLA', '特斯拉', 90),
        ('AAPL', '苹果', 90),
        ('META', 'Meta', 90),
        ('AMD', 'AMD', 90),
    ]
    
    print('\n' + '='*60)
    print('🇺🇸 美股策略 1.5 优化版回测')
    print('='*60)
    print('策略: ATR动态止损止盈 + 多信号共振 + RSI背离')
    print('仓位: 15% | 止损: ATR 1.5x | 止盈: ATR 3x')
    print('='*60)
    
    results = []
    for symbol, name, days in us_stocks:
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
        print(f'\n{"标的":<10} {"收益率":>10} {"最大回撤":>10} {"交易":>8} {"胜率":>8}')
        print('-'*50)
        for r in results:
            won = r['trades'].get('won', {}).get('total', 0)
            lost = r['trades'].get('lost', {}).get('total', 0)
            win_rate = f'{won/(won+lost)*100:.0f}%' if (won + lost) > 0 else 'N/A'
            print(f'{r["name"]:<10} {r["pnl_pct"]:>+9.2f}% {r["max_drawdown"]:>+9.2f}% {r["total_trades"]:>8} {win_rate:>8}')
        
        avg_pnl = np.mean([r["pnl_pct"] for r in results])
        total_trades = sum([r["total_trades"] for r in results])
        print(f'\n📈 平均收益: {avg_pnl:+.2f}% | 总交易: {total_trades}次')