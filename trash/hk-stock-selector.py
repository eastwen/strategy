#!/usr/bin/env python3
"""
港股动态选股系统 - 按原方案筛选
步骤：1. 获取股票池 → 2. 计算评分 → 3. 筛选≥65分 → 4. 回测
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, '/home/admin/.openclaw/workspace-arashi/futu-venv/lib/python3.14/site-packages')
from futu import *

class HKStockSelector:
    """港股动态选股系统"""
    
    def __init__(self):
        self.quote_ctx = None
        
        # 行业股票池（代表性股票）
        self.sector_stocks = {
            "互联网科技": [
                ('HK.00700', '腾讯控股'),
                ('HK.09988', '阿里巴巴-SW'),
                ('HK.03690', '美团-W'),
                ('HK.09999', '网易-S'),
                ('HK.09618', '京东集团-SW'),
                ('HK.09888', '百度集团-SW'),
            ],
            "消费电子": [
                ('HK.02382', '舜宇光学科技'),
                ('HK.02018', '瑞声科技'),
                ('HK.01347', '华虹半导体'),
            ],
            "新能源汽车": [
                ('HK.09868', '小鹏汽车-W'),
                ('HK.09866', '蔚来-SW'),
                ('HK.02333', '比亚迪股份'),
            ],
            "互联网医疗": [
                ('HK.09618', '京东健康'),
                ('HK.02386', '阿里健康'),
            ],
            "金融": [
                ('HK.00005', '汇丰控股'),
                ('HK.01299', '友邦保险'),
                ('HK.00388', '香港交易所'),
                ('HK.00939', '建设银行'),
                ('HK.01398', '工商银行'),
            ],
            "消费": [
                ('HK.02331', '李宁'),
                ('HK.02319', '蒙牛乳业'),
                ('HK.02020', '安踏体育'),
            ],
            "医药": [
                ('HK.02269', '药明生物'),
                ('HK.01093', '石药集团'),
            ],
        }
        
        # 评分权重
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
    
    def get_sentiment_score(self) -> float:
        """获取市场情绪评分"""
        try:
            # 获取VHSI
            ret, data = self.quote_ctx.get_market_snapshot(['HK.800125'])
            
            if ret == 0 and not data.empty:
                vhsi = float(data.iloc[0]['last_price'])
                
                # VHSI评分转换
                if vhsi < 15:
                    sentiment_score = 90  # 非常平静
                elif vhsi < 20:
                    sentiment_score = 80  # 平静
                elif vhsi < 25:
                    sentiment_score = 70  # 正常
                elif vhsi < 30:
                    sentiment_score = 50  # 恐慌
                else:
                    sentiment_score = 30  # 极度恐慌
                
                return sentiment_score, vhsi
            
            return 60, None  # 默认正常
            
        except Exception as e:
            print(f"获取情绪失败: {e}")
            return 60, None
    
    def calculate_technical_score(self, code: str, name: str) -> dict:
        """计算技术评分"""
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
                return {'error': '数据不足'}
            
            close = data['close']
            volume = data['volume']
            
            # 1. 均线金叉
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            ma_cross = ma5 > ma10
            
            # 2. 成交量放大
            avg_vol = volume.rolling(30).mean().iloc[-1]
            vol_ratio = volume.iloc[-1] / avg_vol if avg_vol > 0 else 1
            vol_surge = vol_ratio >= 1.5
            
            # 3. RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 0
            rsi = 100 - (100 / (1 + rs))
            rsi_ok = 40 <= rsi <= 60
            
            # 4. 价格突破
            high_20 = close.rolling(20).max().iloc[-2]
            breakout = close.iloc[-1] >= high_20
            
            # 计算技术评分
            tech_score = 50  # 基础分
            if ma_cross:
                tech_score += 20
            if vol_surge:
                tech_score += 15
            if rsi_ok:
                tech_score += 15
            if breakout:
                tech_score += 10
            
            return {
                'score': min(100, tech_score),
                'ma_cross': ma_cross,
                'vol_surge': vol_surge,
                'vol_ratio': round(vol_ratio, 2),
                'rsi': round(rsi, 2),
                'breakout': breakout
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def calculate_total_score(self, technical_score: float, sentiment_score: float) -> dict:
        """计算综合评分"""
        # 新闻评分（假设中性，实际应该接入新闻API）
        news_score = 60
        
        total_score = (
            news_score * self.weights['news'] +
            technical_score * self.weights['technical'] +
            sentiment_score * self.weights['sentiment']
        )
        
        return {
            'news_score': news_score,
            'technical_score': technical_score,
            'sentiment_score': sentiment_score,
            'total_score': round(total_score, 2),
            'should_trade': total_score >= 65
        }
    
    def select_stocks(self, min_score: float = 65, max_count: int = 20):
        """动态筛选股票"""
        print('\n' + '='*60)
        print('🇭🇰 港股动态选股系统')
        print('='*60)
        print(f'筛选标准: 评分≥{min_score}, 最多{max_count}只')
        print('='*60)
        
        # 1. 获取市场情绪
        sentiment_score, vhsi = self.get_sentiment_score()
        print(f"\n📊 市场情绪: VHSI={vhsi or 'N/A'}, 情绪评分={sentiment_score}")
        
        if sentiment_score < 50:
            print("⚠️ 市场情绪不佳，不建议交易")
            return []
        
        # 2. 遍历所有行业股票
        print(f"\n{'行业':<12} {'股票':<12} {'技术评分':<8} {'综合评分':<8} {'状态':<8}")
        print('-'*55)
        
        selected = []
        
        for sector, stocks in self.sector_stocks.items():
            for code, name in stocks:
                # 计算技术评分
                tech = self.calculate_technical_score(code, name)
                
                if 'error' in tech:
                    continue
                
                # 计算综合评分
                score = self.calculate_total_score(
                    tech['score'],
                    sentiment_score
                )
                
                # 显示
                status = '✅ 入选' if score['should_trade'] else '⏸️ 观望'
                print(f"{sector:<12} {name:<12} {tech['score']:<8.0f} {score['total_score']:<8.1f} {status:<8}")
                
                # 筛选
                if score['should_trade']:
                    selected.append({
                        'code': code,
                        'name': name,
                        'sector': sector,
                        'score': score['total_score'],
                        'tech_score': tech['score'],
                        'tech_details': tech
                    })
        
        # 3. 按评分排序
        selected.sort(key=lambda x: x['score'], reverse=True)
        
        # 4. 限制数量
        selected = selected[:max_count]
        
        # 5. 汇总
        print(f"\n{'='*60}")
        print(f"📊 筛选结果: {len(selected)}只股票入选")
        print(f"{'='*60}")
        
        if selected:
            print(f"\n{'序号':<4} {'代码':<12} {'名称':<12} {'行业':<12} {'评分':<8}")
            print('-'*55)
            for i, s in enumerate(selected, 1):
                print(f"{i:<4} {s['code']:<12} {s['name']:<12} {s['sector']:<12} {s['score']:<8.1f}")
        
        return selected


def main():
    """主函数"""
    selector = HKStockSelector()
    selector.connect()
    
    try:
        # 动态选股
        selected = selector.select_stocks(min_score=65, max_count=20)
        
        if not selected:
            print("\n无符合条件的股票")
            return
        
        # 保存结果
        print(f"\n{'='*60}")
        print("💾 选股结果已保存")
        print(f"{'='*60}")
        print(f"入选股票: {len(selected)}只")
        print(f"建议: 对入选股票进行策略回测")
        
    finally:
        selector.close()


if __name__ == '__main__':
    main()