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
        """获取港股资金流向（2026-06-18 修复）

        原 BUG：get_capital_flow('HK.800000') 返回 "只支持正股/窝轮/基金"错误
        修复：用 get_capital_distribution 逐只拉取恒指 10 大权重股，累加净流入
        返回：单位亿港元（正=净流入, 负=净流出）
        """
        # 恒生指数 10 大权重股（按资金权重）
        weights = [
            'HK.00700',  # 腾讯
            'HK.09988',  # 阿里
            'HK.00005',  # 汇丰
            'HK.01299',  # 友邦
            'HK.03690',  # 美团
            'HK.02318',  # 平安
            'HK.00939',  # 建行
            'HK.00388',  # 港交所
            'HK.00941',  # 中移动
            'HK.00883',  # 中海油
        ]
        try:
            total_in = 0.0
            total_out = 0.0
            ok_count = 0
            for sym in weights:
                ret, data = self.quote_ctx.get_capital_distribution(sym)
                if ret != RET_OK or data is None or len(data) == 0:
                    continue
                row = data.iloc[0]
                in_v = (
                    float(row.get('capital_in_super', 0) or 0)
                    + float(row.get('capital_in_big', 0) or 0)
                    + float(row.get('capital_in_mid', 0) or 0)
                    + float(row.get('capital_in_small', 0) or 0)
                )
                out_v = (
                    float(row.get('capital_out_super', 0) or 0)
                    + float(row.get('capital_out_big', 0) or 0)
                    + float(row.get('capital_out_mid', 0) or 0)
                    + float(row.get('capital_out_small', 0) or 0)
                )
                total_in += in_v
                total_out += out_v
                ok_count += 1
            if ok_count >= 5:
                net_flow = (total_in - total_out) / 1e8
                self.capital_flow = net_flow
                self._capital_flow_detail = {
                    'in_total': total_in / 1e8,
                    'out_total': total_out / 1e8,
                    'net': net_flow,
                    'sample_size': ok_count,
                    'note': '基于恒指 10 大权重股资金分布累加',
                }
                return net_flow
            else:
                print(f"资金流向取数不足：仅{ok_count}只成功")
        except Exception as e:
            print(f"获取资金流向失败: {e}")
        return None

    def get_warrant_ratio(self):
        """获取港股多空资金比（2026-06-18 修复）

        原 BUG：get_warrant() 缺少 req 参数，data 返回 tuple 未解包
        修复：用 Request 分别查 BULL+CALL / BEAR+PUT，按成交额计算比例
        返回：BULL_CALL成交额 / BEAR_PUT成交额  > 1 看多, < 1 看空
        """
        try:
            from futu import WrtType
            from futu.quote.quote_get_warrant import Request

            def _sum_turnover(types):
                total = 0.0
                begin = 0
                while True:
                    req = Request()
                    req.begin = begin
                    req.num = 200
                    req.stock_owner = 'HK.800000'
                    req.type_list = types
                    ret, data = self.quote_ctx.get_warrant('HK.800000', req=req)
                    if not isinstance(data, tuple):
                        return None
                    df, has_more, _total = data
                    if df is None or len(df) == 0:
                        break
                    total += float(df['turnover'].fillna(0).sum())
                    if not has_more:
                        break
                    begin += len(df)
                    if begin >= 1000:
                        break
                return total

            bull = _sum_turnover([WrtType.BULL, WrtType.CALL])
            bear = _sum_turnover([WrtType.BEAR, WrtType.PUT])
            if bull is None or bear is None or bear <= 0:
                print(f"牛熊证取数不完整: bull={bull}, bear={bear}")
                return None
            ratio = round(bull / bear, 3)
            self.bull_bear_ratio = ratio
            self._warrant_detail = {
                'bull_call_turnover': bull,
                'bear_put_turnover': bear,
                'ratio': ratio,
                'note': '多头(BULL+CALL) ÷ 空头(BEAR+PUT) 成交额比；>1 看多, <1 看空',
            }
            return ratio
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
        if flow is not None:
            sentiment['capital_flow'] = flow
            sentiment['capital_flow_detail'] = getattr(self, '_capital_flow_detail', None)
            if flow >= 50:  # 亿港元
                sentiment['flow_sentiment'] = '大流入'
                sentiment['flow_score'] = 80
            elif flow >= 20:
                sentiment['flow_sentiment'] = '流入'
                sentiment['flow_score'] = 65
            elif flow >= -20:
                sentiment['flow_sentiment'] = '中性'
                sentiment['flow_score'] = 50
            elif flow >= -50:
                sentiment['flow_sentiment'] = '流出'
                sentiment['flow_score'] = 35
            else:
                sentiment['flow_sentiment'] = '大流出'
                sentiment['flow_score'] = 20
        
        # 获取牛熊证比例
        ratio = self.get_warrant_ratio()
        if ratio is not None:
            sentiment['bull_bear_ratio'] = ratio
            sentiment['warrant_detail'] = getattr(self, '_warrant_detail', None)
            if ratio >= 1.5:
                sentiment['warrant_sentiment'] = '看多'
                sentiment['warrant_score'] = 75
            elif ratio >= 1.0:
                sentiment['warrant_sentiment'] = '中性'
                sentiment['warrant_score'] = 50
            elif ratio >= 0.7:
                sentiment['warrant_sentiment'] = '偏空'
                sentiment['warrant_score'] = 35
            else:
                sentiment['warrant_sentiment'] = '看空'
                sentiment['warrant_score'] = 20
        
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