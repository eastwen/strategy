#!/usr/bin/env python3
"""
CNN恐慌贪婪指数获取器
"""

import requests
from datetime import datetime
from typing import Optional, Dict
import json

class FearGreedIndex:
    """CNN恐慌贪婪指数获取器"""
    
    def __init__(self):
        self.base_url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        self.cache = None
        self.cache_time = None
        
    def get_index(self, date_str: str = None) -> Optional[Dict]:
        """
        获取恐慌贪婪指数
        
        Args:
            date_str: 日期字符串，默认今天
        
        Returns:
            {
                "score": 14.59,
                "rating": "extreme fear",
                "timestamp": "2026-03-20T23:59:51+00:00",
                "previous_close": 17.17,
                "previous_1_week": 22.63,
                "previous_1_month": 44.41,
                "previous_1_year": 21.69
            }
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        url = f"{self.base_url}/{date_str}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Origin': 'https://edition.cnn.com',
            'Referer': 'https://edition.cnn.com/markets/fear-and-greed'
        }
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            
            if res.status_code == 200:
                data = res.json()
                
                if 'fear_and_greed' in data:
                    fng = data['fear_and_greed']
                    
                    result = {
                        "score": round(fng.get('score', 0), 2),
                        "rating": fng.get('rating', 'unknown'),
                        "timestamp": fng.get('timestamp', ''),
                        "previous_close": round(fng.get('previous_close', 0), 2),
                        "previous_1_week": round(fng.get('previous_1_week', 0), 2),
                        "previous_1_month": round(fng.get('previous_1_month', 0), 2),
                        "previous_1_year": round(fng.get('previous_1_year', 0), 2)
                    }
                    
                    # 缓存结果
                    self.cache = result
                    self.cache_time = datetime.now()
                    
                    return result
            
            return None
            
        except Exception as e:
            print(f"⚠️ 获取恐慌贪婪指数失败: {e}")
            return None
    
    def get_sentiment_level(self, score: float) -> str:
        """根据分数获取情绪等级"""
        if score >= 75:
            return "extreme_greed"
        elif score >= 55:
            return "greed"
        elif score >= 45:
            return "neutral"
        elif score >= 25:
            return "fear"
        else:
            return "extreme_fear"
    
    def get_sentiment_description(self, rating: str) -> str:
        """获取情绪描述"""
        descriptions = {
            "extreme fear": "极度恐慌",
            "fear": "恐慌",
            "neutral": "中性",
            "greed": "贪婪",
            "extreme greed": "极度贪婪"
        }
        return descriptions.get(rating.lower(), "未知")


def get_fear_greed_index() -> Optional[Dict]:
    """便捷函数：获取恐慌贪婪指数"""
    fng = FearGreedIndex()
    return fng.get_index()


if __name__ == "__main__":
    print("="*50)
    print("📊 CNN恐慌贪婪指数")
    print("="*50)
    
    fng = FearGreedIndex()
    result = fng.get_index()
    
    if result:
        print(f"\n当前指数: {result['score']}")
        print(f"情绪状态: {result['rating']} ({fng.get_sentiment_description(result['rating'])})")
        print(f"更新时间: {result['timestamp']}")
        print(f"\n历史对比:")
        print(f"  昨日收盘: {result['previous_close']}")
        print(f"  上周: {result['previous_1_week']}")
        print(f"  上月: {result['previous_1_month']}")
        print(f"  去年: {result['previous_1_year']}")
        
        # 情绪分析
        level = fng.get_sentiment_level(result['score'])
        print(f"\n情绪等级: {level}")
        
        # 交易建议
        if result['score'] <= 25:
            print("💡 建议: 市场极度恐慌，可能是买入机会")
        elif result['score'] >= 75:
            print("💡 建议: 市场极度贪婪，注意风险，考虑减仓")
        else:
            print("💡 建议: 市场情绪正常，维持现有策略")
    else:
        print("❌ 获取失败")
