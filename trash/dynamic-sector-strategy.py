#!/usr/bin/env python3
"""
港股策略 - 动态调整版（方案三）
根据近期表现动态调整行业权重
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

class DynamicHKStrategy:
    """动态调整港股策略"""
    
    def __init__(self):
        self.quote_ctx = None
        
        # 行业股票池
        self.sector_stocks = {
            "消费": [
                ('HK.02331', '李宁'),
                ('HK.02319', '蒙牛乳业'),
                ('HK.02020', '安踏体育'),
            ],
            "医药": [
                ('HK.02269', '药明生物'),
                ('HK.01093', '石药集团'),
            ],
            "新能源汽车": [
                ('HK.09868', '小鹏汽车-W'),
                ('HK.09866', '蔚来-SW'),
                ('HK.02333', '比亚迪股份'),
            ],
            "互联网科技": [
                ('HK.00700', '腾讯控股'),
                ('HK.09988', '阿里巴巴-SW'),
                ('HK.03690', '美团-W'),
            ],
            "金融": [
                ('HK.01299', '友邦保险'),
                ('HK.00388', '香港交易所'),
                ('HK.00939', '建设银行'),
            ],
        }
        
        # 行业权重（初始等权）
        self.sector_weights = {
            "消费": 1.0,
            "医药": 1.0,
            "新能源汽车": 1.0,
            "互联网科技": 1.0,
            "金融": 1.0,
        }
        
        # 行业历史表现
        self.sector_performance = {}
        
    def connect(self):
        """连接Futu"""
        self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        print("✅ 连接Futu成功")
        
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
    
    def backtest_sector_stocks(self, sector, stocks):
        """回测行业内的股票"""
        sector_trades = []
        
        for code, name in stocks:
            try:
                # 获取数据
                ret, data, _ = self.quote_ctx.request_history_kline(
                    code=code,
                    start='2025-11-01',
                    end='2026-03-20',
                    ktype=KLType.K_DAY,
                    autype=AuType.QFQ
                )
                
                if ret != 0 or data.empty or len(data) < 30:
                    continue
                
                df = pd.DataFrame({
                    'date': pd.to_datetime(data['time_key']),
                    'close': data['close'].astype(float),
                    'volume': data['volume'].astype(float),
                    'high': data['high'].astype(float),
                    'low': data['low'].astype(float),
                })
                df.set_index('date', inplace=True)
                
                # 计算指标
                df['ma20'] = df['close'].rolling(20).mean()
                df['vol_ma10'] = df['volume'].rolling(10).mean()
                df['vol_ratio'] = df['volume'] / df['vol_ma10']
                df['atr'] = self._calculate_atr(df)
                df['rsi'] = self._calculate_rsi(df['close'])
                df['bb_width'] = self._calculate_bb_width(df['close'])
                df['high_10'] = df['high'].rolling(10).max().shift(1)
                
                # 模拟交易
                position = 0
                entry_price = 0
                stop_price = 0
                target_price = 0
                
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
                            position = 1
                            entry_price = row['close']
                            atr = row['atr']
                            stop_price = entry_price - atr * 1.5
                            target_price = entry_price + atr * 3.0
                    
                    else:
                        current_price = df['close'].iloc[i]
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                        hold_days = i - 30
                        
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
                            sector_trades.append({
                                'stock': name,
                                'pnl_pct': pnl_pct,
                                'win': pnl_pct > 0
                            })
                            position = 0
                
            except Exception as e:
                continue
        
        # 计算行业表现
        if sector_trades:
            wins = len([t for t in sector_trades if t['win']])
            total = len(sector_trades)
            avg_pnl = np.mean([t['pnl_pct'] for t in sector_trades])
            
            return {
                'sector': sector,
                'trades': total,
                'wins': wins,
                'win_rate': wins / total * 100,
                'avg_pnl': avg_pnl,
                'total_pnl': sum([t['pnl_pct'] for t in sector_trades])
            }
        
        return None
    
    def _calculate_atr(self, df):
        """计算ATR"""
        tr = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        return tr.rolling(14).mean()
    
    def _calculate_rsi(self, close):
        """计算RSI"""
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_bb_width(self, close):
        """计算布林带宽度"""
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        return (2 * std / mid) * 100
    
    def update_sector_weights(self):
        """根据历史表现更新行业权重"""
        print(f"\n{'='*60}")
        print("📊 行业历史表现分析")
        print(f"{'='*60}")
        
        for sector, stocks in self.sector_stocks.items():
            performance = self.backtest_sector_stocks(sector, stocks)
            
            if performance:
                self.sector_performance[sector] = performance
                
                print(f"\n{sector}:")
                print(f"  交易次数: {performance['trades']}")
                print(f"  胜率: {performance['win_rate']:.1f}%")
                print(f"  平均收益: {performance['avg_pnl']:+.2f}%")
        
        # 计算权重
        if self.sector_performance:
            print(f"\n{'='*60}")
            print("🎯 动态调整行业权重")
            print(f"{'='*60}")
            
            # 根据平均收益调整权重
            max_pnl = max([p['avg_pnl'] for p in self.sector_performance.values()])
            min_pnl = min([p['avg_pnl'] for p in self.sector_performance.values()])
            
            for sector, perf in self.sector_performance.items():
                # 归一化收益
                if max_pnl != min_pnl:
                    normalized = (perf['avg_pnl'] - min_pnl) / (max_pnl - min_pnl)
                else:
                    normalized = 0.5
                
                # 权重范围：0.2 - 2.0
                self.sector_weights[sector] = 0.2 + normalized * 1.8
                
                print(f"{sector}: 权重={self.sector_weights[sector]:.2f} (收益{perf['avg_pnl']:+.2f}%)")
        
        # 显示推荐
        print(f"\n{'='*60}")
        print("💡 行业推荐")
        print(f"{'='*60}")
        
        sorted_sectors = sorted(
            self.sector_performance.items(),
            key=lambda x: x[1]['avg_pnl'],
            reverse=True
        )
        
        for i, (sector, perf) in enumerate(sorted_sectors, 1):
            weight = self.sector_weights[sector]
            
            if weight >= 1.5:
                recommendation = "⭐⭐⭐ 强烈推荐"
            elif weight >= 1.0:
                recommendation = "⭐⭐ 推荐"
            elif weight >= 0.5:
                recommendation = "⭐ 观察"
            else:
                recommendation = "❌ 不推荐"
            
            print(f"{i}. {sector:<10} {recommendation} (权重{weight:.2f})")
        
        return sorted_sectors
    
    def get_top_stocks(self, top_n=5):
        """获取推荐的股票"""
        print(f"\n{'='*60}")
        print(f"🚀 推荐股票（权重前{top_n}名）")
        print(f"{'='*60}")
        
        # 按权重排序行业
        sorted_sectors = sorted(
            self.sector_weights.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        recommended_stocks = []
        
        for sector, weight in sorted_sectors:
            if weight >= 0.5:  # 只推荐权重≥0.5的行业
                stocks = self.sector_stocks[sector]
                for code, name in stocks:
                    recommended_stocks.append({
                        'code': code,
                        'name': name,
                        'sector': sector,
                        'weight': weight
                    })
        
        # 按权重排序
        recommended_stocks.sort(key=lambda x: x['weight'], reverse=True)
        
        print(f"\n{'序号':<4} {'代码':<12} {'名称':<12} {'行业':<10} {'权重':<6}")
        print('-'*50)
        
        for i, stock in enumerate(recommended_stocks[:top_n*2], 1):
            print(f"{i:<4} {stock['code']:<12} {stock['name']:<12} {stock['sector']:<10} {stock['weight']:.2f}")
        
        return recommended_stocks[:top_n*2]


def main():
    """主函数"""
    print('\n' + '='*60)
    print('🇭🇰 港股动态调整策略（方案三）')
    print('='*60)
    print('核心逻辑:')
    print('1. 分析各行业近期表现')
    print('2. 动态调整行业权重')
    print('3. 推荐高权重行业的股票')
    print('='*60)
    
    strategy = DynamicHKStrategy()
    strategy.connect()
    
    try:
        # 更新行业权重
        sorted_sectors = strategy.update_sector_weights()
        
        # 获取推荐股票
        top_stocks = strategy.get_top_stocks(top_n=5)
        
        print(f"\n{'='*60}")
        print("✅ 动态调整完成")
        print(f"{'='*60}")
        print(f"推荐交易行业: {len([s for s in strategy.sector_weights.values() if s >= 1.0])}个")
        print(f"推荐交易股票: {len(top_stocks)}只")
        print(f"\n建议: 对推荐股票使用策略1.9.1进行交易")
        
    finally:
        strategy.close()


if __name__ == '__main__':
    main()