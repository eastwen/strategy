#!/usr/bin/env python3
"""
美股策略 1.6 - 严格盈利版（仅做多）
入场严格 + 盈利优先

优化点：
1. 择时：MA20 > MA50 才交易（趋势向上）
2. 信号：≥2个技术信号 或 1个+强背离
3. 成交量：1.8倍放大
4. RSI：<65（不过热）
5. 动态止损：ATR 1.8x（宽止损给波动率）
6. 动态止盈：ATR 4.0x（3:1盈亏比）
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests

class USStrictProfitStrategy(bt.Strategy):
    """美股严格盈利策略 1.6"""
    
    params = (
        ('position_pct', 0.12),      # 12%仓位（适中）
        ('hold_days', 6),            # 最大持仓6天
    )
    
    def __init__(self):
        # 趋势判断
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma50 = bt.indicators.SMA(self.data.close, period=50)
        
        # 入场信号
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
                # 动态计算止损止盈（根据ATR和波动率）
                atr = self.atr[0]
                price_range = (self.bb.top[0] - self.bb.bot[0]) / self.bb.mid[0]
                
                # 波动率大 => 宽止损
                if price_range > 0.15:  # 布林带宽 >15%
                    stop_mult = 2.0  # 宽止损
                    profit_mult = 4.5  # 高止盈
                else:
                    stop_mult = 1.8
                    profit_mult = 4.0
                
                self.stop_price = self.entry_price - atr * stop_mult
                self.target_price = self.entry_price + atr * profit_mult
                
                print(f'ATR止损: {stop_mult:.1f}x, 止盈: {profit_mult:.1f}x, 波动率: {price_range:.1%}')
                
    def next(self):
        if self.order:
            return
        
        current_bar = len(self.data)
        
        # ===== 择时过滤 =====
        # 1. 趋势必须向上（MA20 > MA50）
        trend_up = self.ma20[0] > self.ma50[0]
        
        # 2. 价格在MA20上方
        price_above_ma20 = self.data.close[0] > self.ma20[0]
        
        if not (trend_up and price_above_ma20):
            return  # 不满足趋势条件，不交易
        
        # ===== 持仓管理 =====
        if self.position:
            hold_days = current_bar - self.entry_bar if self.entry_bar else 0
            current_price = self.data.close[0]
            pnl_pct = (current_price - self.entry_price) / self.entry_price
            
            # 1. ATR动态止损
            if current_price <= self.stop_price:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 🛑 止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 2. ATR动态止盈
            if current_price >= self.target_price:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ✅ 止盈 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 3. 移动止损（盈利超过8%后，保本+3%）
            if pnl_pct > 0.08:
                new_stop = self.entry_price * 1.03
                if new_stop > self.stop_price:
                    self.stop_price = new_stop
            
            # 4. RSI超买离场 (>70)
            if self.rsi[0] > 70:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📊 RSI超买 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 5. MACD死叉离场
            if self.macd.macd[0] < self.macd.signal[0] and self.macd.macd[-1] >= self.macd.signal[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 MACD离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 6. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ⏰ 超时离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
        
        # ===== 入场信号（严格） =====
        else:
            # 信号1: MACD金叉
            macd_cross = self.macd.macd[0] > self.macd.signal[0] and self.macd.macd[-1] <= self.macd.signal[-1]
            
            # 信号2: 短期均线金叉
            ma_cross = self.ma5[0] > self.ma10[0] and self.ma5[-1] <= self.ma10[-1]
            
            # 信号3: 成交量显著放大（1.8倍）
            vol_surge = self.data.volume[0] > self.vol_ma[0] * 1.8
            
            # 信号4: 价格突破布林带中轨
            bb_break = self.data.close[0] > self.bb.mid[0] and self.data.close[-1] <= self.bb.mid[-1]
            
            # 信号5: RSI背离（强信号）
            price_near_low = self.data.close[0] <= self.price_low_20[-1] * 1.02
            rsi_not_low = self.rsi[0] > self.rsi_low_20[-1] * 1.15  # RSI比20日低点高15%（更强背离）
            rsi_divergence = price_near_low and rsi_not_low
            
            # 信号6: RSI超卖反弹（强信号）
            rsi_oversold = self.rsi[0] < 35 and self.rsi[-1] < 30  # 更严格的超卖
            
            # RSI不过热
            rsi_ok = self.rsi[0] < 65  # 比之前更严格
            
            # ===== 入场条件 =====
            # 方案A: 技术信号≥2 + RSI不过热
            tech_signals = [macd_cross, ma_cross, vol_surge, bb_break]
            tech_count = sum(tech_signals)
            
            # 方案B: 技术信号≥1 + 强背离信号
            strong_signals = [rsi_divergence, rsi_oversold]
            strong_count = sum(strong_signals)
            
            # 入场条件A（技术为主）
            condition_a = tech_count >= 2 and rsi_ok
            
            # 入场条件B（背离为主）
            condition_b = tech_count >= 1 and strong_count >= 1 and rsi_ok
            
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
                        reasons.append('量能1.8x')
                    if bb_break:
                        reasons.append('突破中轨')
                    if rsi_divergence:
                        reasons.append('RSI强背离')
                    if rsi_oversold:
                        reasons.append('RSI超卖反弹')
                    
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
    print(f'📊 {name} ({symbol}) 严格版回测 ({days}天)')
    print(f'{"="*60}')
    
    df = get_yahoo_data(symbol, days)
    if df is None or len(df) < 30:
        print(f'数据不足 (仅{len(df) if df is not None else 0}条)')
        return None
    
    print(f'数据范围: {df.index[0].date()} ~ {df.index[-1].date()}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(USStrictProfitStrategy)
    
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
    print('🇺🇸 美股策略 1.6 - 严格盈利版')
    print('='*60)
    print('入场条件：')
    print('1. 趋势向上 (MA20 > MA50, 价格>MA20)')
    print('2. 技术信号≥2 或 信号≥1+强背离')
    print('3. 成交量放大1.8x')
    print('4. RSI < 65')
    print('仓位: 12% | ATR止损: 1.8-2.0x | 止盈: 4.0-4.5x')
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
        
        valid_results = [r for r in results if r["total_trades"] > 0]
        if valid_results:
            avg_pnl = np.mean([r["pnl_pct"] for r in valid_results])
            total_trades = sum([r["total_trades"] for r in valid_results])
            
            win_rates = []
            for r in valid_results:
                won = r['trades'].get('won', {}).get('total', 0)
                lost = r['trades'].get('lost', {}).get('total', 0)
                if won + lost > 0:
                    win_rates.append(won / (won + lost) * 100)
            
            avg_win_rate = np.mean(win_rates) if win_rates else 0
            
            print(f'\n📈 平均收益: {avg_pnl:+.2f}% | 总交易: {total_trades}次 | 平均胜率: {avg_win_rate:.1f}%')
        else:
            print('\n📈 无交易信号')