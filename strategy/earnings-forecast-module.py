#!/usr/bin/env python3
"""
财报预测模块 - EPS/营收预测
数据来源: Finnhub, Yahoo Finance
预测内容: 财报日期, EPS预期, 营收增速, 超预期概率, 股价影响预期
"""

import sys
import json
import requests
import time
from datetime import datetime, timedelta

class EarningsForecastModule:
    """财报预测分析器"""
    
    def __init__(self):
        self.load_config()
        self.earnings_cache = {}
        
    def load_config(self):
        with open('/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json', 'r') as f:
            keys = json.load(f)
        self.finnhub_key = keys['finnhub']['api_key']
    
    def get_earnings_calendar(self, symbol):
        """
        获取财报日历
        
        Args:
            symbol: 股票代码 (如 'NVDA')
        
        Returns:
            {
                'date': '2026-04-25',
                'eps_estimate': 0.72,
                'revenue_estimate': 28500000000,
                'eps_actual': None,  # 未公布时为None
                'surprise_percent': None
            }
        """
        # Finnhub API获取财报日历
        url = f"https://finnhub.io/api/v1/calendar/earnings"
        params = {
            'symbol': symbol,
            'from': (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
            'to': (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d'),
            'token': self.finnhub_key
        }
        
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                earnings = data.get('earningsCalendar', [])
                
                if earnings:
                    # 获取最近的财报
                    next_earning = earnings[0]
                    return {
                        'date': next_earning.get('date'),
                        'eps_estimate': next_earning.get('epsEstimate'),
                        'revenue_estimate': next_earning.get('revenueEstimate'),
                        'eps_actual': next_earning.get('epsActual'),
                        'surprise_percent': next_earning.get('surprisePercent'),
                        'hour': next_earning.get('hour')  # bmo(盘前), amc(盘后)
                    }
            return None
        except Exception as e:
            print(f"❌ 获取财报日历失败 {symbol}: {e}")
            return None
    
    def get_historical_earnings(self, symbol, years=2):
        """
        获取历史财报数据，计算超预期率
        
        Args:
            symbol: 股票代码
            years: 查询年数
        
        Returns:
            {
                'total_reports': 8,
                'beat_count': 6,
                'miss_count': 2,
                'beat_rate': 0.75,
                'avg_surprise': 0.05
            }
        """
        url = f"https://finnhub.io/api/v1/stock/earnings"
        params = {
            'symbol': symbol,
            'token': self.finnhub_key
        }
        
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                
                total = len(data)
                beat_count = sum(1 for d in data if d.get('surprisePercent', 0) > 0)
                miss_count = total - beat_count
                
                avg_surprise = sum(d.get('surprisePercent', 0) for d in data) / total if total > 0 else 0
                
                return {
                    'total_reports': total,
                    'beat_count': beat_count,
                    'miss_count': miss_count,
                    'beat_rate': beat_count / total if total > 0 else 0,
                    'avg_surprise': avg_surprise
                }
            return None
        except Exception as e:
            print(f"❌ 获取历史财报失败 {symbol}: {e}")
            return None
    
    def get_revenue_growth_forecast(self, symbol):
        """
        获取营收增速预测
        
        Returns:
            {
                'q1_growth': 0.58,  # Q1同比增长
                'fy_growth': 0.52,  # 财年同比增长
                'sector_avg': 0.35  # 行业平均
            }
        """
        url = f"https://finnhub.io/api/v1/stock/metric"
        params = {
            'symbol': symbol,
            'metric': 'all',
            'token': self.finnhub_key
        }
        
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                metrics = data.get('metric', {})
                
                # 获取营收增速指标
                revenue_growth = metrics.get('revenueGrowth', 0)
                revenue_growth_qoq = metrics.get('revenueGrowthQuarterly', 0)
                
                return {
                    'revenue_growth_yoy': revenue_growth,
                    'revenue_growth_qoq': revenue_growth_qoq,
                    'eps_growth': metrics.get('epsGrowth', 0),
                    'pe_ratio': metrics.get('peBasicExclExtraTTM', 0),
                    'forward_pe': metrics.get('peNormalizedAnnual', 0)
                }
            return None
        except Exception as e:
            print(f"❌ 获取营收预测失败 {symbol}: {e}")
            return None
    
    def predict_stock_impact(self, symbol, earnings_data, historical_data, growth_data):
        """
        预测财报对股价的影响
        
        Returns:
            {
                'impact': 'positive' | 'neutral' | 'negative',
                'confidence': 0.75,
                'reason': '历史超预期率75%，营收增速58%高于行业平均'
            }
        """
        score = 0
        reasons = []
        
        # 1. 历史超预期率 (权重40%)
        if historical_data:
            beat_rate = historical_data.get('beat_rate', 0.5)
            if beat_rate >= 0.75:
                score += 40
                reasons.append(f"历史超预期率{beat_rate*100:.0f}%优秀")
            elif beat_rate >= 0.6:
                score += 25
                reasons.append(f"历史超预期率{beat_rate*100:.0f}%良好")
            elif beat_rate < 0.5:
                score -= 20
                reasons.append(f"历史超预期率{beat_rate*100:.0f}%偏低")
        
        # 2. 营收增速 (权重30%)
        if growth_data:
            revenue_growth = growth_data.get('revenue_growth_yoy', 0)
            if revenue_growth >= 0.5:
                score += 30
                reasons.append(f"营收增速{revenue_growth*100:.0f}%强劲")
            elif revenue_growth >= 0.3:
                score += 15
                reasons.append(f"营收增速{revenue_growth*100:.0f}%稳健")
            elif revenue_growth < 0.1:
                score -= 15
                reasons.append(f"营收增速{revenue_growth*100:.0f}%疲软")
        
        # 3. EPS预期 (权重20%)
        if earnings_data and earnings_data.get('eps_estimate'):
            eps = earnings_data['eps_estimate']
            if eps > 0:
                score += 15
                reasons.append(f"EPS预期${eps:.2f}为正")
            else:
                score -= 10
                reasons.append(f"EPS预期${eps:.2f}为负")
        
        # 4. PE估值 (权重10%)
        if growth_data:
            pe = growth_data.get('pe_ratio', 30)
            forward_pe = growth_data.get('forward_pe', 25)
            if pe < 20 and forward_pe < pe:
                score += 10
                reasons.append("估值合理且前瞻PE下降")
            elif pe > 50:
                score -= 10
                reasons.append(f"估值偏高PE={pe:.1f}")
        
        # 判断影响
        if score >= 50:
            impact = 'positive'
            confidence = min(score / 100, 0.95)
        elif score <= -20:
            impact = 'negative'
            confidence = min(abs(score) / 100, 0.95)
        else:
            impact = 'neutral'
            confidence = 0.6
        
        return {
            'impact': impact,
            'confidence': confidence,
            'score': score,
            'reason': '；'.join(reasons)
        }
    
    def analyze_stock(self, symbol):
        """分析单只股票的财报预期"""
        print(f"\n{'='*60}")
        print(f"📊 分析 {symbol} 财报预期")
        print(f"{'='*60}")
        
        # 1. 获取财报日历
        earnings = self.get_earnings_calendar(symbol)
        if not earnings:
            print(f"❌ 无法获取 {symbol} 财报数据")
            return None
        
        print(f"📅 财报日期: {earnings['date']} ({earnings.get('hour', 'unknown')})")
        print(f"💰 EPS预期: ${earnings.get('eps_estimate', 'N/A')}")
        
        # 2. 获取历史表现
        historical = self.get_historical_earnings(symbol)
        if historical:
            print(f"📈 历史超预期: {historical['beat_count']}/{historical['total_reports']} ({historical['beat_rate']*100:.0f}%)")
            print(f"📊 平均惊喜: {historical['avg_surprise']*100:+.1f}%")
        
        # 3. 获取增长数据
        growth = self.get_revenue_growth_forecast(symbol)
        if growth:
            print(f"🚀 营收增速: {growth.get('revenue_growth_yoy', 0)*100:.0f}% YoY")
            print(f"📊 当前PE: {growth.get('pe_ratio', 0):.1f}")
        
        # 4. 预测影响
        impact = self.predict_stock_impact(symbol, earnings, historical, growth)
        print(f"\n🎯 影响预测: {impact['impact'].upper()} (置信度: {impact['confidence']*100:.0f}%)")
        print(f"📋 理由: {impact['reason']}")
        
        return {
            'symbol': symbol,
            'earnings_date': earnings['date'],
            'eps_estimate': earnings.get('eps_estimate'),
            'revenue_estimate': earnings.get('revenue_estimate'),
            'historical_beat_rate': historical.get('beat_rate') if historical else None,
            'revenue_growth': growth.get('revenue_growth_yoy') if growth else None,
            'impact_prediction': impact['impact'],
            'confidence': impact['confidence'],
            'reason': impact['reason']
        }
    
    def analyze_portfolio(self, symbols=None):
        """分析投资组合的财报预期"""
        if not symbols:
            # 默认分析美股持仓
            try:
                with open('/home/admin/.openclaw/workspace-stock/data/trades-us.json', 'r') as f:
                    data = json.load(f)
                trades = data.get('trades', [])
                symbols = list(set(t['symbol'] for t in trades))
            except:
                symbols = ['NVDA', 'AAPL', 'MSFT', 'AMD', 'META', 'TSLA']
        
        print(f"\n{'='*60}")
        print(f"📊 投资组合财报分析 - {len(symbols)}只股票")
        print(f"{'='*60}")
        
        results = []
        for symbol in symbols:
            result = self.analyze_stock(symbol)
            if result:
                results.append(result)
            time.sleep(0.5)  # API限流
        
        # 生成汇总报告
        self.generate_report(results)
        
        return results
    
    def generate_report(self, results):
        """生成财报预测报告"""
        report = f"""
# 📊 财报预测报告
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 📋 个股分析

"""
        
        for r in results:
            impact_emoji = {'positive': '🟢', 'neutral': '🟡', 'negative': '🔴'}
            eps_str = f"${r['eps_estimate']:.2f}" if r['eps_estimate'] else 'N/A'
            beat_str = f"{r['historical_beat_rate']*100:.0f}%" if r['historical_beat_rate'] else 'N/A'
            growth_str = f"{r['revenue_growth']*100:.0f}%" if r['revenue_growth'] else 'N/A'
            report += f"""
### {r['symbol']}
- 📅 财报日期: {r['earnings_date']}
- 💰 EPS预期: {eps_str}
- 📈 历史超预期率: {beat_str}
- 🚀 营收增速: {growth_str}
- {impact_emoji.get(r['impact_prediction'], '⚪')} 影响预测: {r['impact_prediction'].upper()} (置信度: {r['confidence']*100:.0f}%)
- 📋 理由: {r['reason']}

"""
        
        # 保存报告
        with open(f'/home/admin/.openclaw/workspace-stock/data/earnings-forecast-{datetime.now().strftime("%Y%m%d")}.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✅ 财报预测报告已保存")
        return report


def main():
    """主函数"""
    module = EarningsForecastModule()
    
    # 分析美股持仓
    module.analyze_portfolio()


if __name__ == '__main__':
    main()
