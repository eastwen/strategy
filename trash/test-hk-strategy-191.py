#!/usr/bin/env python3
"""
港股策略 1.9.1 - 调整优化版
调整点：降低门槛，提高信号数量
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

def test_strategy_191():
    """策略1.9.1测试"""
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        test_stocks = [
            ('HK.02331', '李宁'),
            ('HK.02319', '蒙牛乳业'),
            ('HK.02020', '安踏体育'),
            ('HK.01299', '友邦保险'),
            ('HK.00388', '香港交易所'),
            ('HK.00939', '建设银行'),
            ('HK.00700', '腾讯控股'),
            ('HK.03690', '美团-W'),
        ]
        
        all_results = []
        
        print('\n' + '='*60)
        print('🇭🇰 港股策略 1.9.1 - 调整优化版')
        print('='*60)
        print('调整点：')
        print('1. 成交量要求：1.8x → 1.5x ✅')
        print('2. RSI范围：40-60 → 35-70 ✅')
        print('3. 增强信号：≥1个即可 ✅')
        print('4. 其他条件保持不变')
        print('='*60)
        
        for code, name in test_stocks:
            print(f"\n{'='*60}")
            print(f"📊 {name} ({code})")
            print(f"{'='*60}")
            
            # 获取数据
            ret, data, _ = quote_ctx.request_history_kline(
                code=code,
                start='2025-11-01',
                end='2026-03-20',
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
            
            print(f"数据: {len(df)}天 | 价格变动: {(df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100:+.2f}%")
            
            # 计算技术指标
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
            df['bb_width'] = (2 * df['bb_std'] / df['bb_mid']) * 100
            
            # 价格高点
            df['high_10'] = df['high'].rolling(10).max().shift(1)
            
            # 模拟交易
            position = 0
            entry_price = 0
            entry_date = None
            stop_price = 0
            target_price = 0
            trades = []
            capital = 1000000
            
            for i in range(30, len(df)-1):
                if position == 0:
                    row = df.iloc[i]
                    
                    # ===== 策略1.9.1入场条件（调整版） =====
                    # 条件1: 趋势向上
                    ma20_up = row['ma20'] > df['ma20'].iloc[i-5] if i >= 35 else True
                    price_above_ma20 = row['close'] > row['ma20']
                    
                    # 条件2: 成交量放大 ≥ 1.5x（从1.8x降低）
                    vol_surge = row['vol_ratio'] >= 1.5
                    
                    # 条件3: RSI 35-70（从40-60放宽）
                    rsi_ok = 35 <= row['rsi'] <= 70
                    
                    # 增强信号
                    price_breakout = row['close'] >= row['high_10']
                    bb_contraction = row['bb_width'] < 12
                    
                    # 入场：核心条件 + 至少1个增强信号
                    core_condition = vol_surge and rsi_ok and ma20_up and price_above_ma20
                    enhance_count = sum([price_breakout, bb_contraction])
                    
                    if core_condition and enhance_count >= 1:
                        position = capital * 0.03 / row['close']
                        entry_price = row['close']
                        entry_date = df.index[i]
                        atr = row['atr']
                        stop_price = entry_price - atr * 1.5  # 放宽止损
                        target_price = entry_price + atr * 3.0
                        
                        reasons = [f"量能{row['vol_ratio']:.1f}x", f"RSI{row['rsi']:.0f}"]
                        if price_breakout:
                            reasons.append("突破")
                        if bb_contraction:
                            reasons.append(f"布林{row['bb_width']:.0f}%")
                        
                        print(f"  {entry_date.date()}: 🚀 ${entry_price:.2f} ({', '.join(reasons)})")
                
                else:
                    current_price = df['close'].iloc[i]
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    hold_days = (df.index[i] - entry_date).days
                    
                    exit_reason = None
                    
                    if current_price <= stop_price:
                        exit_reason = "止损"
                    elif current_price >= target_price:
                        exit_reason = "止盈"
                    elif df['rsi'].iloc[i] > 70:
                        exit_reason = "RSI超买"
                    elif hold_days >= 10:
                        exit_reason = "超时"
                    
                    if exit_reason:
                        trades.append({
                            'entry_date': entry_date,
                            'exit_date': df.index[i],
                            'pnl_pct': pnl_pct,
                            'hold_days': hold_days,
                            'reason': exit_reason
                        })
                        
                        emoji = '✅' if pnl_pct > 0 else '🛑'
                        print(f"  {df.index[i].date()}: {emoji} {exit_reason} {pnl_pct:+.2f}% ({hold_days}天)")
                        
                        position = 0
            
            # 统计
            if trades:
                won = len([t for t in trades if t['pnl_pct'] > 0])
                lost = len([t for t in trades if t['pnl_pct'] <= 0])
                total_pnl = sum(t['pnl_pct'] for t in trades)
                avg_pnl = total_pnl / len(trades)
                
                print(f"\n  📊 交易{len(trades)}次 | 胜率{won/len(trades)*100:.0f}% | 平均{avg_pnl:+.2f}%")
                
                all_results.append({
                    'name': name,
                    'trades': len(trades),
                    'won': won,
                    'lost': lost,
                    'win_rate': won/len(trades)*100,
                    'avg_pnl': avg_pnl,
                })
            else:
                print(f"  无交易")
                all_results.append({
                    'name': name,
                    'trades': 0,
                    'won': 0,
                    'lost': 0,
                    'win_rate': 0,
                    'avg_pnl': 0,
                })
        
        # 总体汇总
        if all_results:
            print(f"\n{'='*60}")
            print("📊 策略 1.9.1 总体结果")
            print(f"{'='*60}")
            print(f"\n{'标的':<12} {'交易':<5} {'胜率':<7} {'平均收益':<10}")
            print('-'*40)
            
            total_trades = sum(r['trades'] for r in all_results)
            total_won = sum(r['won'] for r in all_results)
            
            for r in all_results:
                wr = f"{r['win_rate']:.0f}%" if r['trades'] > 0 else "N/A"
                print(f"{r['name']:<12} {r['trades']:<5} {wr:<7} {r['avg_pnl']:<+9.2f}%")
            
            if total_trades > 0:
                overall_wr = total_won / total_trades * 100
                avg_pnl_all = np.mean([r['avg_pnl'] for r in all_results if r['trades'] > 0])
                
                print(f"\n📈 总交易: {total_trades}次")
                print(f"📈 总胜率: {overall_wr:.1f}%")
                print(f"📈 平均收益: {avg_pnl_all:+.2f}%")
                
                if avg_pnl_all > 0 and overall_wr >= 50:
                    print(f"\n🎯 评价: ✅ 有效")
                elif avg_pnl_all > 0:
                    print(f"\n🎯 评价: ⚠️ 可接受")
                else:
                    print(f"\n🎯 评价: ❌ 需改进")
            
    except Exception as e:
        print(f"错误: {e}")
    finally:
        quote_ctx.close()


if __name__ == '__main__':
    test_strategy_191()