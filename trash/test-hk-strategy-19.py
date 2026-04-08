#!/usr/bin/env python3
"""
港股策略简化测试 - 直接测试李宁
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

def simulate_strategy_19():
    """模拟策略1.9在历史数据上的表现"""
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        # 获取李宁历史数据
        end_date = '2026-03-20'
        start_date = '2025-11-01'
        
        ret, data, _ = quote_ctx.request_history_kline(
            code='HK.02331',
            start=start_date,
            end=end_date,
            ktype=KLType.K_DAY,
            autype=AuType.QFQ
        )
        
        if ret != 0 or data.empty:
            print("数据获取失败")
            return
        
        df = pd.DataFrame({
            'date': pd.to_datetime(data['time_key']),
            'open': data['open'].astype(float),
            'high': data['high'].astype(float),
            'low': data['low'].astype(float),
            'close': data['close'].astype(float),
            'volume': data['volume'].astype(float)
        })
        df.set_index('date', inplace=True)
        
        print(f"\n数据范围: {df.index[0].date()} ~ {df.index[-1].date()}")
        print(f"数据条数: {len(df)}")
        print(f"起始价格: {df['close'].iloc[0]:.2f}")
        print(f"结束价格: {df['close'].iloc[-1]:.2f}")
        print(f"价格变动: {(df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100:+.2f}%")
        
        # 计算技术指标
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['vol_ma10'] = df['volume'].rolling(10).mean()
        df['vol_ratio'] = df['volume'] / df['vol_ma10']
        
        # 计算ATR
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['atr'] = df['tr'].rolling(14).mean()
        
        # 计算RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 布林带
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_width'] = (df['bb_mid'] + 2*df['bb_std'] - (df['bb_mid'] - 2*df['bb_std'])) / df['bb_mid'] * 100
        
        # 模拟交易
        print(f"\n{'='*60}")
        print("模拟交易信号检测")
        print(f"{'='*60}")
        
        position = 0
        entry_price = 0
        entry_date = None
        trades = []
        initial_capital = 1000000
        capital = initial_capital
        position_size = 0.03  # 3%仓位
        
        for i in range(30, len(df)-1):  # 从第30天开始（有足够数据）
            if position == 0:
                # 入场条件检查
                row = df.iloc[i]
                prev_row = df.iloc[i-1]
                
                # 条件1: 趋势向上（MA20上升）
                ma20_up = row['ma20'] > df['ma20'].iloc[i-5] if i >= 35 else True
                
                # 条件2: 价格在MA20上方
                price_above_ma20 = row['close'] > row['ma20']
                
                # 条件3: 成交量放大1.8x
                vol_surge = row['vol_ratio'] >= 1.8
                
                # 条件4: RSI适中（40-60）
                rsi_ok = 40 <= row['rsi'] <= 60
                
                # 增强条件
                price_breakout = row['close'] >= df['high'].iloc[i-10:i].max() if i >= 40 else False
                bb_contraction = row['bb_width'] < 12
                bb_break = row['close'] > row['bb_mid']
                
                # 核心入场条件
                core_condition = vol_surge and rsi_ok and ma20_up and price_above_ma20
                enhance_count = sum([price_breakout, bb_contraction and bb_break])
                
                if core_condition and enhance_count >= 1:
                    # 入场
                    position = capital * position_size / row['close']
                    entry_price = row['close']
                    entry_date = df.index[i]
                    
                    reasons = [f"量能{row['vol_ratio']:.1f}x", f"RSI{row['rsi']:.0f}"]
                    if price_breakout:
                        reasons.append("突破10日高点")
                    if bb_contraction:
                        reasons.append(f"布林收缩{row['bb_width']:.1f}%")
                    
                    print(f"{entry_date.date()}: 🚀 买入 ${entry_price:.2f} ({', '.join(reasons)})")
            
            else:
                # 出场条件检查
                current_price = df['close'].iloc[i]
                pnl_pct = (current_price - entry_price) / entry_price
                
                # 止损（ATR 1.2x）
                atr = df['atr'].iloc[i]
                stop_loss_price = entry_price - atr * 1.2
                
                # 止盈（ATR 2.5x）
                take_profit_price = entry_price + atr * 2.5
                
                # RSI超买
                rsi_overbought = df['rsi'].iloc[i] > 65
                
                # 持有天数
                hold_days = (df.index[i] - entry_date).days
                
                exit_reason = None
                if current_price <= stop_loss_price:
                    exit_reason = "止损"
                elif current_price >= take_profit_price:
                    exit_reason = "止盈"
                elif rsi_overbought:
                    exit_reason = "RSI超买"
                elif hold_days >= 8:
                    exit_reason = "超时"
                
                if exit_reason:
                    # 出场
                    capital_change = position * current_price - position * entry_price
                    capital += capital_change
                    
                    trades.append({
                        'entry_date': entry_date,
                        'exit_date': df.index[i],
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'pnl_pct': pnl_pct * 100,
                        'hold_days': hold_days,
                        'reason': exit_reason
                    })
                    
                    print(f"{df.index[i].date()}: {'✅' if pnl_pct > 0 else '🛑'} {exit_reason} {pnl_pct*100:+.2f}% (持仓{hold_days}天)")
                    
                    position = 0
                    entry_price = 0
                    entry_date = None
        
        # 汇总结果
        print(f"\n{'='*60}")
        print("交易汇总")
        print(f"{'='*60}")
        
        if trades:
            total_pnl = sum(t['pnl_pct'] for t in trades)
            winning_trades = [t for t in trades if t['pnl_pct'] > 0]
            losing_trades = [t for t in trades if t['pnl_pct'] <= 0]
            
            print(f"总交易次数: {len(trades)}")
            print(f"盈利次数: {len(winning_trades)}")
            print(f"亏损次数: {len(losing_trades)}")
            print(f"胜率: {len(winning_trades)/len(trades)*100:.1f}%")
            
            avg_win = np.mean([t['pnl_pct'] for t in winning_trades]) if winning_trades else 0
            avg_loss = abs(np.mean([t['pnl_pct'] for t in losing_trades])) if losing_trades else 0
            print(f"平均盈利: {avg_win:+.2f}%")
            print(f"平均亏损: {avg_loss:+.2f}%")
            print(f"盈亏比: {avg_win/avg_loss:.2f}" if avg_loss > 0 else "盈亏比: N/A")
            
            print(f"\n初始资金: ${initial_capital:,.2f}")
            print(f"最终资金: ${capital:,.2f}")
            print(f"总收益: {(capital - initial_capital) / initial_capital * 100:+.2f}%")
            
            # 交易明细
            print(f"\n交易明细:")
            for i, t in enumerate(trades, 1):
                print(f"{i:2d}. {t['entry_date'].date()}→{t['exit_date'].date()} "
                      f"({t['hold_days']}天): ${t['entry_price']:.2f}→${t['exit_price']:.2f} "
                      f"{t['pnl_pct']:+.2f}% ({t['reason']})")
        else:
            print("无交易信号")
            
    except Exception as e:
        print(f"错误: {e}")
    finally:
        quote_ctx.close()


if __name__ == '__main__':
    print('\n' + '='*60)
    print('🇭🇰 港股策略1.9 - 李宁模拟交易')
    print('='*60)
    print('核心逻辑:')
    print('1. 成交量放大1.8x + RSI 40-60')
    print('2. 趋势向上 (MA20上升, 价格>MA20)')
    print('3. 至少1个增强信号 (突破高点 或 布林收缩突破)')
    print('4. 紧止损止盈 (ATR 1.2x/2.5x)')
    print('='*60)
    
    simulate_strategy_19()