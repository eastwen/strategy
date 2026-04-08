#!/usr/bin/env python3
"""
港股策略 1.6 - 优化版趋势跟踪（仅做多）
适合港股市场：趋势性强、资金驱动

版本历史:
- 1.0: 基础均线策略 (5/10均线金叉)
- 1.1: 参数优化
- 1.2: 趋势突破 (20日突破 + ADX确认) - 信号少
- 1.3: 趋势突破优化 (缩短周期，降低ADX阈值)
- 1.4: 双向交易 (已废弃)
- 1.5: 回滚单向
- 1.6: 优化版 (放宽条件+增加成交量金叉+优化止损)
- 1.4: 双向交易 (已废弃)
- 1.5: 回滚单向
- 1.6: 优化版 (放宽条件+成交量金叉)
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from futu import OpenQuoteContext, KLType, AuType

class HKTrendStrategy(bt.Strategy):
    """港股趋势策略 1.6 - 优化版"""
    
    params = (
        ('position_pct', 0.12),      # 12%仓位（提高）
        ('hold_days', 6),            # 最大持仓6天（缩短）
        ('breakout_period', 8),      # 8日突破（缩短）
        ('adx_threshold', 12),       # ADX阈值12（降低）
        ('stop_loss_pct', 0.035),    # 3.5%止损（收紧）
        ('take_profit_pct', 0.085),  # 8.5%止盈（提高）
    )
    
    def __init__(self):
        # 技术指标
        self.ma8 = bt.indicators.SMA(self.data.close, period=8)
        self.ma21 = bt.indicators.SMA(self.data.close, period=21)
        self.high_n = bt.indicators.Highest(self.data.high, period=self.params.breakout_period)
        self.adx = bt.indicators.ADX(self.data, period=14)
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        self.vol_ma_fast = bt.indicators.SMA(self.data.volume, period=5)  # 快速成交量
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        
        self.order = None
        self.entry_price = None
        self.entry_bar = None
        
    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self.data)
                
    def next(self):
        if self.order:
            return
        
        current_bar = len(self.data)
        
        # ===== 持仓管理 =====
        if self.position:
            hold_days = current_bar - self.entry_bar if self.entry_bar else 0
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price if self.entry_price else 0
            
            # 1. 固定止损
            if pnl_pct <= -self.params.stop_loss_pct:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 🛑 止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 2. 固定止盈
            if pnl_pct >= self.params.take_profit_pct:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ✅ 止盈 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 3. 移动止损（盈利6%后，保本+3%）
            if pnl_pct > 0.06:
                stop_price = self.entry_price * 1.03
                if self.data.close[0] < stop_price:
                    self.order = self.close()
                    print(f'{self.data.datetime.date(0)}: 🔒 移动止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                    return
            
            # 4. 趋势反转离场（均线死叉）
            if self.ma8[0] < self.ma21[0] and self.ma8[-1] >= self.ma21[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 趋势反转 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 5. ADX转弱离场
            if self.adx[0] < 10 and self.adx[-1] >= 10:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 趋势转弱 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 6. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ⏰ 超时离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
        
        # ===== 入场信号 =====
        else:
            # 条件1: 趋势向上（8日均线>21日均线）
            trend_up = self.ma8[0] > self.ma21[0]
            
            # 条件2: 价格突破N日高点
            breakout = self.data.close[0] >= self.high_n[-1] * 0.998  # 接近即可
            
            # 条件3: 成交量放大（快速成交量金叉慢速）
            vol_gold_cross = self.vol_ma_fast[0] > self.vol_ma[0] and self.vol_ma_fast[-1] <= self.vol_ma[-1]
            vol_surge = self.data.volume[0] > self.vol_ma[0] * 1.2  # 降低要求
            
            # 条件4: ADX趋势强度
            adx_ok = self.adx[0] > self.params.adx_threshold
            
            # 条件5: RSI不过热
            rsi_ok = self.rsi[0] < 68
            
            # 组合信号：
            # 方案A：趋势+突破+成交量金叉（强信号）
            signal_a = trend_up and breakout and vol_gold_cross and rsi_ok
            
            # 方案B：趋势+成交量放大+ADX确认（弱趋势也接受）
            signal_b = trend_up and vol_surge and adx_ok and rsi_ok and self.adx[0] > 10
            
            # 方案C：突破+强成交量+弱趋势（横盘突破）
            signal_c = breakout and self.data.volume[0] > self.vol_ma[0] * 1.5 and self.rsi[0] < 65
            
            if signal_a or signal_b or signal_c:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                
                if size > 0:
                    reason = []
                    if signal_a:
                        reason.append('成交量金叉突破')
                    elif signal_b:
                        reason.append('趋势+成交量')
                    else:
                        reason.append('横盘突破')
                    
                    adx_str = f'ADX:{self.adx[0]:.0f}' if self.adx[0] > 0 else ''
                    rsi_str = f'RSI:{self.rsi[0]:.0f}'
                    self.order = self.buy(size=size)
                    print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} ({", ".join(reason)}, {adx_str}, {rsi_str})')
    
    def __init__(self):
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma30 = bt.indicators.SMA(self.data.close, period=30)
        self.high_n = bt.indicators.Highest(self.data.high, period=self.params.breakout_period)
        self.adx = bt.indicators.ADX(self.data, period=14)
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        
        self.order = None
        self.entry_price = None
        self.entry_bar = None
        
    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self.data)
                
    def next(self):
        if self.order:
            return
        
        current_bar = len(self.data)
        
        # ===== 持仓管理 =====
        if self.position:
            hold_days = current_bar - self.entry_bar if self.entry_bar else 0
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price if self.entry_price else 0
            
            # 1. 固定止损
            if pnl_pct <= -self.params.stop_loss_pct:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 🛑 止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 2. 固定止盈
            if pnl_pct >= self.params.take_profit_pct:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ✅ 止盈 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 3. 移动止损（盈利5%后，保本+2%）
            if pnl_pct > 0.05:
                stop_price = self.entry_price * 1.02
                if self.data.close[0] < stop_price:
                    self.order = self.close()
                    print(f'{self.data.datetime.date(0)}: 🔒 移动止损 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                    return
            
            # 4. 趋势反转离场（均线死叉）
            if self.ma10[0] < self.ma30[0] and self.ma10[-1] >= self.ma30[-1]:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: 📉 趋势反转 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
            
            # 5. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                print(f'{self.data.datetime.date(0)}: ⏰ 超时离场 {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                return
        
        # ===== 入场信号 =====
        else:
            # 条件1: 趋势向上（均线多头）
            trend_up = self.ma10[0] > self.ma30[0]
            
            # 条件2: 趋势强度
            trend_strong = self.adx[0] > self.params.adx_threshold
            
            # 条件3: 价格突破N日高点
            breakout = self.data.close[0] >= self.high_n[-1]
            
            # 条件4: 成交量放大
            vol_confirm = self.data.volume[0] > self.vol_ma[0] * 1.3
            
            # 条件5: RSI不过热
            rsi_ok = self.rsi[0] < 70
            
            # 组合信号（趋势+突破+量能）
            signal = trend_up and breakout and vol_confirm and rsi_ok
            
            # 趋势强时可以不要ADX条件
            if not trend_strong and (self.adx[0] > 10):
                # ADX较弱但仍有趋势
                signal = signal and self.adx[0] > 10
            
            if signal:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                
                if size > 0:
                    self.order = self.buy(size=size)
                    adx_str = f'ADX:{self.adx[0]:.0f}' if self.adx[0] > 0 else ''
                    print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} (突破{self.params.breakout_period}日高点, {adx_str})')


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
    print(f'📊 {name} ({code}) 回测 ({days}天)')
    print(f'{"="*60}')
    
    df = get_futu_data(code, days)
    if df is None or len(df) < 30:
        print(f'数据不足 (仅{len(df) if df is not None else 0}条)')
        return None
    
    print(f'数据范围: {df.index[0].date()} ~ {df.index[-1].date()}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(HKTrendStrategy)
    
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
        print(f'  亏损: {lost}次 (${pnl_lost:,.2f})')
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
    print('🇭🇰 港股策略 1.5 回测')
    print('='*60)
    print('策略: 10日突破 + 均线趋势 + 成交量放大')
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
        
        avg_pnl = np.mean([r["pnl_pct"] for r in results])
        total_trades = sum([r["total_trades"] for r in results])
        print(f'\n📈 平均收益: {avg_pnl:+.2f}% | 总交易: {total_trades}次')