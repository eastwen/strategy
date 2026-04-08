#!/usr/bin/env python3
"""
港股策略1.8回测
基于优化后的港股策略进行90天回测
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import backtrader as bt

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class HKStrategy18(bt.Strategy):
    """港股策略1.8回测版本"""
    
    params = (
        ('position_pct', 0.02),      # 2%仓位（小仓位测试）
        ('hold_days', 10),           # 最大持仓10天
        ('stop_loss_atr', 1.5),      # ATR止损倍数
        ('take_profit_atr', 3.0),    # ATR止盈倍数
    )
    
    def __init__(self):
        # 技术指标
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma50 = bt.indicators.SMA(self.data.close, period=50)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=10)
        self.atr = bt.indicators.ATR(self.data, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        
        # 价格高点
        self.high_5 = bt.indicators.Highest(self.data.high, period=5)
        
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
            pnl_pct = (current_price - self.entry_price) / self.entry_price
            
            # 1. ATR动态止损
            if current_price <= self.stop_price:
                self.order = self.close()
                return
            
            # 2. ATR动态止盈
            if current_price >= self.target_price:
                self.order = self.close()
                return
            
            # 3. RSI超买离场 (>70)
            if self.rsi[0] > 70:
                self.order = self.close()
                return
            
            # 4. 价格跌破MA10
            if current_price < self.ma10[0] and self.data.close[-1] >= self.ma10[-1]:
                self.order = self.close()
                return
            
            # 5. 最大持仓天数
            if hold_days >= self.params.hold_days:
                self.order = self.close()
                return
        
        # ===== 入场信号（策略1.8核心逻辑） =====
        else:
            # 基础条件：趋势向上（MA20 > MA50）
            trend_up = self.ma20[0] > self.ma50[0]
            price_above_ma20 = self.data.close[0] > self.ma20[0]
            
            if not (trend_up and price_above_ma20):
                return
            
            # 技术信号（策略1.8优化版）
            # 强条件1: 成交量放大1.3x
            vol_surge = self.data.volume[0] > self.vol_ma[0] * 1.3
            
            # 强条件2: 价格突破5日高点
            price_breakout = self.data.close[0] >= self.high_5[-1]
            
            # 弱条件1: 均线金叉
            ma_cross = self.ma5[0] > self.ma10[0]
            
            # 弱条件2: RSI适中
            rsi_ok = 30 <= self.rsi[0] <= 70
            
            # 策略1.8入场条件：至少1个强条件 + 弱条件不限
            has_strong_signal = vol_surge or price_breakout
            
            if has_strong_signal:
                # 计算综合评分（模拟）
                tech_score = 50  # 基础分
                if vol_surge:
                    tech_score += 20
                if price_breakout:
                    tech_score += 15
                if ma_cross:
                    tech_score += 10
                if rsi_ok:
                    tech_score += 5
                
                # 模拟情绪评分（假设VHSI正常）
                sentiment_score = 70
                news_score = 60
                
                # 权重计算（情绪45%，技术30%，新闻25%）
                total_score = (
                    news_score * 0.25 +
                    tech_score * 0.30 +
                    sentiment_score * 0.45
                )
                
                # 阈值判断（65分）
                if total_score >= 65:
                    cash = self.broker.getcash()
                    size = int(cash * self.params.position_pct / self.data.close[0])
                    
                    if size > 0:
                        reasons = []
                        if vol_surge:
                            reasons.append(f'量能{self.data.volume[0]/self.vol_ma[0]:.1f}x')
                        if price_breakout:
                            reasons.append('突破高点')
                        if ma_cross:
                            reasons.append('金叉')
                        
                        self.order = self.buy(size=size)
                        print(f'{self.data.datetime.date(0)}: 🚀 买入 ${self.data.close[0]:.2f} (评分:{total_score:.0f}, {", ".join(reasons)})')


def get_futu_data_bt(code, days=90):
    """获取Futu数据并转换为Backtrader格式"""
    from futu import OpenQuoteContext, KLType, AuType
    from datetime import datetime, date, timedelta
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        end_date = date.today().strftime('%Y-%m-%d')
        start_date = (date.today() - timedelta(days=days*2)).strftime('%Y-%m-%d')
        
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
        
        if len(df) > days:
            df = df.iloc[-days:]
        
        return df
        
    except Exception as e:
        print(f'获取数据失败: {e}')
        return None
    finally:
        quote_ctx.close()


def run_backtest(code, name, days=90):
    """运行单只股票回测"""
    print(f'\n{"="*60}')
    print(f'📊 {name} ({code}) 策略1.8回测 ({days}天)')
    print(f'{"="*60}')
    
    df = get_futu_data_bt(code, days)
    if df is None or len(df) < 30:
        print(f'数据不足 (仅{len(df) if df is not None else 0}条)')
        return None
    
    print(f'数据范围: {df.index[0].date()} ~ {df.index[-1].date()}')
    print(f'数据条数: {len(df)}')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(HKStrategy18)
    
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
        'trades': trades, 'total_trades': total_trades,
        'won': won if total_trades > 0 else 0,
        'lost': lost if total_trades > 0 else 0
    }


def main():
    """主函数"""
    print('\n' + '='*60)
    print('🇭🇰 港股策略1.8回测')
    print('='*60)
    print('优化点：')
    print('1. 评分阈值: 70 → 65')
    print('2. 技术条件: 2个 → 1个强条件')
    print('3. 情绪权重: 35% → 45%')
    print('4. 成交量要求: 1.5x → 1.3x')
    print('5. 仓位: 2% (小仓位测试)')
    print('='*60)
    
    # 测试股票（根据全市场测试结果选择）
    test_stocks = [
        # 科技龙头（适合度高）
        ('HK.00700', '腾讯控股'),
        ('HK.03690', '美团-W'),
        ('HK.09618', '京东集团-SW'),
        
        # 金融股（适合度83%）
        ('HK.01299', '友邦保险'),
        ('HK.00388', '香港交易所'),
        ('HK.00939', '建设银行'),
        
        # 消费股（适合度高）
        ('HK.02319', '蒙牛乳业'),
        ('HK.02020', '安踏体育'),
        ('HK.02331', '李宁'),
        
        # 工业股（适合度高）
        ('HK.02382', '舜宇光学科技'),
        ('HK.02313', '申洲国际'),
    ]
    
    results = []
    for code, name in test_stocks:
        try:
            result = run_backtest(code, name, 90)
            if result:
                results.append(result)
        except Exception as e:
            print(f'❌ {name} 回测失败: {e}')
    
    if results:
        print(f'\n{"="*60}')
        print('📊 回测汇总')
        print(f'{"="*60}')
        print(f'\n{"标的":<12} {"收益率":>8} {"最大回撤":>8} {"交易":>6} {"胜率":>8} {"盈亏比":>8}')
        print('-'*55)
        
        total_pnl = 0
        total_trades = 0
        total_won = 0
        total_lost = 0
        
        for r in results:
            won = r['won']
            lost = r['lost']
            total_trades += r['total_trades']
            total_won += won
            total_lost += lost
            
            win_rate = f'{won/(won+lost)*100:.0f}%' if (won + lost) > 0 else 'N/A'
            avg_win = r['trades'].get('won', {}).get('pnl', {}).get('total', 0) / won if won > 0 else 0
            avg_lost = abs(r['trades'].get('lost', {}).get('pnl', {}).get('total', 0) / lost) if lost > 0 else 0
            profit_ratio = f'{avg_win/avg_lost:.2f}' if avg_lost > 0 else 'N/A'
            
            total_pnl += r['pnl_pct']
            
            print(f'{r["name"]:<12} {r["pnl_pct"]:>+7.2f}% {r["max_drawdown"]:>+7.2f}% {r["total_trades"]:>6} {win_rate:>8} {profit_ratio:>8}')
        
        if len(results) > 0:
            avg_pnl = total_pnl / len(results)
            overall_win_rate = total_won / (total_won + total_lost) * 100 if (total_won + total_lost) > 0 else 0
            
            print(f'\n📈 平均收益: {avg_pnl:+.2f}%')
            print(f'📈 总交易: {total_trades}次')
            print(f'📈 整体胜率: {overall_win_rate:.1f}%')
            
            # 按类别分析
            categories = {}
            for r in results:
                cat = '金融' if '保险' in r['name'] or '银行' in r['name'] or '交易所' in r['name'] else \
                      '消费' if '乳业' in r['name'] or '体育' in r['name'] or '李宁' in r['name'] else \
                      '科技' if '腾讯' in r['name'] or '美团' in r['name'] or '京东' in r['name'] else \
                      '工业'
                
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(r['pnl_pct'])
            
            print(f'\n📊 按类别表现:')
            for cat, pnls in categories.items():
                avg = np.mean(pnls)
                print(f'  {cat:<8}: {avg:+.2f}% (n={len(pnls)})')


if __name__ == '__main__':
    main()