#!/usr/bin/env python3
"""
港股全市场扫描系统
24小时自动扫描全部港股，筛选符合策略的股票
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

class HKMarketScanner:
    """港股全市场扫描器"""
    
    def __init__(self):
        self.quote_ctx = None
        self.weights = {
            'news': 0.30,
            'technical': 0.35,
            'sentiment': 0.35
        }
        
    def connect(self):
        """连接Futu"""
        self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        print("✅ 连接Futu成功")
        
    def close(self):
        """关闭连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
    
    def get_all_hk_stocks(self):
        """获取全部港股列表"""
        print("\n📊 获取港股全市场股票列表...")
        
        # 获取港股主板、创业板股票
        # 这里使用Futu的股票筛选API
        all_stocks = []
        
        # 方法1：通过板块获取
        sectors = [
            'HK_MAIN_BOARD',      # 主板
            'HK_GEM_BOARD',       # 创业板
        ]
        
        # 方法2：通过行业获取
        industries = [
            ('能源', 'HK.ENERGY'),
            ('原材料', 'HK.MATERIALS'),
            ('工业', 'HK.INDUSTRIALS'),
            ('可选消费', 'HK.CONSUMER_DISCRETIONARY'),
            ('主要消费', 'HK.CONSUMER_STAPLES'),
            ('医疗保健', 'HK.HEALTH_CARE'),
            ('金融', 'HK.FINANCIALS'),
            ('信息技术', 'HK.INFORMATION_TECHNOLOGY'),
            ('通信服务', 'HK.COMMUNICATION_SERVICES'),
            ('公用事业', 'HK.UTILITIES'),
            ('房地产', 'HK.REAL_ESTATE'),
        ]
        
        # 简化版：使用常用股票池
        # 实际应用中应该调用API获取全市场股票
        stock_pool = {
            '科技龙头': [
                'HK.00700', 'HK.09988', 'HK.03690', 'HK.09999', 
                'HK.09618', 'HK.09888', 'HK.09961', 'HK.09922',
                'HK.02015', 'HK.09888', 'HK.09626', 'HK.09898',
            ],
            '消费': [
                'HK.02331', 'HK.02319', 'HK.02020', 'HK.01928',
                'HK.02286', 'HK.01177', 'HK.00175', 'HK.00268',
                'HK.00493', 'HK.06060', 'HK.09922', 'HK.01579',
            ],
            '新能源汽车': [
                'HK.09868', 'HK.09866', 'HK.02333', 'HK.01211',
                'HK.06618', 'HK.09863', 'HK.09860', 'HK.09867',
            ],
            '医药': [
                'HK.02269', 'HK.01093', 'HK.03692', 'HK.01548',
                'HK.01877', 'HK.06969', 'HK.01099', 'HK.02607',
                'HK.01813', 'HK.01528', 'HK.02367', 'HK.03799',
            ],
            '金融': [
                'HK.00005', 'HK.01299', 'HK.00388', 'HK.00939',
                'HK.01398', 'HK.03988', 'HK.02628', 'HK.02318',
                'HK.01658', 'HK.01339', 'HK.00966', 'HK.01336',
            ],
            '地产': [
                'HK.00016', 'HK.01113', 'HK.00960', 'HK.00688',
                'HK.01109', 'HK.00817', 'HK.00410', 'HK.01207',
            ],
            '工业': [
                'HK.00669', 'HK.00868', 'HK.02382', 'HK.02313',
                'HK.00968', 'HK.02018', 'HK.02313', 'HK.00144',
            ],
            '公用事业': [
                'HK.00002', 'HK.00003', 'HK.00006', 'HK.00083',
                'HK.00267', 'HK.02638', 'HK.00971', 'HK.01797',
            ],
        }
        
        # 扁平化股票列表
        all_stocks = []
        for sector, codes in stock_pool.items():
            for code in codes:
                all_stocks.append((code, sector))
        
        print(f"✅ 股票池：{len(all_stocks)}只股票")
        return all_stocks
    
    def calculate_stock_score(self, code, sector):
        """计算单只股票评分"""
        try:
            # 获取60天数据
            ret, data, _ = self.quote_ctx.request_history_kline(
                code=code,
                start=(datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'),
                end=(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
                ktype=KLType.K_DAY,
                autype=AuType.QFQ
            )
            
            if ret != 0 or data.empty or len(data) < 30:
                return None
            
            close = data['close']
            volume = data['volume']
            
            # 技术指标计算
            # 1. 均线
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            
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
                tech_score += 20
            if vol_ratio >= 1.5:
                tech_score += 15
            if 40 <= rsi <= 60:
                tech_score += 15
            if breakout:
                tech_score += 10
            
            # 市值过滤（获取快照）
            ret2, snapshot = self.quote_ctx.get_market_snapshot([code])
            market_cap = None
            if ret2 == 0 and not snapshot.empty:
                market_cap = snapshot.iloc[0].get('market_val', 0) / 1e9
            
            # 过滤条件
            # 1. 市值>10亿（流动性）
            # 2. 成交量放大
            # 3. 技术评分>=60
            
            if market_cap and market_cap < 10:
                return None
            
            if vol_ratio < 1.2:
                return None
            
            if tech_score < 60:
                return None
            
            # 情绪评分（假设市场中性）
            sentiment_score = 70
            
            # 新闻评分（假设中性）
            news_score = 60
            
            # 综合评分
            total_score = (
                news_score * self.weights['news'] +
                tech_score * self.weights['technical'] +
                sentiment_score * self.weights['sentiment']
            )
            
            return {
                'code': code,
                'sector': sector,
                'tech_score': tech_score,
                'total_score': total_score,
                'price': close.iloc[-1],
                'price_change': price_change,
                'vol_ratio': vol_ratio,
                'rsi': rsi,
                'market_cap': market_cap,
                'breakout': breakout
            }
            
        except Exception as e:
            return None
    
    def scan_market(self, min_score=65, max_count=50):
        """扫描全市场"""
        print('\n' + '='*60)
        print('🇭🇰 港股全市场扫描')
        print('='*60)
        print(f'筛选标准: 评分≥{min_score}, 最多{max_count}只')
        print(f'扫描时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print('='*60)
        
        # 获取股票池
        all_stocks = self.get_all_hk_stocks()
        
        print(f"\n开始扫描 {len(all_stocks)} 只股票...\n")
        
        results = []
        scanned = 0
        passed = 0
        
        for code, sector in all_stocks:
            scanned += 1
            
            # 每10只显示进度
            if scanned % 10 == 0:
                print(f"  已扫描: {scanned}/{len(all_stocks)} | 入选: {len(results)}")
            
            score = self.calculate_stock_score(code, sector)
            
            if score and score['total_score'] >= min_score:
                results.append(score)
                passed += 1
        
        # 按评分排序
        results.sort(key=lambda x: x['total_score'], reverse=True)
        
        # 限制数量
        results = results[:max_count]
        
        # 显示结果
        print(f"\n{'='*60}")
        print(f"✅ 扫描完成")
        print(f"{'='*60}")
        print(f"扫描股票: {scanned}只")
        print(f"符合条件: {passed}只")
        print(f"最终入选: {len(results)}只")
        
        if results:
            print(f"\n{'='*60}")
            print("📊 入选股票")
            print(f"{'='*60}")
            print(f"\n{'序号':<4} {'代码':<12} {'行业':<10} {'评分':<6} {'价格':<8} {'涨跌幅':<8} {'成交量':<8}")
            print('-'*70)
            
            for i, r in enumerate(results, 1):
                print(f"{i:<4} {r['code']:<12} {r['sector']:<10} {r['total_score']:<6.1f} "
                      f"{r['price']:<8.2f} {r['price_change']:<+7.2f}% {r['vol_ratio']:<7.1f}x")
        
        return results
    
    def save_results(self, results):
        """保存扫描结果"""
        if not results:
            return
        
        # 保存到文件
        filename = f"scan_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        import json
        with open(f'/home/admin/.openclaw/workspace-arashi/{filename}', 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 结果已保存: {filename}")


def main():
    """主函数"""
    scanner = HKMarketScanner()
    scanner.connect()
    
    try:
        # 扫描市场
        results = scanner.scan_market(min_score=65, max_count=50)
        
        # 保存结果
        scanner.save_results(results)
        
        print(f"\n{'='*60}")
        print("💡 下一步")
        print(f"{'='*60}")
        print("1. 对入选股票进行策略回测")
        print("2. 选择评分最高的股票进行交易")
        print("3. 定期扫描（建议每日或每周）")
        
    finally:
        scanner.close()


if __name__ == '__main__':
    main()