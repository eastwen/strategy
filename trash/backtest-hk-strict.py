#!/usr/bin/env python3
"""
港股策略 1.6 - 严格盈利版（仅做多）
适合港股市场：趋势性强、资金驱动

优化点：
1. 择时：MA20 > MA50 才交易（趋势向上）
2. 信号：突破信号 + 均线确认 + 成交量放大
3. 成交量：1.5倍放大
4. RSI：<70
5. 动态止损：ATR 2.0x（港股波动大）
6. 动态止盈：ATR 4.0x（2:1盈亏比）
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from futu import OpenQuoteContext, KLType, AuType

class HKStrictProfitStrategy(bt.Strategy):
    """港股严格盈利策略 1.6"""
    
    params = (
        ('position_pct', 0.10),      # 10%仓位（港股谨慎）
        ('hold_days', 8),            # 最大持仓8天
        ('breakout_period', 10),     # 10日突破
    )
    
    def __init__(self):
        # 趋势判断
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma50 = bt.indicators.SMA(self.data.close, period=50)
        
        # 入场信号
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma30 = bt.indicators.SMA(self.data.close, period=30)
        self.high_n = bt.indicators.Highest(self.data.high, period=self.params.breakout_period)
        self.adx = bt.indicators.ADX(self.data, period=14)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        self.atr = bt.indicators.ATR(self.data, period=14)
        
        # 成交量金叉
        self.vol_ma5 = bt.indicators.SMA(self.data.volume, period=5)
        self.vol_ma10 = bt.indicators.SMA(self.data.volume, period=10)
        
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
                # 动态计算止损止盈（港股波动大，用更宽止损）
                atr = self.atr[0]
                self.stop_price = self.entry_price - atr * 2.0  # 港股用2.0x ATR
                self.target_price = self.entry_price + atr * 4.0  # 2:1盈亏比
                
                print(f'ATR止损: 2.0x, 止盈: 4.0x, ATR值: {atr:.2f}')
                
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
            
            # 3. 移动止损（盈利超过8%后，保本+2%）
            if pnl_pct > 0.08:
                new_stop = self.entry_price * 1.02
                if new_stop > self.stop_price:
                    self.stop_price = new_stop
            
            # 4. 趋势反转离场（MA10死叉MA30）
            if self.ma10[0] < self.ma30[0] and self.ma10[-1] >= self.ma30[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 趋势反转 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 5. RSI超买离场 (>75)
            if self.rsi[0] > 75:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📊 RSI超买 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 6. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ⏰ 超时离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
        
        # ===== 入场信号（严格） =====
        else:
            # 信号1: 价格突破10日高点
            price_breakout = self.data.close[0] >= self.high_n[-1]
            
            # 信号2: 均线多头排列
            ma_trend_up = self.ma10[0] > self.ma30[0]
            
            # 信号3: 成交量放大（1.5倍）
            vol_surge = self.data.volume[0] > self.vol_ma[0] * 1.5
            
            # 信号4: 成交量金叉
            vol_cross_up = self.vol_ma5[0] > self.vol_ma10[0] and self.vol_ma5[-1] <= self.vol_ma10[-1]
            
            # 信号5: ADX趋势强度（>15）
            trend_strength = self.adx[0] > 15
            
            # 信号6: RSI适中
            rsi_ok = self.rsi[0] < 70 and self.rsi[0] > 30
            
            # ===== 入场条件 =====
            # 港股策略：必须突破 + 成交量 + 趋势
            required_signals = price_breakout and vol_surge
            
            # 增强信号：至少满足2个
            enhance_signals = [ma_trend_up, vol_cross_up, trend_strength]
            enhance_count = sum(enhance_signals)
            
            # 入场条件：必须信号 + 至少1个增强信号 + RSI合适
            if required_signals and enhance_count >= 1 and rsi_ok:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                
                if size > 0:
                    reasons = [f'突破{self.params.breakout_period}日高点', '量能放大1.5x']
                    if ma_trend_up:
                        reasons.append('均线多头')
                    if vol_cross_up:
                        reasons.append('成交量金叉')
                    if trend_strength:
                        reasons.append(f'趋势强度({self.adx[0]:.0f})')
                    
                    self.order = self.buy(size=size)
                    print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} ({", ".join(reasons)}, RSI:{self.rsi[0]:.0f})')


def get_futu_data(code, days=90):
    """从Futu获取港股K线数据"""
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
        
        ret, data, _ = quote_ctx.request_history_kline(
            code=code,
            start=start_date,
            end=end_date,
            ktype=KLType.K_DAY,
            autype=AuType.QFQ
        )
        
        if ret != 0:
            print(f'获取数据失败: {data}')
            return None
        
        df = pd.DataFrame({
            'datetime': pd.to_datetime(data['time_key']),
            'open': data['open'].astype(float),
            'high': data['high'].astype(float),
            'low': data['low'].astype(float),
            'close': data['close'].astype(float),
            'volume': data['volume'].astype(float)
        })
        df.set_index('datetime', inplace=True)
        df = df.sort_index()
        df.dropna(inplace=True)
        
        if len(df) > days:
            df = df.iloc[-days:]
        
        return df
        
    except Exception as e:
        print(f'获取数据失败: {e}')
        return None
    finally:
        quote_ctx.close()


def run_backtest(code, name, days=90):
    """运行回测"""
    print(f'\n{"="*60}')
    print(f'📊 {name} ({code}) 严格版回测 ({days}天)')
    print(f'{"="*60}')
    
    df = get_futu_data(code, days)
    if df is None or len(df) < 30:
        print(f'数据不足 (仅{len(df) if df is not None else 0}条)')
        return None
    
    print(f'数据范围: {df.index[0].date()} ~ {df.index[-1].date()}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(HKStrictProfitStrategy)
    
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.0018)  # 港股费率
    
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print('\n运行回测...')
    results = cerebro.run()
    strat = results[0]
    
    final_value = cerebro.broker.getvalue()
    pnl_pct = (final_value / 1000000 - 1) * 100
    
    print(f'\n📈 最终资金: HK${final_value:,.2f}')
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
        print(f'  亏损: {lost}次 (${pnnl_lost:,.2f})')
        if won + lost > 0:
            win_rate = won / (won + lost) * 100
            avg_win = pnl_won / won if won > 0 else 0
            avg_lost = abs(pnl_lost / lost) if lost > 0 else 0
            print(f'  胜率: {win_rate:.1f}%')
            print(f'  盈亏比: {avg_win/avg_lost:.2f}' if avg_lost > 0 else '  盈亏比: N/A')
    
    return {
        'code': code, 'name': name, 'pnl_pct': pnl_pct,
        'sharpe': sharpe_val, 'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'trades': trades, 'total_trades': total_trades
    }


if __name__ == '__main__':
    hk_stocks = [
        ('HK.00700', '腾讯', 90),
        ('HK.09988', '阿里巴巴', 90),
        ('HK.03690', '美团', 90),
        ('HK.09618', '京东健康', 90),
        ('HK.01810', '小米', 90),
        ('HK.09999', '网易', 90),
    ]
    
    print('\n' + '='*60)
    print('🇭🇰 港股策略 1.6 - 严格盈利版')
    print('='*60)
    print('入场条件：')
    print('1. 趋势向上 (MA20 > MA50, 价格>MA20)')
    print('2. 必须：价格突破10日高点 + 成交量放大1.5x')
    print('3. 增强：均线多头 / 成交量金叉 / ADX>15 (至少1个)')
    print('4. RSI 30-70')
    print('仓位: 10% | ATR止损: 2.0x | 止盈: 4.0x')
    print('='*60)
    
    results = []
    for code, name, days in hk_stocks:
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