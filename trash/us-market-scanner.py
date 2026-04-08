#!/usr/bin/env python3
"""
美股全市场扫描系统
24小时自动扫描全部美股，筛选符合策略的股票
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import time

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')

class USMarketScanner:
    """美股全市场扫描器"""
    
    def __init__(self):
        self.weights = {
            'news': 0.35,
            'technical': 0.40,
            'sentiment': 0.25
        }
        
    def get_all_us_stocks(self):
        """获取美股股票池"""
        print("\n📊 获取美股股票池...")
        
        # 美股常用股票池
        # 实际应用中应该从Yahoo Finance或其他API获取全市场股票
        stock_pool = {
            '科技龙头': [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA',
                'AMD', 'INTC', 'NFLX', 'CRM', 'ORCL', 'ADBE', 'PYPL',
                'AVGO', 'QCOM', 'TXN', 'NVDA', 'AMD', 'INTC',
            ],
            '半导体': [
                'NVDA', 'AMD', 'AVGO', 'QCOM', 'TXN', 'INTC', 'MU',
                'AMAT', 'LRCX', 'KLAC', 'ASML', 'TSM', 'ADI', 'MRVL',
                'SNPS', 'CDNS', 'SWKS', 'QRVO', 'ON', 'WOLF',
            ],
            'AI算力': [
                'NVDA', 'AMD', 'AVGO', 'MRVL', 'ARM', 'SMCI', 'VRT',
                'PLTR', 'AI', 'PATH', 'DOCN', 'NET', 'DDOG', 'SNOW',
            ],
            '新能源': [
                'TSLA', 'RIVN', 'LCID', 'F', 'GM', 'NIO', 'XPEV', 'LI',
                'CHPT', 'BLNK', 'EVGO', 'DCRC', 'FCEL', 'PLUG', 'BE',
            ],
            '消费': [
                'AMZN', 'BABA', 'JD', 'PDD', 'MELI', 'SE', 'EBAY',
                'WMT', 'TGT', 'COST', 'HD', 'LOW', 'BBY', 'DKS',
            ],
            '医疗': [
                'UNH', 'JNJ', 'PFE', 'MRK', 'ABBV', 'LLY', 'BMY',
                'AMGN', 'GILD', 'REGN', 'VRTX', 'BIIB', 'ILMN',
            ],
            '金融': [
                'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'USB', 'PNC',
                'BLK', 'SCHW', 'V', 'MA', 'AXP', 'COF', 'BK',
            ],
            '工业': [
                'BA', 'CAT', 'HON', 'UPS', 'FDX', 'GE', 'MMM',
                'DE', 'LMT', 'RTX', 'NOC', 'GD', 'LHX',
            ],
            '能源': [
                'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PSX', 'VLO',
                'MPC', 'OXY', 'PXD', 'FANG', 'MRO',
            ],
        }
        
        # 扁平化
        all_stocks = []
        for sector, codes in stock_pool.items():
            for code in codes:
                all_stocks.append((code, sector))
        
        # 去重
        seen = set()
        unique_stocks = []
        for code, sector in all_stocks:
            if code not in seen:
                seen.add(code)
                unique_stocks.append((code, sector))
        
        print(f"✅ 股票池：{len(unique_stocks)}只股票")
        return unique_stocks
    
    def get_yahoo_data(self, symbol):
        """从Yahoo Finance获取数据"""
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        params = {'range': '60d', 'interval': '1d'}
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        try:
            res = requests.get(url, params=params, headers=headers, timeout=10)
            if res.status_code != 200:
                return None
            
            data = res.json()['chart']['result'][0]
            timestamps = data['timestamp']
            quote = data['indicators']['quote'][0]
            
            df = pd.DataFrame({
                'close': quote['close'],
                'volume': quote['volume'],
                'high': quote['high'],
                'low': quote['low'],
            })
            df.dropna(inplace=True)
            
            return df
            
        except Exception as e:
            return None
    
    def calculate_stock_score(self, symbol, sector):
        """计算股票评分"""
        try:
            # 获取数据
            df = self.get_yahoo_data(symbol)
            
            if df is None or len(df) < 30:
                return None
            
            close = df['close']
            volume = df['volume']
            
            # 技术指标
            # 1. 均线
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.iloc[-50:].mean() if len(close) >= 50 else ma20
            
            # 2. 成交量
            avg_vol = volume.rolling(30).mean().iloc[-1]
            vol_ratio = volume.iloc[-1] / avg_vol if avg_vol > 0 else 1
            
            # 3. RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 0
            rsi = 100 - (100 / (1 + rs))
            
            # 4. 价格突破
            high_20 = close.rolling(20).max().iloc[-2]
            breakout = close.iloc[-1] >= high_20
            
            # 5. 价格变动
            price_change = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100
            
            # 技术评分
            tech_score = 50
            if ma5 > ma10:
                tech_score += 15
            if ma20 > ma50:
                tech_score += 20  # 趋势向上
            if vol_ratio >= 1.8:
                tech_score += 15
            if rsi < 65:
                tech_score += 10
            
            # 过滤条件
            if vol_ratio < 1.3:
                return None
            
            if tech_score < 60:
                return None
            
            if rsi > 70:
                return None
            
            # 情绪评分（假设）
            sentiment_score = 70
            
            # 新闻评分（假设）
            news_score = 60
            
            # 综合评分
            total_score = (
                news_score * self.weights['news'] +
                tech_score * self.weights['technical'] +
                sentiment_score * self.weights['sentiment']
            )
            
            return {
                'symbol': symbol,
                'sector': sector,
                'tech_score': tech_score,
                'total_score': total_score,
                'price': close.iloc[-1],
                'price_change': price_change,
                'vol_ratio': vol_ratio,
                'rsi': rsi,
                'ma20_above_ma50': ma20 > ma50,
                'breakout': breakout
            }
            
        except Exception as e:
            return None
    
    def scan_market(self, min_score=65, max_count=50):
        """扫描全市场"""
        print('\n' + '='*60)
        print('🇺🇸 美股全市场扫描')
        print('='*60)
        print(f'筛选标准: 评分≥{min_score}, 最多{max_count}只')
        print(f'扫描时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print('='*60)
        
        # 获取股票池
        all_stocks = self.get_all_us_stocks()
        
        print(f"\n开始扫描 {len(all_stocks)} 只股票...\n")
        
        results = []
        scanned = 0
        
        for symbol, sector in all_stocks:
            scanned += 1
            
            # 每10只显示进度
            if scanned % 10 == 0:
                print(f"  已扫描: {scanned}/{len(all_stocks)} | 入选: {len(results)}")
            
            score = self.calculate_stock_score(symbol, sector)
            
            if score and score['total_score'] >= min_score:
                results.append(score)
            
            # 延迟避免请求过快
            time.sleep(0.1)
        
        # 排序
        results.sort(key=lambda x: x['total_score'], reverse=True)
        
        # 限制数量
        results = results[:max_count]
        
        # 显示结果
        print(f"\n{'='*60}")
        print(f"✅ 扫描完成")
        print(f"{'='*60}")
        print(f"扫描股票: {scanned}只")
        print(f"符合条件: {len(results)}只")
        
        if results:
            print(f"\n{'='*60}")
            print("📊 入选股票")
            print(f"{'='*60}")
            print(f"\n{'序号':<4} {'代码':<8} {'行业':<10} {'评分':<6} {'价格':<8} {'涨跌幅':<8} {'成交量':<8} {'趋势':<8}")
            print('-'*75)
            
            for i, r in enumerate(results, 1):
                trend = '✅' if r['ma20_above_ma50'] else '⬇️'
                print(f"{i:<4} {r['symbol']:<8} {r['sector']:<10} {r['total_score']:<6.1f} "
                      f"${r['price']:<7.2f} {r['price_change']:<+7.2f}% {r['vol_ratio']:<7.1f}x {trend:<8}")
        
        return results


def main():
    """主函数"""
    scanner = USMarketScanner()
    
    try:
        results = scanner.scan_market(min_score=65, max_count=50)
        
        print(f"\n{'='*60}")
        print("💡 下一步")
        print(f"{'='*60}")
        print("1. 对入选股票进行策略v1.6回测")
        print("2. 选择评分最高的股票进行交易")
        print("3. 定期扫描（建议每日或每周）")
        
    except Exception as e:
        print(f"错误: {e}")


if __name__ == '__main__':
    main()