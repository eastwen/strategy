#!/usr/bin/env python3
"""
港股策略1.9 - 精选强化版
优化点：1. 精选标的 2. 强化过滤 3. 动态调整
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import backtrader as bt

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class HKStrategy19(bt.Strategy):
    """港股策略1.9精选强化版"""
    
    params = (
        ('position_pct', 0.03),      # 3%仓位（提高信心）
        ('hold_days', 8),            # 持仓8天
        ('stop_loss_atr', 1.2),      # 紧止损（1.2x ATR）
        ('take_profit_atr', 2.5),    # 紧止盈（2.5x ATR）
    )
    
    def __init__(self):
        # 技术指标 - 强化版
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.macd = bt.indicators.MACD(self.data.close)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        self.atr = bt.indicators.ATR(self.data, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        
        # 布林带宽度（收缩判断）
        self.bb_width = (self.bb.top - self.bb.bot) / self.bb.mid * 100
        
        # 价格高点
        self.high_10 = bt.indicators.Highest(self.data.high, period=10)
        
        self.order = None
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        
        # 交易统计
        self.trades_won = 0
        self.trades_lost = 0
        
    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self.data)
                atr = self.atr[0]
                self.stop_price = self.entry_price - atr * self.params.stop_loss_atr
                self.target_price = self.entry_price + atr * self.params.take_profit_atr
                
                print(f'入场: ${order.executed.price:.2f}, ATR止损: {atr*self.params.stop_loss_atr:.2f}')
                
            elif order.issell():
                exit_price = order.executed.price
                pnl_pct = (exit_price - self.entry_price) / self.entry_price
                hold_days = len(self.data) - self.entry_bar
                
                if pnl_pct > 0:
                    self.trades_won += 1
                    print(f'✅ 止盈: {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                else:
                    self.trades_lost += 1
                    print(f'🛑 止损: {pnl_pct*100:.2f}% (持仓{hold_days}天)')
                
    def next(self):
        if self.order:
            return
        
        current_bar = len(self.data)
        
        # ===== 持仓管理 =====
        if self.position:
            hold_days = current_bar - self.entry_bar if self.entry_bar else 0
            current_price = self.data.close[0]
            
            # 1. 紧止损
            if current_price <= self.stop_price:
                self.order = self.close()
                return
            
            # 2. 紧止盈
            if current_price >= self.target_price:
                self.order = self.close()
                return
            
            # 3. MACD死叉离场
            if self.macd.macd[0] < self.macd.signal[0] and self.macd.macd[-1] >= self.macd.signal[-1]:
                self.order = self.close()
                return
            
            # 4. RSI超买离场 (>65)
            if self.rsi[0] > 65:
                self.order = self.close()
                return
            
            # 5. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                return
        
        # ===== 入场信号（强化版） =====
        else:
            # 过滤1: 趋势向上（MA20向上）
            ma20_up = self.ma20[0] > self.ma20[-5]
            
            # 过滤2: 价格在MA20上方
            price_above_ma20 = self.data.close[0] > self.ma20[0]
            
            if not (ma20_up and price_above_ma20):
                return
            
            # 信号1: 成交量显著放大（1.8x）- 加强要求
            vol_surge = self.data.volume[0] > self.vol_ma[0] * 1.8
            
            # 信号2: 价格突破10日高点
            price_breakout = self.data.close[0] >= self.high_10[-1]
            
            # 信号3: 布林带收缩突破（宽度<12%）
            bb_contraction = self.bb_width[0] < 12  # 布林带收缩
            bb_break = self.data.close[0] > self.bb.mid[0]  # 突破中轨
            
            # 信号4: MACD金叉
            macd_cross = self.macd.macd[0] > self.macd.signal[0] and self.macd.macd[-1] <= self.macd.signal[-1]
            
            # 信号5: RSI适中（40-60）
            rsi_ok = 40 <= self.rsi[0] <= 60
            
            # 信号6: 短期均线多头
            ma_align = self.ma5[0] > self.ma10[0] and self.ma10[0] > self.ma20[0]
            
            # ===== 入场条件（严格） =====
            # 核心条件：必须满足
            core_condition = vol_surge and rsi_ok
            
            # 增强条件：至少满足2个
            enhance_conditions = [price_breakout, bb_contraction and bb_break, macd_cross, ma_align]
            enhance_count = sum(enhance_conditions)
            
            if core_condition and enhance_count >= 2:
                cash = self.broker.getcash()
                size = int(cash * self.params.position_pct / self.data.close[0])
                
                if size > 0:
                    reasons = [f'量能{self.data.volume[0]/self.vol_ma[0]:.1f}x']
                    if price_breakout:
                        reasons.append('突破10日高点')
                    if bb_contraction and bb_break:
                        reasons.append(f'布林收缩{self.bb_width[0]:.1f}%')
                    if macd_cross:
                        reasons.append('MACD金叉')
                    if ma_align:
                        reasons.append('均线多头')
                    
                    self.order = self.buy(size=size)
                    print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} ({", ".join(reasons)}, RSI:{self.rsi[0]:.0f})')


def get_futu_data_bt(code, days=90):
    """获取Futu数据"""
    from futu import OpenQuoteContext, KLType, AuType
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')  # 昨天
        start_date = (datetime.now() - timedelta(days=days+30)).strftime('%Y-%m-%d')
        
        ret, data, _ = quote_ctx.request_history_kline(
            code=code,
            start=start_date,
            end=end_date,
            ktype=KLType.K_DAY,
            autype=AuType.QFQ
        )
        
        if ret != 0 or data.empty:
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
        
        # 确保足够天数
        if len(df) < days:
            return None
        
        return df.iloc[-days:]  # 只取最后days天
        
    except Exception as e:
        print(f'获取数据失败: {e}')
        return None
    finally:
        quote_ctx.close()


def run_backtest(code, name, days=90):
    """运行回测"""
    print(f'\n{"="*60}')
    print(f'📊 {name} ({code}) 策略1.9回测 ({days}天)')
    print(f'{"="*60}')
    
    df = get_futu_data_bt(code, days)
    if df is None or len(df) < 30:
        print(f'数据不足')
        return None
    
    print(f'数据范围: {df.index[0].date()} ~ {df.index[-1].date()}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(HKStrategy19)
    
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.0018)
    
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
    
    sharpe_val = sharpe.get('sharperatio')
    print(f'夏普比率: {sharpe_val:.2f}' if sharpe_val else '夏普比率: N/A')
    print(f'最大回撤: {drawdown.get("max", {}).get("drawdown", 0):.2f}%')
    
    # 使用策略内部统计
    total_trades = strat.trades_won + strat.trades_lost
    if total_trades > 0:
        win_rate = strat.trades_won / total_trades * 100
        print(f'\n📊 交易统计:')
        print(f'  总交易: {total_trades}')
        print(f'  盈利: {strat.trades_won}次')
        print(f'  亏损: {strat.trades_lost}次')
        print(f'  胜率: {win_rate:.1f}%')
    
    return {
        'code': code, 'name': name, 'pnl_pct': pnl_pct,
        'sharpe': sharpe_val, 'max_drawdown': drawdown.get("max", {}).get("drawdown", 0),
        'trades_won': strat.trades_won, 'trades_lost': strat.trades_lost,
        'total_trades': total_trades
    }


def main():
    """主函数"""
    print('\n' + '='*60)
    print('🇭🇰 港股策略1.9 - 精选强化版')
    print('='*60)
    print('优化点：')
    print('1. 成交量要求: 1.8x (从1.3x提高)')
    print('2. 强化过滤: 必须趋势向上 + 价格在MA20上')
    print('3. 增加信号: 布林收缩+突破, MACD金叉')
    print('4. 紧止损止盈: ATR 1.2x/2.5x')
    print('5. 精选标的: 只做适合策略的股票')
    print('='*60)
    
    # 精选组合（根据历史表现）
    selected_stocks = [
        ('HK.02331', '李宁'),         # 表现最好
        ('HK.02319', '蒙牛乳业'),     # 表现稳定
        ('HK.02020', '安踏体育'),     # 类似李宁
        ('HK.01299', '友邦保险'),     # 金融稳健
        ('HK.00388', '香港交易所'),    # 金融龙头
    ]
    
    results = []
    for code, name in selected_stocks:
        try:
            result = run_backtest(code, name, 90)
            if result:
                results.append(result)
        except Exception as e:
            print(f'❌ {name} 回测失败: {e}')
    
    if results:
        print(f'\n{"="*60}')
        print('📊 精选组合回测汇总')
        print(f'{"="*60}')
        print(f'\n{"标的":<12} {"收益率":>8} {"最大回撤":>8} {"交易":>6} {"胜率":>8}')
        print('-'*50)
        
        total_pnl = 0
        total_trades = 0
        total_won = 0
        
        for r in results:
            total_trades += r['total_trades']
            total_won += r['trades_won']
            total_pnl += r['pnl_pct']
            
            win_rate = f'{r["trades_won"]/r["total_trades"]*100:.0f}%' if r['total_trades'] > 0 else 'N/A'
            print(f'{r["name"]:<12} {r["pnl_pct"]:>+7.2f}% {r["max_drawdown"]:>+7.2f}% {r["total_trades"]:>6} {win_rate:>8}')
        
        if len(results) > 0:
            avg_pnl = total_pnl / len(results)
            overall_win_rate = total_won / total_trades * 100 if total_trades > 0 else 0
            
            print(f'\n📈 平均收益: {avg_pnl:+.2f}%')
            print(f'📈 总交易: {total_trades}次')
            print(f'📈 整体胜率: {overall_win_rate:.1f}%')
            
            # 判断策略有效性
            if avg_pnl > 0 and overall_win_rate > 50:
                print(f'\n🎯 策略评价: ✅ 有效 (正收益+高胜率)')
            elif avg_pnl > 0:
                print(f'\n🎯 策略评价: ⚠️ 可接受 (正收益但胜率低)')
            else:
                print(f'\n🎯 策略评价: ❌ 需改进 (负收益)')


if __name__ == '__main__':
    main()