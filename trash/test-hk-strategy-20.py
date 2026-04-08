#!/usr/bin/env python3
"""
港股策略2.0 - 最终版测试
核心理念：趋势第一，简单有效
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

def test_strategy_20():
    """测试策略2.0"""
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        # 测试多只股票
        test_stocks = [
            ('HK.02331', '李宁'),      # 消费龙头
            ('HK.02319', '蒙牛乳业'),  # 消费稳健
            ('HK.02020', '安踏体育'),  # 消费成长
            ('HK.00388', '香港交易所'), # 金融龙头
            ('HK.00700', '腾讯控股'),  # 科技龙头
        ]
        
        all_results = []
        
        for code, name in test_stocks:
            print(f"\n{'='*60}")
            print(f"📊 {name} ({code}) 策略2.0测试")
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
            
            if ret != 0 or data.empty:
                print("数据获取失败")
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
            
            print(f"数据范围: {df.index[0].date()} ~ {df.index[-1].date()}")
            print(f"数据条数: {len(df)}")
            print(f"价格变动: {(df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100:+.2f}%")
            
            # 计算技术指标
            df['ma20'] = df['close'].rolling(20).mean()
            df['vol_ma10'] = df['volume'].rolling(10).mean()
            df['vol_ratio'] = df['volume'] / df['vol_ma10']
            
            # 计算RSI
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
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
            position_size = 0.03  # 3%仓位
            
            for i in range(30, len(df)-1):
                if position == 0:
                    # ===== 策略2.0入场条件 =====
                    row = df.iloc[i]
                    
                    # 条件1: 价格突破10日高点
                    price_breakout = row['close'] >= row['high_10']
                    
                    # 条件2: 成交量放大 ≥ 1.5x
                    vol_surge = row['vol_ratio'] >= 1.5
                    
                    # 条件3: RSI 30-70
                    rsi_ok = 30 <= row['rsi'] <= 70
                    
                    # 条件4: 价格在MA20上方
                    price_above_ma20 = row['close'] > row['ma20']
                    
                    # 入场条件：全部满足
                    if price_breakout and vol_surge and rsi_ok and price_above_ma20:
                        position = capital * position_size / row['close']
                        entry_price = row['close']
                        entry_date = df.index[i]
                        stop_price = entry_price * 0.98  # 2%止损
                        target_price = entry_price * 1.05  # 5%止盈
                        
                        reasons = [
                            f"突破高点",
                            f"量能{row['vol_ratio']:.1f}x",
                            f"RSI{row['rsi']:.0f}",
                            f"价格>MA20"
                        ]
                        
                        print(f"{entry_date.date()}: 🚀 买入 ${entry_price:.2f} ({', '.join(reasons)})")
                
                else:
                    # ===== 策略2.0出场条件 =====
                    current_price = df['close'].iloc[i]
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    hold_days = (df.index[i] - entry_date).days
                    
                    # 移动止损：盈利3%后保本
                    if pnl_pct > 3:
                        stop_price = max(stop_price, entry_price)  # 保本
                    
                    exit_reason = None
                    
                    # 1. 止损
                    if current_price <= stop_price:
                        exit_reason = f"止损({stop_price/entry_price*100-100:.1f}%)"
                    
                    # 2. 止盈
                    elif current_price >= target_price:
                        exit_reason = f"止盈(+5%)"
                    
                    # 3. RSI超买
                    elif df['rsi'].iloc[i] > 70:
                        exit_reason = "RSI超买"
                    
                    # 4. 最大持仓天数
                    elif hold_days >= 10:
                        exit_reason = "超时(10天)"
                    
                    if exit_reason:
                        # 出场
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
                        
                        print(f"{df.index[i].date()}: {'✅' if pnl_pct > 0 else '🛑'} {exit_reason} {pnl_pct:+.2f}% (持仓{hold_days}天)")
                        
                        position = 0
                        entry_price = 0
                        entry_date = None
            
            # 汇总单只股票结果
            if trades:
                total_pnl = sum(t['pnl_pct'] for t in trades)
                winning_trades = [t for t in trades if t['pnl_pct'] > 0]
                losing_trades = [t for t in trades if t['pnl_pct'] <= 0]
                
                print(f"\n📊 {name} 交易统计:")
                print(f"  总交易: {len(trades)}")
                print(f"  盈利: {len(winning_trades)}次")
                print(f"  亏损: {len(losing_trades)}次")
                print(f"  胜率: {len(winning_trades)/len(trades)*100:.1f}%")
                
                avg_win = np.mean([t['pnl_pct'] for t in winning_trades]) if winning_trades else 0
                avg_loss = abs(np.mean([t['pnl_pct'] for t in losing_trades])) if losing_trades else 0
                print(f"  平均盈利: {avg_win:+.2f}%")
                print(f"  平均亏损: {avg_loss:+.2f}%")
                
                capital_pct_change = (capital - initial_capital) / initial_capital * 100
                print(f"  策略收益: {capital_pct_change:+.2f}%")
                print(f"  买入持有收益: {(df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100:+.2f}%")
                
                all_results.append({
                    'name': name,
                    'code': code,
                    'trades': len(trades),
                    'win_rate': len(winning_trades)/len(trades)*100 if trades else 0,
                    'strategy_return': capital_pct_change,
                    'buy_hold_return': (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
                })
            else:
                print(f"无交易信号")
                all_results.append({
                    'name': name,
                    'code': code,
                    'trades': 0,
                    'win_rate': 0,
                    'strategy_return': 0,
                    'buy_hold_return': (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
                })
        
        # 总体汇总
        if all_results:
            print(f"\n{'='*60}")
            print("📊 策略2.0总体测试结果")
            print(f"{'='*60}")
            print(f"\n{'标的':<12} {'交易':<6} {'胜率':<8} {'策略收益':<10} {'买入持有':<10} {'Alpha':<8}")
            print('-'*60)
            
            total_trades = sum(r['trades'] for r in all_results)
            avg_win_rate = np.mean([r['win_rate'] for r in all_results if r['trades'] > 0])
            avg_strategy_return = np.mean([r['strategy_return'] for r in all_results])
            avg_buy_hold = np.mean([r['buy_hold_return'] for r in all_results])
            
            for r in all_results:
                alpha = r['strategy_return'] - r['buy_hold_return']
                alpha_display = f"{alpha:+.2f}%" if r['trades'] > 0 else "N/A"
                print(f"{r['name']:<12} {r['trades']:<6} {r['win_rate']:<7.1f}% {r['strategy_return']:<+9.2f}% {r['buy_hold_return']:<+9.2f}% {alpha_display:<8}")
            
            print(f"\n📈 总体统计:")
            print(f"  总交易次数: {total_trades}")
            print(f"  平均胜率: {avg_win_rate:.1f}%")
            print(f"  平均策略收益: {avg_strategy_return:+.2f}%")
            print(f"  平均买入持有收益: {avg_buy_hold:+.2f}%")
            print(f"  平均Alpha: {avg_strategy_return - avg_buy_hold:+.2f}%")
            
            # 策略评价
            if avg_strategy_return > 0 and avg_win_rate > 50:
                print(f"\n🎯 策略评价: ✅ 有效 (正收益+高胜率)")
            elif avg_strategy_return > 0:
                print(f"\n🎯 策略评价: ⚠️ 可接受 (正收益但胜率待提升)")
            else:
                print(f"\n🎯 策略评价: ❌ 需改进")
            
    except Exception as e:
        print(f"错误: {e}")
    finally:
        quote_ctx.close()


if __name__ == '__main__':
    print('\n' + '='*60)
    print('🇭🇰 港股策略2.0 - 最终版测试')
    print('='*60)
    print('核心理念: 趋势第一，简单有效')
    print('入场条件:')
    print('1. 价格突破10日高点')
    print('2. 成交量放大 ≥ 1.5x')
    print('3. RSI 30-70')
    print('4. 价格在MA20上方')
    print('出场条件:')
    print('1. 止损: -2%')
    print('2. 止盈: +5%')
    print('3. 移动止损: 盈利3%后保本')
    print('4. 最大持仓: 10天')
    print('仓位: 3%')
    print('='*60)
    
    test_strategy_20()