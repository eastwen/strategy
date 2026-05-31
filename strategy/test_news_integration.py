#!/usr/bin/env python3
"""测试新闻整合效果"""
import json
import sqlite3
from datetime import datetime

def test_news_integration():
    """测试新闻整合"""
    print("🧪 测试新闻整合系统")
    print("=" * 50)
    
    # 1. 检查数据库
    db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查新闻表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='news';")
        if cursor.fetchone():
            print("✅ 新闻数据库正常")
            
            # 统计新闻数量
            cursor.execute("SELECT COUNT(*) FROM news WHERE date(timestamp) = date('now')")
            count = cursor.fetchone()[0]
            print(f"   今日新闻: {count} 条")
            
            # 查看最新新闻
            cursor.execute("SELECT source, title FROM news ORDER BY timestamp DESC LIMIT 3")
            for source, title in cursor.fetchall():
                print(f"   - [{source}] {title[:50]}...")
        else:
            print("❌ 新闻表不存在")
        
        conn.close()
    except Exception as e:
        print(f"❌ 数据库错误: {e}")
    
    # 2. 检查交易机会
    opp_file = '/home/admin/.openclaw/workspace-stock/data/opportunities.json'
    try:
        with open(opp_file, 'r') as f:
            data = json.load(f)
        
        opportunities = data.get('opportunities', [])
        print(f"\n✅ 交易机会文件正常")
        print(f"   机会数量: {len(opportunities)} 个")
        
        # 检查是否有新闻调整
        has_news_adjustment = any('news_adjusted_score' in o for o in opportunities)
        if has_news_adjustment:
            print("   已整合新闻调整 ✅")
            
            # 显示调整最大的机会
            sorted_opps = sorted(opportunities, 
                               key=lambda x: abs(x.get('news_adjustment', 0)), 
                               reverse=True)
            
            print("\n📊 新闻调整最大的机会:")
            for o in sorted_opps[:3]:
                symbol = o.get('symbol', '')
                score = o.get('score', 0)
                adj = o.get('news_adjusted_score', 0)
                adjustment = o.get('news_adjustment', 0)
                reason = o.get('news_reason', '')
                
                if abs(adjustment) > 0.1:
                    arrow = "↑" if adjustment > 0 else "↓"
                    print(f"   {symbol}: {score:.1f} → {adj:.1f} ({arrow}{abs(adjustment):.1f})")
                    print(f"     原因: {reason[:60]}...")
        else:
            print("   未整合新闻调整 ⚠️")
            
    except Exception as e:
        print(f"❌ 交易机会文件错误: {e}")
    
    # 3. 模拟新闻影响
    print("\n🎯 模拟新闻影响分析:")
    
    sample_symbols = ['AAPL', 'TSLA', 'NVDA', 'AMZN', 'META']
    for symbol in sample_symbols:
        # 模拟新闻影响
        impact_score = 0.5 + (ord(symbol[0]) % 10) / 50  # 简单模拟
        adjustment = (impact_score - 0.5) * 15  # 放大到±15分
        
        if abs(adjustment) > 3:
            arrow = "↑" if adjustment > 0 else "↓"
            sentiment = "看涨" if adjustment > 0 else "看跌"
            print(f"   {symbol}: 模拟{sentiment}新闻，评分{arrow}{abs(adjustment):.1f}分")
    
    print("\n" + "=" * 50)
    print("✅ 测试完成")
    
    # 4. 建议下一步
    print("\n🎯 建议立即执行:")
    print("1. 运行 python3 simple_chinese_news.py 获取今日新闻")
    print("2. 运行 python3 news_integration.py --update 更新机会")
    print("3. 将新闻任务添加到定时任务")

if __name__ == "__main__":
    test_news_integration()