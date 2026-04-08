#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""新闻与交易策略深度整合系统"""
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any
import sys
import os

class NewsTradingIntegration:
    """新闻与交易策略深度整合"""
    
    def __init__(self):
        self.news_db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
        self.trades_file = '/home/admin/.openclaw/workspace-stock/data/trades.json'
        self.opportunities_file = '/home/admin/.openclaw/workspace-stock/data/opportunities.json'
        
        # 加载策略配置
        self.hk_strategy = self.load_strategy('hk-strategy-v1.0.json')
        self.us_strategy = self.load_strategy('us-strategy-v1.6.json')
    
    def load_strategy(self, filename: str) -> Dict[str, Any]:
        """加载策略配置"""
        try:
            with open(f'/home/admin/.openclaw/workspace-stock/config/{filename}', 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def get_recent_news_for_symbol(self, symbol: str, hours: int = 24) -> List[Dict[str, Any]]:
        """获取某只股票最近N小时的新闻"""
        news = []
        try:
            conn = sqlite3.connect(self.news_db_path)
            cursor = conn.cursor()
            
            # 查询相关新闻
            query = '''
            SELECT source, title, content, sentiment, timestamp 
            FROM news 
            WHERE (title LIKE ? OR content LIKE ? OR symbol = ?)
            AND timestamp >= datetime('now', ?)
            ORDER BY timestamp DESC
            '''
            
            time_filter = f'-{hours} hours'
            cursor.execute(query, (f'%{symbol}%', f'%{symbol}%', symbol, time_filter))
            
            for row in cursor.fetchall():
                news.append({
                    'source': row[0],
                    'title': row[1],
                    'content': row[2],
                    'sentiment': row[3],
                    'timestamp': row[4]
                })
            
            conn.close()
        except Exception as e:
            print(f"❌ 查询新闻失败: {e}")
        
        return news
    
    def get_market_sentiment(self, market: str = 'us', hours: int = 24) -> Dict[str, Any]:
        """获取市场整体情绪"""
        try:
            conn = sqlite3.connect(self.news_db_path)
            cursor = conn.cursor()
            
            # 查询最近N小时的新闻情绪
            query = '''
            SELECT sentiment, COUNT(*) as count
            FROM news 
            WHERE timestamp >= datetime('now', ?)
            AND sentiment IS NOT NULL
            GROUP BY sentiment
            ORDER BY sentiment
            '''
            
            time_filter = f'-{hours} hours'
            cursor.execute(query, (time_filter,))
            
            sentiment_data = cursor.fetchall()
            conn.close()
            
            if not sentiment_data:
                return {'bullish': 0, 'neutral': 0, 'bearish': 0, 'total': 0}
            
            # 计算情绪分布
            total = sum(count for _, count in sentiment_data)
            bullish = sum(count for sentiment, count in sentiment_data if sentiment > 0.6)
            bearish = sum(count for sentiment, count in sentiment_data if sentiment < 0.4)
            neutral = total - bullish - bearish
            
            return {
                'bullish': bullish,
                'neutral': neutral,
                'bearish': bearish,
                'total': total,
                'bullish_percent': (bullish / total * 100) if total > 0 else 0,
                'bearish_percent': (bearish / total * 100) if total > 0 else 0
            }
            
        except Exception as e:
            print(f"❌ 获取市场情绪失败: {e}")
            return {'bullish': 0, 'neutral': 0, 'bearish': 0, 'total': 0}
    
    def analyze_news_impact(self, symbol: str, news_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """分析新闻对股票的影响"""
        if not news_list:
            return {'impact_score': 0, 'sentiment': 0.5, 'news_count': 0, 'recommendation': '中性'}
        
        # 计算平均情绪
        sentiments = [n.get('sentiment', 0.5) for n in news_list if n.get('sentiment') is not None]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.5
        
        # 新闻数量权重
        news_count = len(news_list)
        count_weight = min(news_count / 10, 1.0)  # 最多10条新闻
        
        # 新闻来源权重
        source_weights = {
            'SEC EDGAR': 1.5,    # 官方公告，权重高
            'Finnhub': 1.2,      # 专业财经
            'CNBC': 1.2,
            'Yahoo Finance': 1.0,
            '财联社': 1.3,        # 国内重要财经
            '雪球': 0.8,         # 社区讨论
            'Twitter/X': 0.7,    # 社交媒体
        }
        
        source_score = 0
        for news in news_list:
            source = news.get('source', '')
            weight = source_weights.get(source, 0.5)
            source_score += weight
        
        avg_source_score = source_score / len(news_list) if news_list else 0.5
        
        # 综合影响分数
        impact_score = avg_sentiment * 0.5 + count_weight * 0.3 + avg_source_score * 0.2
        
        # 生成建议
        if impact_score > 0.7:
            recommendation = '强烈看涨'
        elif impact_score > 0.6:
            recommendation = '看涨'
        elif impact_score > 0.4:
            recommendation = '中性'
        elif impact_score > 0.3:
            recommendation = '看跌'
        else:
            recommendation = '强烈看跌'
        
        return {
            'impact_score': round(impact_score, 3),
            'sentiment': round(avg_sentiment, 3),
            'news_count': news_count,
            'source_score': round(avg_source_score, 3),
            'recommendation': recommendation
        }
    
    def adjust_trading_decision(self, symbol: str, original_score: float, market: str = 'us') -> Dict[str, Any]:
        """根据新闻调整交易决策"""
        # 获取相关新闻
        recent_news = self.get_recent_news_for_symbol(symbol, hours=48)
        
        if not recent_news:
            return {
                'original_score': original_score,
                'adjusted_score': original_score,
                'adjustment': 0,
                'reason': '无相关新闻',
                'news_count': 0
            }
        
        # 分析新闻影响
        news_impact = self.analyze_news_impact(symbol, recent_news)
        
        # 根据策略配置调整权重
        strategy_config = self.us_strategy if market == 'us' else self.hk_strategy
        news_weight = 0.3  # 默认权重
        
        if strategy_config:
            if market == 'us':
                # 美股策略中新闻权重
                four_sources = strategy_config.get('four_sources', {})
                if four_sources:
                    news_weight = four_sources.get('weights', {}).get('news', 0.3)
            else:
                # 港股策略中新闻权重
                scoring_weights = strategy_config.get('scoring_weights', {})
                if scoring_weights:
                    news_weight = scoring_weights.get('weights', {}).get('news', 0.3)
        
        # 计算调整
        news_adjustment = (news_impact['impact_score'] - 0.5) * news_weight * 20  # 放大调整
        
        # 限制调整幅度
        max_adjustment = 15  # 最多调整15分
        news_adjustment = max(min(news_adjustment, max_adjustment), -max_adjustment)
        
        adjusted_score = original_score + news_adjustment
        adjusted_score = max(min(adjusted_score, 100), 0)  # 限制在0-100分
        
        return {
            'original_score': round(original_score, 1),
            'adjusted_score': round(adjusted_score, 1),
            'adjustment': round(news_adjustment, 1),
            'reason': f"新闻影响: {news_impact['recommendation']} ({news_impact['impact_score']})",
            'news_count': news_impact['news_count'],
            'news_impact': news_impact
        }
    
    def generate_trading_signals(self, opportunities: List[Dict[str, Any]], market: str = 'us') -> List[Dict[str, Any]]:
        """生成整合新闻的交易信号"""
        enhanced_opportunities = []
        
        for opp in opportunities:
            symbol = opp.get('symbol', '')
            original_score = opp.get('score', 0)
            
            # 根据新闻调整评分
            adjusted_decision = self.adjust_trading_decision(symbol, original_score, market)
            
            # 合并信息
            enhanced_opp = opp.copy()
            enhanced_opp.update({
                'news_adjusted_score': adjusted_decision['adjusted_score'],
                'news_adjustment': adjusted_decision['adjustment'],
                'news_reason': adjusted_decision['reason'],
                'news_count': adjusted_decision['news_count'],
                'news_impact': adjusted_decision.get('news_impact', {})
            })
            
            # 添加新闻摘要
            recent_news = self.get_recent_news_for_symbol(symbol, hours=24)
            if recent_news:
                enhanced_opp['recent_news'] = recent_news[:3]  # 只保留最近3条
            
            enhanced_opportunities.append(enhanced_opp)
        
        # 按调整后评分排序
        enhanced_opportunities.sort(key=lambda x: x.get('news_adjusted_score', 0), reverse=True)
        
        return enhanced_opportunities
    
    def check_news_alerts(self) -> List[Dict[str, Any]]:
        """检查新闻警报（重大新闻、财报等）"""
        alerts = []
        try:
            conn = sqlite3.connect(self.news_db_path)
            cursor = conn.cursor()
            
            # 查询最近2小时的重要新闻
            query = '''
            SELECT source, title, sentiment, timestamp 
            FROM news 
            WHERE timestamp >= datetime('now', '-2 hours')
            AND (title LIKE '%财报%' OR title LIKE '%earnings%' 
                 OR title LIKE '%收购%' OR title LIKE '%merger%'
                 OR title LIKE '%诉讼%' OR title LIKE '%lawsuit%'
                 OR title LIKE '%监管%' OR title LIKE '%regulat%'
                 OR source = 'SEC EDGAR')
            ORDER BY timestamp DESC
            '''
            
            cursor.execute(query)
            
            for source, title, sentiment, timestamp in cursor.fetchall():
                # 判断重要性
                importance = '中等'
                if 'SEC EDGAR' in source or '财报' in title or 'earnings' in title:
                    importance = '高'
                
                alerts.append({
                    'symbol': self.extract_symbol_from_title(title),
                    'title': title,
                    'source': source,
                    'sentiment': sentiment,
                    'timestamp': timestamp,
                    'importance': importance,
                    'alert_type': '新闻'
                })
            
            conn.close()
            
        except Exception as e:
            print(f"❌ 检查新闻警报失败: {e}")
        
        return alerts
    
    def extract_symbol_from_title(self, title: str) -> str:
        """从标题中提取股票代码"""
        # 美股代码
        import re
        us_match = re.search(r'\$([A-Z]{1,5})\b', title)
        if us_match:
            return f"US.{us_match.group(1)}"
        
        # 港股代码
        hk_match = re.search(r'(HK\.\d{5})', title)
        if hk_match:
            return hk_match.group(1)
        
        return ''
    
    def update_opportunities_with_news(self):
        """用新闻信息更新交易机会"""
        try:
            # 加载现有机会
            with open(self.opportunities_file, 'r') as f:
                data = json.load(f)
            
            opportunities = data.get('opportunities', [])
            
            if not opportunities:
                print("⚠️ 无交易机会需要更新")
                return
            
            # 生成整合新闻的交易信号
            enhanced_opportunities = self.generate_trading_signals(opportunities, market='us')
            
            # 保存更新后的机会
            data['opportunities'] = enhanced_opportunities
            data['last_news_update'] = datetime.now().isoformat()
            
            with open(self.opportunities_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ 更新 {len(enhanced_opportunities)} 个交易机会的新闻信息")
            
            # 显示调整最大的机会
            sorted_by_adjustment = sorted(enhanced_opportunities, 
                                        key=lambda x: abs(x.get('news_adjustment', 0)), 
                                        reverse=True)
            
            print("\n📊 新闻调整最大的机会:")
            for opp in sorted_by_adjustment[:5]:
                symbol = opp.get('symbol', '')
                original = opp.get('score', 0)
                adjusted = opp.get('news_adjusted_score', 0)
                adjustment = opp.get('news_adjustment', 0)
                reason = opp.get('news_reason', '')
                
                if abs(adjustment) > 5:  # 只显示调整超过5分的机会
                    arrow = "↑" if adjustment > 0 else "↓"
                    print(f"   {symbol}: {original:.1f} → {adjusted:.1f} ({arrow}{abs(adjustment):.1f}) - {reason}")
            
        except Exception as e:
            print(f"❌ 更新交易机会失败: {e}")
    
    def generate_news_report(self) -> Dict[str, Any]:
        """生成新闻分析报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'market_sentiment': self.get_market_sentiment('us', hours=24),
            'news_alerts': self.check_news_alerts(),
            'top_stocks_news': []
        }
        
        # 获取持仓股票的新闻
        try:
            with open(self.trades_file, 'r') as f:
                trades_data = json.load(f)
            
            positions = trades_data.get('positions', [])
            for position in positions[:10]:  # 最多10个持仓
                symbol = position.get('symbol', '')
                if symbol:
                    news = self.get_recent_news_for_symbol(symbol, hours=24)
                    if news:
                        impact = self.analyze_news_impact(symbol, news)
                        report['top_stocks_news'].append({
                            'symbol': symbol,
                            'news_count': len(news),
                            'news_impact': impact,
                            'latest_news': news[0] if news else None
                        })
        except Exception as e:
            print(f"❌ 获取持仓新闻失败: {e}")
        
        return report
    
    def run_integration_pipeline(self):
        """运行整合管道"""
        print("🚀 新闻与交易策略深度整合")
        print("=" * 60)
        
        # 1. 检查新闻数据库
        if not os.path.exists(self.news_db_path):
            print("❌ 新闻数据库不存在，请先运行新闻获取")
            return
        
        # 2. 更新交易机会
        print("\n1. 📈 更新交易机会的新闻信息...")
        self.update_opportunities_with_news()
        
        # 3. 检查新闻警报
        print("\n2. 🚨 检查新闻警报...")
        alerts = self.check_news_alerts()
        if alerts:
            print(f"   发现 {len(alerts)} 个新闻警报:")
            for alert in alerts[:5]:
                print(f"   - [{alert['importance']}] {alert['symbol']}: {alert['title'][:60]}...")
        else:
            print("   无重大新闻警报")
        
        # 4. 生成市场情绪报告
        print("\n3. 📊 市场情绪分析...")
        sentiment = self.get_market_sentiment('us', hours=24)
        print(f"   过去24小时新闻情绪:")
        print(f"     看涨: {sentiment['bullish']}条 ({sentiment['bullish_percent']:.1f}%)")
        print(f"     中性: {sentiment['neutral']}条")
        print(f"     看跌: {sentiment['bearish']}条 ({sentiment['bearish_percent']:.1f}%)")
        
        # 5. 生成整合报告
        print("\n4. 📋 生成新闻整合报告...")
        report = self.generate_news_report()
        
        # 保存报告
        report_file = '/home/admin/.openclaw/workspace-stock/data/news/news_integration_report.json'
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 整合报告已保存到: {report_file}")
        
        print("\n" + "=" * 60)
        print("🎯 整合完成 - 新闻数据已深度融入交易策略")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='新闻与交易策略深度整合')
    parser.add_argument('--update', action='store_true', help='更新交易机会的新闻信息')
    parser.add_argument('--report', action='store_true', help='生成新闻整合报告')
    parser.add_argument('--alerts', action='store_true', help='检查新闻警报')
    parser.add_argument('--full', action='store_true', help='运行完整整合管道')
    
    args = parser.parse_args()
    
    integration = NewsTradingIntegration()
    
    if args.update:
        integration.update_opportunities_with_news()
    elif args.report:
        report = integration.generate_news_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.alerts:
        alerts = integration.check_news_alerts()
        for alert in alerts:
            print(f"[{alert['importance']}] {alert['symbol']}: {alert['title']}")
    elif args.full:
        integration.run_integration_pipeline()
    else:
        # 交互模式
        print("📰 新闻与交易策略深度整合系统")
        print("=" * 60)
        print("1. 运行完整整合管道")
        print("2. 更新交易机会")
        print("3. 检查新闻警报")
        print("4. 生成新闻报告")
        print("5. 查看市场情绪")
        
        choice = input("\n请选择 (1-5): ").strip()
        
        if choice == '1':
            integration.run_integration_pipeline()
        elif choice == '2':
            integration.update_opportunities_with_news()
        elif choice == '3':
            alerts = integration.check_news_alerts()
            for alert in alerts[:10]:
                print(f"[{alert['importance']}] {alert['symbol']}: {alert['title']}")
        elif choice == '4':
            report = integration.generate_news_report()
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif choice == '5':
            sentiment = integration.get_market_sentiment('us', hours=24)
            print(f"过去24小时市场情绪:")
            print(f"  看涨新闻: {sentiment['bullish']}条")
            print(f"  中性新闻: {sentiment['neutral']}条")
            print(f"  看跌新闻: {sentiment['bearish']}条")
            print(f"  整体偏向: {'看涨' if sentiment['bullish_percent'] > 55 else '看跌' if sentiment['bearish_percent'] > 55 else '中性'}")

if __name__ == "__main__":
    main()