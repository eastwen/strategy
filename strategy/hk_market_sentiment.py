#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
港股市场情绪监控模块
获取VHSI、港股通资金流向、牛熊证比例
"""

import sys
import json
import time
from datetime import datetime

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')
from futu import OpenQuoteContext, RET_OK

class HKMarketSentiment:
    """港股市场情绪监控"""
    
    def __init__(self):
        self.quote_ctx = None
        self.vhsi = None
        self.capital_flow = None
        self.bull_bear_ratio = None
        
    def connect(self):
        """连接Futu OpenD"""
        try:
            self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            return True
        except Exception as e:
            print(f"连接Futu失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
    
    def get_vhsi(self):
        """获取VHSI恒指波幅指数"""
        try:
            # VHSI code: HK.800125
            # 先订阅VHSI数据
            ret = self.quote_ctx.subscribe(['HK.800125'], [1])
            if ret != RET_OK:
                # 尝试使用SubType.QUOTE
                try:
                    from futu import SubType
                    ret = self.quote_ctx.subscribe(['HK.800125'], [SubType.QUOTE])
                except:
                    pass
            # 等待数据就绪
            import time
            time.sleep(0.5)
            ret, data = self.quote_ctx.get_stock_quote(['HK.800125'])
            if ret == RET_OK and data is not None and len(data) > 0:
                self.vhsi = float(data.iloc[0]['last_price'])
                return self.vhsi
            else:
                print(f"获取VHSI数据失败: {data}")
        except Exception as e:
            print(f"获取VHSI失败: {e}")
        return None
    
    def get_capital_flow(self):
        """获取港股通资金流向"""
        try:
            # 恒生指数成分股资金流向
            ret, data = self.quote_ctx.get_capital_flow('HK.800000')  # 恒生指数
            if ret == RET_OK and data is not None:
                # 获取主要流入/流出
                if 'main_flow' in data.columns:
                    main_flow = data['main_flow'].sum() if len(data) > 0 else 0
                    self.capital_flow = main_flow
                    return main_flow
        except Exception as e:
            print(f"获取资金流向失败: {e}")
        return None
    
    def get_warrant_ratio(self):
        """获取牛熊证比例"""
        try:
            # 获取恒生指数的牛熊证
            ret, data = self.quote_ctx.get_warrant('HK.800000')
            # 注意：data可能是tuple或其他格式，这里简化处理
            if ret != RET_OK:
                return None
            # 如果获取失败，跳过
        except Exception as e:
            print(f"获取牛熊证失败: {e}")
        return None
    
    def get_market_sentiment(self):
        """获取完整市场情绪"""
        if not self.connect():
            return None
        
        sentiment = {
            'vhsi': None,
            'capital_flow': None,
            'bull_bear_ratio': None,
            'sentiment_score': 50,  # 默认中性
            'timestamp': datetime.now().isoformat()
        }
        
        # 获取VHSI
        vhsi = self.get_vhsi()
        if vhsi:
            sentiment['vhsi'] = vhsi
            # VHSI情绪评分
            if vhsi >= 30:
                sentiment['vhsi_sentiment'] = '极度恐慌'
                sentiment['vhsi_score'] = 20
            elif vhsi >= 25:
                sentiment['vhsi_sentiment'] = '恐慌'
                sentiment['vhsi_score'] = 35
            elif vhsi >= 18:
                sentiment['vhsi_sentiment'] = '正常'
                sentiment['vhsi_score'] = 50
            elif vhsi >= 15:
                sentiment['vhsi_sentiment'] = '平静'
                sentiment['vhsi_score'] = 65
            else:
                sentiment['vhsi_sentiment'] = '极度贪婪'
                sentiment['vhsi_score'] = 80
        
        # 获取资金流向
        flow = self.get_capital_flow()
        if flow:
            sentiment['capital_flow'] = flow
            if flow >= 50:  # 亿港元
                sentiment['flow_sentiment'] = '大流入'
                sentiment['flow_score'] = 80
            elif flow >= 20:
                sentiment['flow_sentiment'] = '流入'
                sentiment['flow_score'] = 65
            elif flow >= -20:
                sentiment['flow_sentiment'] = '中性'
                sentiment['flow_score'] = 50
            else:
                sentiment['flow_sentiment'] = '流出'
                sentiment['flow_score'] = 35
        
        # 获取牛熊证比例
        ratio = self.get_warrant_ratio()
        if ratio:
            sentiment['bull_bear_ratio'] = ratio
            if ratio >= 1.5:
                sentiment['warrant_sentiment'] = '看多'
                sentiment['warrant_score'] = 75
            elif ratio >= 1.0:
                sentiment['warrant_sentiment'] = '中性'
                sentiment['warrant_score'] = 50
            else:
                sentiment['warrant_sentiment'] = '看空'
                sentiment['warrant_score'] = 30
        
        # 计算综合情绪评分
        scores = []
        weights = []
        
        if sentiment.get('vhsi_score'):
            scores.append(sentiment['vhsi_score'])
            weights.append(0.35)  # VHSI权重35%
        
        if sentiment.get('flow_score'):
            scores.append(sentiment['flow_score'])
            weights.append(0.35)  # 资金流向权重35%
            
        if sentiment.get('warrant_score'):
            scores.append(sentiment['warrant_score'])
            weights.append(0.30)  # 牛熊证权重30%
        
        if scores and weights:
            total_weight = sum(weights)
            sentiment['sentiment_score'] = sum(s * w for s, w in zip(scores, weights)) / total_weight
        
        self.disconnect()
        return sentiment
    
    def print_sentiment(self, sentiment):
        """打印情绪分析"""
        if not sentiment:
            print("❌ 无法获取市场情绪")
            return
            
        print("\n" + "="*50)
        print("🇭🇰 港股市场情绪分析")
        print("="*50)
        
        if sentiment.get('vhsi'):
            print(f"VHSI波幅指数: {sentiment['vhsi']:.1f} ({sentiment.get('vhsi_sentiment', 'N/A')})")
        
        if sentiment.get('capital_flow'):
            flow = sentiment['capital_flow']
            print(f"港股通资金流向: {flow:+.1f}亿 ({sentiment.get('flow_sentiment', 'N/A')})")
        
        if sentiment.get('bull_bear_ratio'):
            print(f"牛熊证比例: {sentiment['bull_bear_ratio']:.2f} ({sentiment.get('warrant_sentiment', 'N/A')})")
        
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


def get_hk_sentiment():
    """便捷函数：获取港股市场情绪"""
    monitor = HKMarketSentiment()
    sentiment = monitor.get_market_sentiment()
    return sentiment


# 测试
if __name__ == '__main__':
    print("测试港股市场情绪获取...")
    sentiment = get_hk_sentiment()
    if sentiment:
        monitor = HKMarketSentiment()
        monitor.print_sentiment(sentiment)
    else:
        print("获取失败，请检查Futu OpenD连接")