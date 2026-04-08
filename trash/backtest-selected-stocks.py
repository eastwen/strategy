#!/usr/bin/env python3
"""
港股策略回测 - 基于动态筛选的20只股票
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

# 动态筛选出的20只股票
SELECTED_STOCKS = [
    ('HK.09868', '小鹏汽车-W', 77.5),
    ('HK.02331', '李宁', 77.5),
    ('HK.01398', '工商银行', 75.8),
    ('HK.09988', '阿里巴巴-SW', 72.2),
    ('HK.03690', '美团-W', 72.2),
    ('HK.09999', '网易-S', 72.2),
    ('HK.09618', '京东集团-SW', 72.2),
    ('HK.02382', '舜宇光学科技', 72.2),
    ('HK.02018', '瑞声科技', 72.2),
    ('HK.01347', '华虹半导体', 72.2),
    ('HK.02333', '比亚迪股份', 72.2),
    ('HK.09618', '京东健康', 72.2),
    ('HK.00939', '建设银行', 72.2),
    ('HK.02319', '蒙牛乳业', 72.2),
    ('HK.09866', '蔚来-SW', 67.0),
    ('HK.01093', '石药集团', 67.0),
    ('HK.00700', '腾讯控股', 65.2),
    ('HK.09888', '百度集团-SW', 65.2),
    ('HK.01299', '友邦保险', 65.2),
    ('HK.00388', '香港交易所', 65.2),
]

def backtest_stock(quote_ctx, code, name, score):
    """回测单只股票"""
    try:
        # 获取数据
        ret, data, _ = quote_ctx.request_history_kline(
            code=code,
            start='2025-11-01',
            end='2026-03-20',
            ktype=KLType.K_DAY,
            autype=AuType.QFQ
        )
        
        if ret != 0 or data.empty or len(data) < 30:
            return None
        
        df = pd.DataFrame({
            'date': pd.to_datetime(data['time_key']),
            'open': data['open'].astype(float),
            'high': data['high'].astype(float),
            'low': data['low'].astype(float),
            'close': data['close'].astype(float),
            'volume': data['volume'].astype(float)
        })
        df.set_index('date', inplace=True)
        
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
        
        # 布林带宽度
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_width'] = (2 * df['bb_std'] / df['bb_mid']) * 100
        
        # 价格高点
        df['high_10'] = df['high'].rolling(10).max().shift(1)
        
        # 模拟交易（策略1.9.1）
        position = 0
        entry_price = 0
        stop_price = 0
        target_price = 0
        trades = []
        capital = 1000000
        
        for i in range(30, len(df)-1):
            if position == 0:
                row = df.iloc[i]
                
                # 入场条件
                ma20_up = row['ma20'] > df['ma20'].iloc[i-5] if i >= 35 else True
                price_above_ma20 = row['close'] > row['ma20']
                vol_surge = row['vol_ratio'] >= 1.5
                rsi_ok = 35 <= row['rsi'] <= 70
                
                price_breakout = row['close'] >= row['high_10']
                bb_contraction = row['bb_width'] < 12
                
                core_condition = vol_surge and rsi_ok and ma20_up and price_above_ma20
                enhance_count = sum([price_breakout, bb_contraction])
                
                if core_condition and enhance_count >= 1:
                    position = capital * 0.03 / row['close']
                    entry_price = row['close']
                    atr = row['atr']
                    stop_price = entry_price - atr * 1.5
                    target_price = entry_price + atr * 3.0
            
            else:
                current_price = df['close'].iloc[i]
                pnl_pct = (current_price - entry_price) / entry_price * 100
                hold_days = (df.index[i] - df.index[i-1]).days
                
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
                        'pnl_pct': pnl_pct,
                        'hold_days': hold_days
                    })
                    position = 0
        
        # 统计
        if trades:
            won = len([t for t in trades if t['pnl_pct'] > 0])
            lost = len([t for t in trades if t['pnl_pct'] <= 0])
            total_pnl = sum(t['pnl_pct'] for t in trades)
            avg_pnl = total_pnl / len(trades)
            
            return {
                'code': code,
                'name': name,
                'score': score,
                'trades': len(trades),
                'won': won,
                'lost': lost,
                'win_rate': won / len(trades) * 100,
                'avg_pnl': avg_pnl,
                'total_pnl': total_pnl
            }
        else:
            return {
                'code': code,
                'name': name,
                'score': score,
                'trades': 0,
                'won': 0,
                'lost': 0,
                'win_rate': 0,
                'avg_pnl': 0,
                'total_pnl': 0
            }
    
    except Exception as e:
        print(f"  ❌ {name} 回测失败: {e}")
        return None


def main():
    """主函数"""
    print('\n' + '='*60)
    print('🇭🇰 港股策略回测 - 动态筛选的20只股票')
    print('='*60)
    print(f'策略: 1.9.1调整版')
    print(f'股票: {len(SELECTED_STOCKS)}只')
    print('='*60)
    
    quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
    
    try:
        results = []
        
        for code, name, score in SELECTED_STOCKS:
            print(f"\n回测 {name}...", end=' ')
            result = backtest_stock(quote_ctx, code, name, score)
            
            if result:
                results.append(result)
                
                if result['trades'] > 0:
                    wr = result['win_rate']
                    ap = result['avg_pnl']
                    print(f"✅ 交易{result['trades']}次 | 胜率{wr:.0f}% | 平均{ap:+.2f}%")
                else:
                    print("无交易")
        
        # 汇总
        if results:
            print(f"\n{'='*60}")
            print('📊 回测汇总')
            print(f"{'='*60}")
            print(f"\n{'股票':<12} {'评分':<6} {'交易':<5} {'胜率':<7} {'平均收益':<10}")
            print('-'*45)
            
            total_trades = 0
            total_won = 0
            total_pnl = 0
            trade_count = 0
            
            for r in sorted(results, key=lambda x: x['avg_pnl'], reverse=True):
                if r['trades'] > 0:
                    wr = f"{r['win_rate']:.0f}%"
                    print(f"{r['name']:<12} {r['score']:<6.1f} {r['trades']:<5} {wr:<7} {r['avg_pnl']:<+9.2f}%")
                    
                    total_trades += r['trades']
                    total_won += r['won']
                    total_pnl += r['avg_pnl']
                    trade_count += 1
            
            # 总体统计
            if trade_count > 0:
                overall_win_rate = total_won / total_trades * 100 if total_trades > 0 else 0
                avg_return = total_pnl / trade_count
                
                print(f"\n{'='*60}")
                print(f"📈 总体表现")
                print(f"{'='*60}")
                print(f"  有交易的股票: {trade_count}只")
                print(f"  总交易次数: {total_trades}次")
                print(f"  总胜率: {overall_win_rate:.1f}%")
                print(f"  平均收益: {avg_return:+.2f}%")
                
                # 评价
                if avg_return > 0 and overall_win_rate >= 50:
                    print(f"\n🎯 策略评价: ✅ 有效")
                elif avg_return > 0:
                    print(f"\n🎯 策略评价: ⚠️ 可接受")
                else:
                    print(f"\n🎯 策略评价: ❌ 需改进")
            
    finally:
        quote_ctx.close()


if __name__ == '__main__':
    main()