#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
美股市场情绪监控模块
获取VIX恐慌指数、恐慌贪婪指数、期权比例
"""

import sys
import json
import time
import requests
from datetime import datetime

class USMarketSentiment:
    """美股市场情绪监控"""
    
    def __init__(self):
        self.vix = None
        self.fear_greed = None
        self.option_ratio = None
    
    def get_vix(self):
        """获取VIX恐慌指数"""
        try:
            url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d'
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
                vix = meta.get('regularMarketPrice', 0)
                if vix and vix > 0:
                    self.vix = float(vix)
                    return self.vix
        except Exception as e:
            print(f"获取VIX失败: {e}")
        return None
    
    def get_fear_greed(self):
        """获取恐慌贪婪指数（用VIX转换）"""
        try:
            vix = self.get_vix()
            if vix:
                # VIX 15-25对应贪婪指数25-75
                fear_greed = max(0, min(100, 100 - (vix - 10) * 3.33))
                self.fear_greed = fear_greed
                return self.fear_greed
        except Exception as e:
            print(f"获取恐慌贪婪指数失败: {e}")
        return None
    
    def get_market_sentiment(self):
        """获取完整市场情绪"""
        sentiment = {
            'vix': None,
            'fear_greed': None,
            'option_ratio': None,
            'sentiment_score': 50,
            'timestamp': datetime.now().isoformat()
        }
        
        # 1. 获取VIX恐慌指数
        vix = self.get_vix()
        if vix:
            sentiment['vix'] = vix
            if vix >= 30:
                sentiment['vix_sentiment'] = '极度恐慌'
                sentiment['vix_score'] = 20
            elif vix >= 25:
                sentiment['vix_sentiment'] = '恐慌'
                sentiment['vix_score'] = 35
            elif vix >= 18:
                sentiment['vix_sentiment'] = '正常'
                sentiment['vix_score'] = 50
            elif vix >= 15:
                sentiment['vix_sentiment'] = '平静'
                sentiment['vix_score'] = 65
            else:
                sentiment['vix_sentiment'] = '极度贪婪'
                sentiment['vix_score'] = 80
        
        # 2. 获取恐慌贪婪指数（从VIX转换）
        fear_greed = self.get_fear_greed()
        if fear_greed:
            sentiment['fear_greed'] = fear_greed
            if fear_greed <= 25:
                sentiment['fg_sentiment'] = '极度恐惧'
                sentiment['fg_score'] = 20
            elif fear_greed <= 45:
                sentiment['fg_sentiment'] = '恐惧'
                sentiment['fg_score'] = 35
            elif fear_greed <= 55:
                sentiment['fg_sentiment'] = '中性'
                sentiment['fg_score'] = 50
            elif fear_greed <= 75:
                sentiment['fg_sentiment'] = '贪婪'
                sentiment['fg_score'] = 65
            else:
                sentiment['fg_sentiment'] = '极度贪婪'
                sentiment['fg_score'] = 80
        
        # 计算综合情绪评分
        scores = []
        weights = []
        
        if sentiment.get('vix_score'):
            scores.append(sentiment['vix_score'])
            weights.append(0.50)  # VIX权重50%
        if sentiment.get('fg_score'):
            scores.append(sentiment['fg_score'])
            weights.append(0.50)  # 恐慌贪婪指数权重50%
        
        if scores and weights:
            sentiment['sentiment_score'] = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
        
        return sentiment
    
    def print_sentiment(self, sentiment):
        """打印情绪分析"""
        if not sentiment:
            print("❌ 无法获取市场情绪")
            return
            
        print("\n" + "="*50)
        print("🇺🇸 美股市场情绪分析")
        print("="*50)
        
        if sentiment.get('vix'):
            print(f"VIX恐慌指数: {sentiment['vix']:.1f} ({sentiment.get('vix_sentiment', 'N/A')})")
        
        if sentiment.get('fear_greed'):
            print(f"恐慌贪婪指数: {sentiment['fear_greed']:.0f} ({sentiment.get('fg_sentiment', 'N/A')})")
        
        score = sentiment.get('sentiment_score', 50)
        print(f"\n综合情绪评分: {score:.0f}/100")
        
        if score >= 70:
            print("📈 市场情绪: 乐观")
        elif score >= 50:
            print("➡️ 市场情绪: 中性")
        elif score >= 30:
            print("📉 市场情绪: 谨慎")
        else:
            print("⚠️ 市场情绪: 恐慌")
        
        print("="*50)


def get_us_sentiment():
    """便捷函数：获取美股市场情绪"""
    monitor = USMarketSentiment()
    sentiment = monitor.get_market_sentiment()
    return sentiment


# 测试
if __name__ == '__main__':
    print("测试美股市场情绪获取...")
    sentiment = get_us_sentiment()
    if sentiment:
        monitor = USMarketSentiment()
        monitor.print_sentiment(sentiment)
    else:
        print("获取失败，请检查网络连接")