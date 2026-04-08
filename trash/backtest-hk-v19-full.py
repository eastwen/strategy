#!/usr/bin/env python3
"""
港股策略1.9 - 完整回测
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

def test_strategy_19_full():
    """策略1.9完整回测"""
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        # 测试股票（根据市场测试结果选择适合的）
        test_stocks = [
            ('HK.02331', '李宁'),         # 消费龙头（适合度67%）
            ('HK.02319', '蒙牛乳业'),     # 消费稳健（适合度67%）
            ('HK.02020', '安踏体育'),     # 消费成长（适合度67%）
            ('HK.01299', '友邦保险'),     # 金融稳健（适合度83%）
            ('HK.00388', '香港交易所'),   # 金融龙头（适合度83%）
            ('HK.00939', '建设银行'),     # 金融股（适合度83%）
            ('HK.00700', '腾讯控股'),     # 科技龙头（适合度67%）
            ('HK.03690', '美团-W'),       # 科技（适合度67%）
        ]
        
        all_results = []
        
        print('\n' + '='*60)
        print('🇭🇰 港股策略1.9 - 完整回测')
        print('='*60)
        print('策略核心:')
        print('1. 成交量放大 ≥ 1.8x')
        print('2. RSI 40-60')
        print('3. 趋势向上 (MA20上升, 价格>MA20)')
        print('4. 增强信号 (突破高点 或 布林收缩突破)')
        print('5. ATR动态止损止盈 (1.2x/2.5x)')
        print('仓位: 3%')
        print('='*60)
        
        for code, name in test_stocks:
            print(f"\n{'='*60}")
            print(f"📊 {name} ({code})")
            print(f"{'='*60}")
            
            # 获取数据
            end_date = '2026-03-20'
            start_date = '2025-11-01'
            
            ret, data, _ = quote_ctx.request_history_kline(
                code=code,
                start=start_date,
                end=end_date,
                ktype=KLType.K_DAY,
                autype=AuType.QFQ
            )
            
            if ret != 0 or data.empty or len(data) < 30:
                print("数据不足")
                continue
            
            df = pd.DataFrame({
                'date': pd.to_datetime(data['time_key']),
                'open': data['open'].astype(float),
                'high': data['high'].astype(float),
                'low': data['low'].astype(float),
                'close': data['close'].astype(float),
                'volume': data['volume'].astype(float)
            })
            df.set_index('date', inplace=True)
            
            print(f"数据: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}天)")
            print(f"价格变动: {(df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100:+.2f}%")
            
            # 计算技术指标
            df['ma5'] = df['close'].rolling(5).mean()
            df['ma10'] = df['close'].rolling(10).mean()
            df['ma20'] = df['close'].rolling(20).mean()
            df['vol_ma10'] = df['volume'].rolling(10).mean()
            df['vol_ratio'] = df['volume'] / df['vol_ma10']
            
            # ATR
            df['tr'] = np.maximum(
                df['high'] - df['low'],
                np.maximum(
                    abs(df['high'] - df['close'].shift(1)),
                    abs(df['low'] - df['close'].shift(1))
                )
            )
            df['atr'] = df['tr'].rolling(14).mean()
            
            # RSI
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
            df['bb_top'] = df['bb_mid'] + 2 * df['bb_std']
            df['bb_bot'] = df['bb_mid'] - 2 * df['bb_std']
            df['bb_width'] = (df['bb_top'] - df['bb_bot']) / df['bb_mid'] * 100
            
            # 价格高点
            df['high_10'] = df['high'].rolling(10).max().shift(1)
            
            # 模拟交易
            position = 0
            entry_price = 0
            entry_date = None
            stop_price = 0
            target_price = 0
            trades = []
            initial_capital = 1000000
            capital = initial_capital
            position_size = 0.03
            
            for i in range(30, len(df)-1):
                if position == 0:
                    # ===== 策略1.9入场条件 =====
                    row = df.iloc[i]
                    
                    # 条件1: 趋势向上（MA20上升）
                    ma20_up = row['ma20'] > df['ma20'].iloc[i-5] if i >= 35 else True
                    
                    # 条件2: 价格在MA20上方
                    price_above_ma20 = row['close'] > row['ma20']
                    
                    # 条件3: 成交量放大 ≥ 1.8x
                    vol_surge = row['vol_ratio'] >= 1.8
                    
                    # 条件4: RSI 40-60
                    rsi_ok = 40 <= row['rsi'] <= 60
                    
                    # 增强信号
                    price_breakout = row['close'] >= row['high_10']
                    bb_contraction = row['bb_width'] < 12
                    bb_break = row['close'] > row['bb_mid']
                    
                    # 核心条件
                    core_condition = vol_surge and rsi_ok and ma20_up and price_above_ma20
                    
                    # 增强条件计数
                    enhance_count = sum([price_breakout, bb_contraction and bb_break])
                    
                    if core_condition and enhance_count >= 1:
                        position = capital * position_size / row['close']
                        entry_price = row['close']
                        entry_date = df.index[i]
                        atr = row['atr']
                        stop_price = entry_price - atr * 1.2
                        target_price = entry_price + atr * 2.5
                        
                        reasons = [f"量能{row['vol_ratio']:.1f}x", f"RSI{row['rsi']:.0f}"]
                        if price_breakout:
                            reasons.append("突破10日高点")
                        if bb_contraction:
                            reasons.append(f"布林收缩{row['bb_width']:.0f}%")
                        
                        print(f"  {entry_date.date()}: 🚀 买入 ${entry_price:.2f} ({', '.join(reasons)})")
                
                else:
                    # ===== 策略1.9出场条件 =====
                    current_price = df['close'].iloc[i]
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    hold_days = (df.index[i] - entry_date).days
                    atr = df['atr'].iloc[i]
                    
                    exit_reason = None
                    
                    # 1. ATR止损
                    if current_price <= stop_price:
                        exit_reason = "ATR止损"
                    
                    # 2. ATR止盈
                    elif current_price >= target_price:
                        exit_reason = "ATR止盈"
                    
                    # 3. RSI超买 (>65)
                    elif df['rsi'].iloc[i] > 65:
                        exit_reason = "RSI超买"
                    
                    # 4. 最大持仓8天
                    elif hold_days >= 8:
                        exit_reason = "超时离场"
                    
                    if exit_reason:
                        capital_change = position * current_price - position * entry_price
                        capital += capital_change
                        
                        trades.append({
                            'entry_date': entry_date,
                            'exit_date': df.index[i],
                            'entry_price': entry_price,
                            'exit_price': current_price,
                            'pnl_pct': pnl_pct,
                            'hold_days': hold_days,
                            'reason': exit_reason
                        })
                        
                        emoji = '✅' if pnl_pct > 0 else '🛑'
                        print(f"  {df.index[i].date()}: {emoji} {exit_reason} {pnl_pct:+.2f}% (持仓{hold_days}天)")
                        
                        position = 0
                        entry_price = 0
                        entry_date = None
            
            # 汇总单只股票
            if trades:
                winning_trades = [t for t in trades if t['pnl_pct'] > 0]
                losing_trades = [t for t in trades if t['pnl_pct'] <= 0]
                
                strategy_return = (capital - initial_capital) / initial_capital * 100
                buy_hold_return = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
                
                print(f"\n  📊 统计: 交易{len(trades)}次 | 胜率{len(winning_trades)/len(trades)*100:.0f}% | "
                      f"策略{strategy_return:+.2f}% | 持有{buy_hold_return:+.2f}%")
                
                all_results.append({
                    'name': name,
                    'code': code,
                    'trades': len(trades),
                    'won': len(winning_trades),
                    'lost': len(losing_trades),
                    'win_rate': len(winning_trades)/len(trades)*100 if trades else 0,
                    'strategy_return': strategy_return,
                    'buy_hold_return': buy_hold_return,
                    'avg_win': np.mean([t['pnl_pct'] for t in winning_trades]) if winning_trades else 0,
                    'avg_loss': abs(np.mean([t['pnl_pct'] for t in losing_trades])) if losing_trades else 0,
                })
            else:
                print(f"  无交易信号")
                all_results.append({
                    'name': name,
                    'code': code,
                    'trades': 0,
                    'won': 0,
                    'lost': 0,
                    'win_rate': 0,
                    'strategy_return': 0,
                    'buy_hold_return': (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100,
                    'avg_win': 0,
                    'avg_loss': 0,
                })
        
        # 总体汇总
        if all_results:
            print(f"\n{'='*60}")
            print("📊 策略1.9总体回测结果")
            print(f"{'='*60}")
            print(f"\n{'标的':<12} {'交易':<5} {'胜率':<7} {'策略收益':<9} {'买入持有':<9} {'Alpha':<8}")
            print('-'*55)
            
            total_trades = sum(r['trades'] for r in all_results)
            total_won = sum(r['won'] for r in all_results)
            total_lost = sum(r['lost'] for r in all_results)
            
            for r in all_results:
                alpha = r['strategy_return'] - r['buy_hold_return']
                alpha_str = f"{alpha:+.2f}%" if r['trades'] > 0 else "N/A"
                win_rate_str = f"{r['win_rate']:.0f}%" if r['trades'] > 0 else "N/A"
                
                print(f"{r['name']:<12} {r['trades']:<5} {win_rate_str:<7} {r['strategy_return']:<+8.2f}% {r['buy_hold_return']:<+8.2f}% {alpha_str:<8}")
            
            # 计算总体指标
            valid_results = [r for r in all_results if r['trades'] > 0]
            
            if valid_results:
                overall_win_rate = total_won / total_trades * 100 if total_trades > 0 else 0
                avg_strategy_return = np.mean([r['strategy_return'] for r in valid_results])
                avg_buy_hold = np.mean([r['buy_hold_return'] for r in valid_results])
                avg_win = np.mean([r['avg_win'] for r in valid_results if r['avg_win'] > 0])
                avg_loss = np.mean([r['avg_loss'] for r in valid_results if r['avg_loss'] > 0])
                profit_ratio = avg_win / avg_loss if avg_loss > 0 else 0
                
                print(f"\n📈 总体表现:")
                print(f"  总交易: {total_trades}次")
                print(f"  总胜率: {overall_win_rate:.1f}% ({total_won}胜/{total_lost}负)")
                print(f"  平均收益: {avg_strategy_return:+.2f}%")
                print(f"  平均盈亏比: {profit_ratio:.2f}")
                print(f"  平均Alpha: {avg_strategy_return - avg_buy_hold:+.2f}%")
                
                # 策略评价
                if avg_strategy_return > 0 and overall_win_rate >= 50:
                    print(f"\n🎯 策略评价: ✅ 有效 (正收益 + 胜率≥50%)")
                elif avg_strategy_return > 0:
                    print(f"\n🎯 策略评价: ⚠️ 可接受 (正收益但胜率待提升)")
                else:
                    print(f"\n🎯 策略评价: ❌ 需改进")
            
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        quote_ctx.close()


if __name__ == '__main__':
    test_strategy_19_full()