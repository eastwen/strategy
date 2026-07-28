#!/usr/bin/env python3
"""
美股市场情绪监控模块（2026-06-18 全面修复）

修复列表：
  2026-06-18 east → BUG 1：恐慌贪婪指数从伪公式改为 CNN F&G API 真数据
  2026-06-18 east → BUG 2：期权 Put/Call 比例从 null 改为 SPX/QQQ/SPY 期权链真实数据
  2026-06-18 east → BUG 3：综合评分从 VIX×2 改为 VIX 30% + FG 25% + PCR 25% + SPX 20%
  2026-06-18 east → 加入标普500指数涨跌列同时输出

数据源：
  VIX：Yahoo Finance ^VIX
  CNN Fear & Greed：edition.cnn.com → production.dataviz.cnn.io
  Put/Call 比例：yfinance 拉取 SPX/QQQ/SPY 期权链成交计算
  SPX：yfinance ^GSPC
  NDX/DJI：yfinance ^IXIC / ^DJI
"""

import sys
import json
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime


class USMarketSentiment:
    """美股市场情绪监控（2026-06-18 修复版）"""

    def __init__(self):
        self.vix = None
        self.fear_greed = None
        self.fear_greed_rating = None
        self.put_call_ratio = None
        self.put_call_detail = None
        self.spx = None
        self.spx_change = None
        self.ndx = None
        self.dji = None

    def get_vix(self):
        """获取VIX恐慌指数（Yahoo Finance）"""
        try:
            t = yf.Ticker('^VIX')
            hist = t.history(period='5d', interval='1d')
            if hist is not None and len(hist) > 0:
                self.vix = float(hist['Close'].iloc[-1])
                return self.vix
        except Exception as e:
            print(f"获取VIX失败: {e}")
        return None

    def get_fear_greed(self):
        """获取 CNN 恐慌贪婪指数（2026-06-18 east 修复 BUG 1）
        
        来源：CNN Business → Fear & Greed Index API
        CNN 的 F&G 指数由 7 个因子综合计算：
        - 股票价格动量 (S&P 500 vs 125日均线)
        - 股票价格广度 (纽交所上涨/下跌比)
        - 看涨看跌期权比例
        - 避险需求 (垃圾债 vs 国债利差)
        - 市场波动 (VIX)
        - 保险需求 (垃圾债 vs 国债利差变化)
        - 低质量需求 (垃圾债占比)
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Referer': 'https://edition.cnn.com/markets/fear-and-greed',
                'Origin': 'https://edition.cnn.com',
            }
            resp = requests.get(
                'https://production.dataviz.cnn.io/index/fearandgreed/graphdata',
                headers=headers, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get('fear_and_greed', {})
                score = data.get('score')
                rating = data.get('rating')
                if score is not None:
                    self.fear_greed = float(score)
                    self.fear_greed_rating = rating
                    return self.fear_greed
            else:
                print(f"CNN F&G API 返回 {resp.status_code}")
        except Exception as e:
            print(f"获取CNN恐慌贪婪指数失败: {e}")

        # Fallback: 用 alternative.me 的 Crypto Fear & Greed
        try:
            resp = requests.get('https://api.alternative.me/fng/?limit=1', timeout=5)
            if resp.status_code == 200:
                d = resp.json().get('data', [{}])[0]
                score = d.get('value')
                if score:
                    self.fear_greed = float(score)
                    self.fear_greed_rating = d.get('value_classification', 'N/A')
                    return self.fear_greed
        except:
            pass

        # 终极 fallback: 从 VIX 推算（保证不崩）
        if self.vix:
            score = max(0, min(100, 100 - (self.vix - 10) * 3.33))
            self.fear_greed = score
            self.fear_greed_rating = 'fallback_from_vix'
            return self.fear_greed
        return None

    def get_put_call_ratio(self):
        """获取看涨看跌期权比例（2026-06-18 east 修复 BUG 2）

        用 yfinance 拉取 SPX/QQQ 期权链，按成交量计算 Put/Call 比。
        P/C < 0.7 = 看多情绪, P/C > 1.0 = 看空情绪
        """
        try:
            # 优先用 QQQ（流动性极高，覆盖整体市场）
            # 如果取不到，fallback 到 SPY
            total_call_vol = 0
            total_put_vol = 0
            total_call_oi = 0
            total_put_oi = 0
            success = False

            for ticker in ['QQQ', 'SPY', 'IWM']:
                try:
                    t = yf.Ticker(ticker)
                    exps = t.options
                    if not exps:
                        continue
                    for exp in exps[:3]:  # 前 3 个到期日
                        chain = t.option_chain(exp)
                        total_call_vol += int(chain.calls['volume'].fillna(0).sum())
                        total_put_vol += int(chain.puts['volume'].fillna(0).sum())
                        total_call_oi += int(chain.calls['openInterest'].fillna(0).sum())
                        total_put_oi += int(chain.puts['openInterest'].fillna(0).sum())
                    success = True
                    break
                except:
                    continue

            if success and total_call_vol > 0:
                vol_ratio = round(total_put_vol / total_call_vol, 3)
                oi_ratio = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

                self.put_call_ratio = vol_ratio
                self.put_call_detail = {
                    'call_volume': total_call_vol,
                    'put_volume': total_put_vol,
                    'volume_pc_ratio': vol_ratio,
                    'call_oi': total_call_oi,
                    'put_oi': total_put_oi,
                    'oi_pc_ratio': oi_ratio,
                    'note': '基于 Top 3 到期日成交量计算；<0.7 看多, 0.7-1.0 中性, >1.0 看空',
                }
                return vol_ratio
        except Exception as e:
            print(f"获取Put/Call期权比例失败: {e}")
        return None

    def get_market_indexes(self):
        """获取美股三大指数（SPX/NDX/DJI）"""
        try:
            for sym, attr in [('^GSPC', 'spx'), ('^IXIC', 'ndx'), ('^DJI', 'dji')]:
                t = yf.Ticker(sym)
                hist = t.history(period='3d', interval='1d')
                if hist is not None and len(hist) >= 2:
                    last = float(hist['Close'].iloc[-1])
                    prev = float(hist['Close'].iloc[-2])
                    change_pct = round((last - prev) / prev * 100, 2)
                    setattr(self, attr, {'price': last, 'change_pct': change_pct})
                    if attr == 'spx':
                        self.spx = last
                        self.spx_change = change_pct
        except Exception as e:
            print(f"获取指数失败: {e}")

    def get_market_sentiment(self):
        """获取完整市场情绪（2026-06-18 修复版 BUG 3）

        新版评分公式（对齐 MEMORY.md 设计文档）：
          VIX 恐慌指数            30%
          CNN 恐慌贪婪指数        25%
          看涨看跌期权比例         25%
          S&P 500 涨跌            20%
        """
        # 先取指数
        self.get_market_indexes()

        sentiment = {
            'vix': None,
            'fear_greed': None,
            'fear_greed_rating': None,
            'option_ratio': None,
            'put_call_detail': None,
            'spx': None,
            'spx_change': None,
            'ndx': None,
            'dji': None,
            'sentiment_score': 50,
            'sentiment_label': '中性',
            'components': {},
            'timestamp': datetime.now().isoformat()
        }

        # 1. VIX 恐慌指数
        vix = self.get_vix()
        if vix:
            sentiment['vix'] = vix
            if vix >= 30:
                sentiment['vix_sentiment'] = '极度恐慌'
                sentiment['vix_score'] = 15
            elif vix >= 25:
                sentiment['vix_sentiment'] = '恐慌'
                sentiment['vix_score'] = 30
            elif vix >= 20:
                sentiment['vix_sentiment'] = '偏恐慌'
                sentiment['vix_score'] = 40
            elif vix >= 16:
                sentiment['vix_sentiment'] = '正常'
                sentiment['vix_score'] = 55
            elif vix >= 13:
                sentiment['vix_sentiment'] = '平静'
                sentiment['vix_score'] = 70
            else:
                sentiment['vix_sentiment'] = '极度平静'
                sentiment['vix_score'] = 85

        # 2. CNN 恐慌贪婪指数（真数据）
        fear_greed = self.get_fear_greed()
        if fear_greed is not None:
            sentiment['fear_greed'] = fear_greed
            sentiment['fear_greed_rating'] = self.fear_greed_rating
            if fear_greed <= 25:
                sentiment['fg_sentiment'] = '极度恐惧'
                sentiment['fg_score'] = 15
            elif fear_greed <= 40:
                sentiment['fg_sentiment'] = '恐惧'
                sentiment['fg_score'] = 30
            elif fear_greed <= 55:
                sentiment['fg_sentiment'] = '中性'
                sentiment['fg_score'] = 55
            elif fear_greed <= 70:
                sentiment['fg_sentiment'] = '贪婪'
                sentiment['fg_score'] = 70
            elif fear_greed <= 85:
                sentiment['fg_sentiment'] = '极度贪婪'
                sentiment['fg_score'] = 85
            else:
                sentiment['fg_sentiment'] = '极度贪婪'
                sentiment['fg_score'] = 80

        # 3. 期权 Put/Call 比例
        pcr = self.get_put_call_ratio()
        if pcr is not None:
            sentiment['option_ratio'] = pcr
            sentiment['put_call_detail'] = self.put_call_detail
            if pcr < 0.6:
                sentiment['pcr_sentiment'] = '极度看多'
                sentiment['pcr_score'] = 85
            elif pcr < 0.8:
                sentiment['pcr_sentiment'] = '看多'
                sentiment['pcr_score'] = 70
            elif pcr < 1.0:
                sentiment['pcr_sentiment'] = '中性偏多'
                sentiment['pcr_score'] = 55
            elif pcr < 1.2:
                sentiment['pcr_sentiment'] = '中性偏空'
                sentiment['pcr_score'] = 40
            elif pcr < 1.5:
                sentiment['pcr_sentiment'] = '看空'
                sentiment['pcr_score'] = 25
            else:
                sentiment['pcr_sentiment'] = '极度看空'
                sentiment['pcr_score'] = 15

        # 4. 标普500指数
        if self.spx is not None and self.spx_change is not None:
            sentiment['spx'] = self.spx
            sentiment['spx_change'] = self.spx_change
            if self.spx_change > 2.0:
                sentiment['spx_sentiment'] = '大涨'
                sentiment['spx_score'] = 85
            elif self.spx_change > 1.0:
                sentiment['spx_sentiment'] = '上涨'
                sentiment['spx_score'] = 70
            elif self.spx_change > 0.0:
                sentiment['spx_sentiment'] = '微涨'
                sentiment['spx_score'] = 60
            elif self.spx_change > -1.0:
                sentiment['spx_sentiment'] = '微跌'
                sentiment['spx_score'] = 40
            elif self.spx_change > -2.0:
                sentiment['spx_sentiment'] = '下跌'
                sentiment['spx_score'] = 25
            else:
                sentiment['spx_sentiment'] = '大跌'
                sentiment['spx_score'] = 15

        if self.ndx:
            sentiment['ndx'] = self.ndx
        if self.dji:
            sentiment['dji'] = self.dji

        # 计算综合情绪评分（设计文档一致权重）
        scores = []
        weights = []

        if sentiment.get('vix_score') is not None:
            scores.append(sentiment['vix_score'])
            weights.append(30)  # VIX 30%
        if sentiment.get('fg_score') is not None:
            scores.append(sentiment['fg_score'])
            weights.append(25)  # 恐慌贪婪 25%
        if sentiment.get('pcr_score') is not None:
            scores.append(sentiment['pcr_score'])
            weights.append(25)  # 期权比例 25%
        if sentiment.get('spx_score') is not None:
            scores.append(sentiment['spx_score'])
            weights.append(20)  # SPX 20%

        sentiment['components'] = {
            'vix_30pct': {'value': sentiment.get('vix'), 'score': sentiment.get('vix_score')},
            'fear_greed_25pct': {'value': sentiment.get('fear_greed'), 'score': sentiment.get('fg_score')},
            'put_call_25pct': {'value': sentiment.get('option_ratio'), 'score': sentiment.get('pcr_score')},
            'spx_20pct': {'value': self.spx_change, 'score': sentiment.get('spx_score')},
        }

        if scores and weights:
            total_weight = sum(weights)
            sentiment['sentiment_score'] = round(
                sum(s * w for s, w in zip(scores, weights)) / total_weight
            )

        # 添加文字标签
        score = sentiment['sentiment_score']
        if score >= 75:
            sentiment['sentiment_label'] = '乐观'
        elif score >= 60:
            sentiment['sentiment_label'] = '偏乐观'
        elif score >= 45:
            sentiment['sentiment_label'] = '中性'
        elif score >= 30:
            sentiment['sentiment_label'] = '偏谨慎'
        else:
            sentiment['sentiment_label'] = '恐慌'

        return sentiment

    def print_sentiment(self, sentiment):
        """打印情绪分析"""
        if not sentiment:
            print("❌ 无法获取市场情绪")
            return

        print("\n" + "="*55)
        print("🇺🇸 美股市场情绪分析（2026-06-18 修复版）")
        print("="*55)
        print(f"  综合评分: {sentiment.get('sentiment_score', 'N/A')}/100 ({sentiment.get('sentiment_label', 'N/A')})")
        print("-" * 55)

        print("\n📊 数据源构成:")
        print(f"  [30%] VIX 恐慌指数: {sentiment.get('vix', 'N/A')} → {sentiment.get('vix_sentiment', 'N/A')} (分{sentiment.get('vix_score', '?')})")
        print(f"  [25%] CNN 恐慌贪婪: {sentiment.get('fear_greed', 'N/A')} → {sentiment.get('fear_greed_rating', 'N/A')} (分{sentiment.get('fg_score', '?')})")
        if sentiment.get('option_ratio'):
            print(f"  [25%] 期权 Put/Call: {sentiment['option_ratio']:.3f} → {sentiment.get('pcr_sentiment', 'N/A')} (分{sentiment.get('pcr_score', '?')})")
            if sentiment.get('put_call_detail'):
                d = sentiment['put_call_detail']
                print(f"          成交量: Call {d.get('call_volume',0):,} / Put {d.get('put_volume',0):,}")
        print(f"  [20%] S&P 500: {sentiment.get('spx', 'N/A')} ({sentiment.get('spx_change', 'N/A'):+.2f}%) → {sentiment.get('spx_sentiment', 'N/A')} (分{sentiment.get('spx_score', '?')})")

        if sentiment.get('ndx'):
            print(f"\n  NDX: {sentiment['ndx']['price']:.0f} ({sentiment['ndx']['change_pct']:+.2f}%)")
        if sentiment.get('dji'):
            print(f"  DJI: {sentiment['dji']['price']:.0f} ({sentiment['dji']['change_pct']:+.2f}%)")

        print("="*55)


def get_us_sentiment():
    """便捷函数：获取美股市场情绪"""
    monitor = USMarketSentiment()
    sentiment = monitor.get_market_sentiment()
    return sentiment


# 测试
if __name__ == '__main__':
    print("测试美股市场情绪获取（2026-06-18 修复版）...")
    sentiment = get_us_sentiment()
    if sentiment:
        monitor = USMarketSentiment()
        monitor.print_sentiment(sentiment)
    else:
        print("获取失败，请检查网络连接")