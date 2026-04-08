#!/usr/bin/env python3
"""
四源共振策略回测
基于 OpenClaw 策略 v1.0
"""

import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from futu import *

class FourSourceStrategy(bt.Strategy):
    """四源共振策略 - 优化版"""
    
    params = (
        ('entry_score', 75),      # 入场阈值（提高）
        ('stop_loss', 0.08),      # 止损 8%（放宽）
        ('take_profit_1', 0.20),  # 止盈1 20%
        ('take_profit_2', 0.35),  # 止盈2 35%
        ('position_pct', 0.03),   # 单标的仓位 3%
    )
    
    def __init__(self):
        # 技术指标
        self.ma5 = bt.indicators.SMA(self.data.close, period=5)
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ma60 = bt.indicators.SMA(self.data.close, period=60)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        
        # MACD
        self.macd = bt.indicators.MACD(self.data.close)
        self.macd_signal = self.macd.macdsignal
        
        # 成交量均线
        self.vol_ma20 = bt.indicators.SMA(self.data.volume, period=20)
        
        # ATR用于动态止损
        self.atr = bt.indicators.ATR(self.data, period=14)
        
        # 记录交易
        self.trades = []
        self.order = None
        self.entry_price = None
        
    def next(self):
        if self.order:
            return
        
        # 计算技术得分
        score = 50  # 基础分
        
        # 趋势判断
        trend_up = self.ma20 > self.ma20[-5]  # 20日线向上
        
        # 条件判断
        golden_cross = self.ma5 > self.ma10 and self.ma5[-1] <= self.ma10[-1]
        volume_surge = self.data.volume > self.vol_ma20 * 1.3
        rsi_ok = 30 < self.rsi < 70
        macd_up = self.macd.macd > self.macd_signal
        above_ma20 = self.data.close > self.ma20
        above_ma60 = self.data.close > self.ma60
        
        if golden_cross:
            score += 15
        if volume_surge:
            score += 10
        if rsi_ok:
            score += 10
        if above_ma20:
            score += 10
        if above_ma60:
            score += 10
        if macd_up:
            score += 10
        if trend_up:
            score += 15  # 趋势向上加分
        
        # 统计满足的条件数
        conditions_met = sum([
            golden_cross,
            volume_surge,
            rsi_ok,
            above_ma20,
            macd_up
        ])
        
        if not self.position:
            # 入场：得分>=75 且 趋势向上 且 至少3个条件
            if score >= self.p.entry_score and trend_up and conditions_met >= 3:
                cash = self.broker.getcash()
                position_size = int(cash * self.p.position_pct / self.data.close[0])
                if position_size > 0:
                    self.order = self.buy(size=position_size)
                    self.entry_price = self.data.close[0]
                    self.atr_at_entry = self.atr[0]
        else:
            # 动态止损止盈
            pnl_pct = (self.data.close[0] - self.entry_price) / self.entry_price
            
            # 动态止损：入场价 - 2*ATR
            dynamic_stop = (self.entry_price - 2 * self.atr_at_entry) / self.entry_price
            
            if self.data.close[0] < self.entry_price * (1 - self.p.stop_loss):
                # 硬止损
                self.order = self.close()
            elif pnl_pct >= self.p.take_profit_2:
                self.order = self.close()
            elif pnl_pct >= self.p.take_profit_1 and self.position.size > 1:
                self.order = self.sell(size=self.position.size // 2)
                self.entry_price = self.data.close[0]  # 重置入场价


def get_historical_data(code, days=365):
    """从Futu获取历史数据"""
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
        print(f'获取数据失败: {data}')
        return None
    
    # 转换为Backtrader格式
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
    
    # 获取数据
    print(f'获取 {days} 天历史数据...')
    df = get_historical_data(code, days)
    
    if df is None or len(df) < 30:
        print('数据不足，跳过回测')
        return None
    
    print(f'数据范围: {df.index[0]} ~ {df.index[-1]}')
    print(f'数据条数: {len(df)}')
    
    # 创建回测引擎
    cerebro = bt.Cerebro()
    
    # 添加策略
    cerebro.addstrategy(FourSourceStrategy)
    
    # 添加数据
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    # 设置初始资金
    cerebro.broker.setcash(1000000)
    cerebro.broker.setcommission(commission=0.001)  # 手续费 0.1%
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # 运行回测
    print('\n运行回测...')
    results = cerebro.run()
    strat = results[0]
    
    # 输出结果
    print('\n' + '='*60)
    print('📈 回测结果')
    print('='*60)
    
    final_value = cerebro.broker.getvalue()
    initial_value = 1000000
    pnl = final_value - initial_value
    pnl_pct = (final_value / initial_value - 1) * 100
    
    print(f'初始资金: ${initial_value:,.2f}')
    print(f'最终资金: ${final_value:,.2f}')
    print(f'总收益: ${pnl:,.2f} ({pnl_pct:.2f}%)')
    
    # 分析指标
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
    # 回测标的
    stocks = [
        ('US.NVDA', '英伟达', 365),
        ('US.VRT', 'Vertiv', 365),
        ('HK.00700', '腾讯控股', 365),
        ('HK.09988', '阿里巴巴', 365),
    ]
    
    results = []
    for code, name, days in stocks:
        result = run_backtest(code, name, days)
        if result:
            results.append(result)
    
    # 汇总报告
    if results:
        print('\n' + '='*60)
        print('📊 回测汇总报告')
        print('='*60)
        print(f'\n{"标的":<15} {"收益率":<12} {"最大回撤":<12} {"夏普比率":<12}')
        print('-'*60)
        for r in results:
            sharpe_str = f'{r["sharpe"]:.2f}' if r['sharpe'] else 'N/A'
            print(f'{r["name"]:<15} {r["pnl_pct"]:>+.2f}%     {r["max_drawdown"]:>+.2f}%     {sharpe_str}')
pct"]:>+.2f}%     {r["max_drawdown"]:>+.2f}%     {sharpe_str:<12} {win_rate}')
        
        # 总体统计
        print('\n' + '='*60)
        print('📈 总体统计')
        print('='*60)
        avg_return = np.mean([r['pnl_pct'] for r in results])
        avg_sharpe = np.mean([r['sharpe'] for r in results if r['sharpe']])
        print(f'平均收益率: {avg_return:+.2f}%')
        print(f'平均夏普比率: {avg_sharpe:.2f}')
