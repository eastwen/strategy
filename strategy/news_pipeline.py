#!/usr/bin/env python3
"""资讯管道 - 稳定可用的新闻获取与存储"""
import requests
import json
import re
import time
import os
import subprocess
from datetime import datetime, timedelta
import sqlite3
from typing import List, Dict, Any
import sys

from runtime_config import DATA_DIR, NEWS_DB_PATH, NEWS_DIR, config_path, load_api_keys

# ========== 数据库管理 ==========
class NewsDatabase:
    def __init__(self, db_path=NEWS_DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 新闻表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            url TEXT,
            symbol TEXT,
            sentiment REAL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, title)
        )
        ''')
        
        # 新闻来源统计表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sources_stats (
            date TEXT NOT NULL,
            source TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY(date, source)
        )
        ''')
        
        # 股票提及表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_mentions (
            news_id INTEGER,
            symbol TEXT NOT NULL,
            mentioned_at TEXT NOT NULL,
            FOREIGN KEY(news_id) REFERENCES news(id),
            PRIMARY KEY(news_id, symbol)
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_news(self, news_list: List[Dict[str, Any]]):
        """保存新闻到数据库"""
        # 用于自动提取股票代码
        stock_extractor = StableNewsSources()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        saved_count = 0
        inserted_by_source = {}
        for news in news_list:
            try:
                # 自动提取股票代码（如果原新闻没有提供symbol）
                symbol = news.get('symbol', '')
                if not symbol:
                    extracted = stock_extractor.extract_stocks(news.get('title', ''))
                    if extracted:
                        symbol = extracted[0]  # 取第一个匹配的股票代码
                
                # 插入新闻（OR IGNORE避免UNIQUE约束冲突）
                cursor.execute('''
                INSERT OR IGNORE INTO news (source, title, content, url, symbol, sentiment, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    news['source'],
                    news['title'],
                    news.get('content', ''),
                    news.get('url', ''),
                    symbol,
                    news.get('sentiment', 0.5),
                    news.get('timestamp', datetime.now().isoformat())
                ))
                
                inserted = cursor.rowcount == 1
                if inserted:
                    news_id = cursor.lastrowid
                    saved_count += 1
                    source = news['source']
                    inserted_by_source[source] = inserted_by_source.get(source, 0) + 1
                else:
                    cursor.execute(
                        'SELECT id FROM news WHERE source = ? AND title = ?',
                        (news['source'], news['title'])
                    )
                    existing = cursor.fetchone()
                    news_id = existing[0] if existing else None
                
                # 保存股票提及
                if news_id is not None:
                    for mentioned_symbol in news.get('stocks', []):
                        cursor.execute('''
                        INSERT OR IGNORE INTO stock_mentions (news_id, symbol, mentioned_at)
                        VALUES (?, ?, ?)
                        ''', (news_id, mentioned_symbol, news.get('timestamp', datetime.now().isoformat())))
            except Exception as e:
                print(f"  保存新闻失败: {e}")
                continue
        
        # 来源统计只累计本轮真正新增的新闻，不把被去重的输入重复计数。
        today = datetime.now().strftime('%Y-%m-%d')
        for source, count in inserted_by_source.items():
            cursor.execute('''
            INSERT OR REPLACE INTO sources_stats (date, source, count)
            VALUES (?, ?, COALESCE((SELECT count FROM sources_stats WHERE date = ? AND source = ?), 0) + ?)
            ''', (today, source, today, source, count))
        
        conn.commit()
        conn.close()
        return saved_count
    
    def cleanup_old_news(self, days=15):
        """清理超过N天的旧新闻"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 删除超过15天的新闻
            cursor.execute('''
            DELETE FROM news 
            WHERE timestamp < datetime('now', ?)
            ''', (f'-{days} days',))
            
            deleted = cursor.rowcount
            
            # 同时清理stock_mentions中孤立的记录
            cursor.execute('''
            DELETE FROM stock_mentions 
            WHERE news_id NOT IN (SELECT id FROM news)
            ''')
            
            orphaned = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if deleted > 0 or orphaned > 0:
                print(f"🧹 清理完成: 删除 {deleted} 条旧新闻, {orphaned} 条孤立记录")
            return deleted
        except Exception as e:
            print(f"⚠️ 清理旧新闻失败: {e}")
            return 0
    
    def get_latest_news(self, limit: int = 50):
        """获取最新新闻"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT source, title, content, url, symbol, sentiment, timestamp
        FROM news
        ORDER BY timestamp DESC
        LIMIT ?
        ''', (limit,))
        
        columns = ['source', 'title', 'content', 'url', 'symbol', 'sentiment', 'timestamp']
        news = []
        for row in cursor.fetchall():
            news.append(dict(zip(columns, row)))
        
        conn.close()
        return news
    
    def get_source_stats(self, days: int = 7):
        """获取来源统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        cursor.execute('''
        SELECT date, source, count
        FROM sources_stats
        WHERE date >= ?
        ORDER BY date DESC, count DESC
        ''', (start_date,))
        
        stats = {}
        for date, source, count in cursor.fetchall():
            if date not in stats:
                stats[date] = {}
            stats[date][source] = count
        
        conn.close()
        return stats

# ========== 稳定新闻源 ==========
class StableNewsSources:
    def __init__(self):
        # 加载API密钥
        try:
            API_KEYS = load_api_keys()
            self.FINNHUB_KEY = API_KEYS['finnhub']['api_key']
            self.ALPHA_KEY = API_KEYS['alphavantage']['api_key']
        except:
            self.FINNHUB_KEY = os.getenv('FINNHUB_KEY', '')
            self.ALPHA_KEY = os.getenv('ALPHAVANTAGE_KEY', '')
    
    def fetch_finnhub(self) -> List[Dict[str, Any]]:
        """Finnhub新闻 - 稳定可靠"""
        news = []
        try:
            url = f"https://finnhub.io/api/v1/news?category=general&token={self.FINNHUB_KEY}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                for item in resp.json()[:20]:
                    title = item.get('headline', '')
                    if title:
                        # Finnhub返回related字段，格式如 "AAPL,MSFT,GOOGL"
                        related = item.get('related', '')
                        stocks = []
                        if related:
                            stocks = [s.strip().upper() for s in related.split(',') if s.strip()]
                        if not stocks:
                            stocks = self.extract_stocks(title)
                        news.append({
                            'source': 'Finnhub',
                            'title': title,
                            'content': item.get('summary', ''),
                            'url': item.get('url', ''),
                            'timestamp': datetime.fromtimestamp(item.get('datetime', time.time())).isoformat(),
                            'stocks': stocks[:5],  # 最多5只
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  Finnhub错误: {e}")
        return news
    
    def fetch_cnbc_rss(self) -> List[Dict[str, Any]]:
        """CNBC RSS - 美股主要新闻"""
        news = []
        try:
            # 新版CNBC RSS
            url = "https://www.cnbc.com/id/100003114/device/rss/rss.html"
            resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            
            if resp.status_code == 200:
                # 解析RSS
                titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', resp.text)[:15]
                for title in titles:
                    if title and 'CNBC' not in title:
                        news.append({
                            'source': 'CNBC',
                            'title': title,
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  CNBC错误: {e}")
        return news
    
    def fetch_yahoo_finance_rss(self) -> List[Dict[str, Any]]:
        """雅虎财经RSS - 美股新闻"""
        news = []
        try:
            # Yahoo Finance RSS
            url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"
            resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            
            if resp.status_code == 200:
                titles = re.findall(r'<title>(.*?)</title>', resp.text)[:15]
                for title in titles:
                    if title and 'Yahoo' not in title:
                        news.append({
                            'source': 'Yahoo Finance',
                            'title': title,
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  雅虎财经错误: {e}")
        return news
    
    def fetch_36kr_news(self) -> List[Dict[str, Any]]:
        """36氪 - 国内科技新闻"""
        news = []
        try:
            url = "https://36kr.com/api/newsflash/homepage/get"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://36kr.com'
            }
            resp = requests.get(url, timeout=15, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('data', {}).get('items', [])[:15]
                if not items:
                    items = data.get('data', [])[:15]
                for item in items:
                    if isinstance(item, dict):
                        title = item.get('title', '') or item.get('desc', '')
                        if title:
                            news.append({
                                'source': '36氪',
                                'title': title[:150],
                                'content': '',
                                'url': item.get('route', ''),
                                'timestamp': datetime.now().isoformat(),
                                'stocks': self.extract_stocks(title),
                                'sentiment': self.analyze_sentiment(title)
                            })
        except Exception as e:
            print(f"  36氪错误: {e}")
        return news
    
    def fetch_ithome_news(self) -> List[Dict[str, Any]]:
        """IT之家 - 国内科技新闻"""
        news = []
        try:
            url = "https://www.ithome.com/"
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                titles = re.findall(r'<h2[^>]*><a[^>]*>([^<]+)</a></h2>', resp.text)[:15]
                for title in titles:
                    if title and len(title) > 10:
                        news.append({
                            'source': 'IT之家',
                            'title': title[:150],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  IT之家错误: {e}")
        return news
    
    def fetch_guancha_news(self) -> List[Dict[str, Any]]:
        """观察者网 - 国内军事/时政"""
        news = []
        try:
            url = "https://www.guancha.cn/"
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                titles = re.findall(r'<h3[^>]*><a[^>]*>([^<]+)</a></h3>', resp.text)[:15]
                for title in titles:
                    if title and len(title) > 10:
                        news.append({
                            'source': '观察者网',
                            'title': title[:150],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  观察者网错误: {e}")
        return news
    
    def fetch_ars_news(self) -> List[Dict[str, Any]]:
        """Ars Technica - 国际科技"""
        news = []
        try:
            url = "https://feeds.arstechnica.com/arstechnica/index"
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', resp.text)[:15]
                for title in titles:
                    if title and 'Ars Technica' not in title:
                        news.append({
                            'source': 'Ars Technica',
                            'title': title[:150],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  Ars Technica错误: {e}")
        return news
    
    def fetch_wired_news(self) -> List[Dict[str, Any]]:
        """Wired - 科技新闻"""
        news = []
        try:
            url = "https://www.wired.com/feed/rss"
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', resp.text)[:15]
                for title in titles:
                    if title and 'Wired' not in title:
                        news.append({
                            'source': 'Wired',
                            'title': title[:150],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  Wired错误: {e}")
        return news
    
    def fetch_reuters_tech(self) -> List[Dict[str, Any]]:
        """Google News Tech - 科技新闻（原Reuters源已失效，替换为Google News RSS）"""
        news = []
        try:
            url = "https://news.google.com/rss/search?q=technology+stocks&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            if resp.status_code == 200:
                titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', resp.text)[:15]
                if not titles:
                    titles = re.findall(r'<title>(.*?)</title>', resp.text)[:15]
                for title in titles:
                    if title and 'Google News' not in title:
                        news.append({
                            'source': 'Google News Tech',
                            'title': title[:150],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
        except Exception as e:
            print(f"  Google News Tech错误: {e}")
        return news
    
    def fetch_tushare_news(self) -> List[Dict[str, Any]]:
        """Tushare新闻 - A股/港股新闻"""
        news = []
        try:
            import tushare as ts
            import json
            
            # 加载Tushare token
            try:
                config = load_api_keys()
                token = config.get('tushare', {}).get('token', '')
                
                if not token:
                    print("  Tushare token未配置")
                    return news
                
                ts.set_token(token)
                pro = ts.pro_api()
                
                # 获取最近新闻
                from datetime import datetime, timedelta
                end_date = datetime.now().strftime('%Y%m%d')
                start_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                
                # 尝试news接口
                try:
                    df = pro.news(src='sina', start_date=start_date, end_date=end_date)
                    if df is not None and len(df) > 0:
                        for _, row in df.head(20).iterrows():
                            title = row.get('title', '')
                            if title:
                                news.append({
                                    'source': 'Tushare-新浪',
                                    'title': title,
                                    'content': row.get('content', ''),
                                    'url': row.get('url', ''),
                                    'timestamp': row.get('pub_time', datetime.now().isoformat()),
                                    'stocks': self.extract_stocks(title),
                                    'sentiment': self.analyze_sentiment(title)
                                })
                except:
                    pass
                
                # 尝试major_news接口
                if not news:
                    try:
                        df = pro.major_news(type='public', start_date=start_date, end_date=end_date)
                        if df is not None and len(df) > 0:
                            for _, row in df.head(15).iterrows():
                                title = row.get('title', '')
                                if title:
                                    news.append({
                                        'source': 'Tushare-公告',
                                        'title': title,
                                        'content': row.get('content', ''),
                                        'url': '',
                                        'timestamp': datetime.now().isoformat(),
                                        'stocks': self.extract_stocks(title),
                                        'sentiment': self.analyze_sentiment(title)
                                    })
                    except:
                        pass
                
                if news:
                    print(f"  ✅ Tushare获取 {len(news)} 条")
                else:
                    print("  ⚠️  Tushare无新闻数据")
                    
            except Exception as e:
                print(f"  Tushare加载失败: {e}")
                
        except ImportError:
            print("  ⚠️  Tushare未安装")
        except Exception as e:
            print(f"  Tushare错误: {e}")
        
        return news
    
    def fetch_jin10_news(self) -> List[Dict[str, Any]]:
        """金十数据 - 中文财经资讯龙头"""
        news = []
        
        try:
            print("  尝试金十数据...")
            
            # 金十数据使用WebSocket/API，需要特殊处理
            # 尝试备用RSS接口
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
            
            # 尝试直接抓取网页，提取新闻
            url = 'https://www.jin10.com/'
            resp = requests.get(url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                import re
                # 查找新闻标题 - Jin10网站结构
                # 通常在 <div class="jin-flash-item"> 或类似结构中
                titles = re.findall(r'<span class="jin-content[^"]*">([^<]+)</span>', resp.text)
                
                if not titles:
                    # 备用pattern
                    titles = re.findall(r'"title"\s*:\s*"([^"]+)"', resp.text)
                
                for title in titles[:15]:
                    title = title.strip()
                    if title and len(title) > 10 and 'http' not in title:
                        news.append({
                            'source': '金十数据',
                            'title': title[:150],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
            
            if news:
                print(f"    ✅ 金十数据: {len(news)} 条")
            else:
                print("    ⚠️  金十数据解析失败，尝试备用接口...")
                # 尝试财经库接口
                try:
                    resp2 = requests.get('https://flash-api.jin10.com/get_list?channel=_all&max_id=&category=&count=20', 
                                        headers=headers, timeout=10)
                    if resp2.status_code == 200:
                        import json
                        data = resp2.json()
                        items = data.get('data', []) if isinstance(data, dict) else []
                        for item in items[:15]:
                            title = item.get('title', '') or item.get('data', {}).get('title', '')
                            if title:
                                news.append({
                                    'source': '金十数据',
                                    'title': title[:150],
                                    'content': '',
                                    'url': '',
                                    'timestamp': datetime.now().isoformat(),
                                    'stocks': self.extract_stocks(title),
                                    'sentiment': self.analyze_sentiment(title)
                                })
                        if news:
                            print(f"    ✅ 金十数据(备用): {len(news)} 条")
                except:
                    pass
                
        except Exception as e:
            print(f"    ❌ 金十数据错误: {str(e)[:50]}")
        
        return news
    
    def fetch_eastmoney_news(self) -> List[Dict[str, Any]]:
        """东方财富 - 国内财经资讯"""
        news = []
        
        try:
            print("  尝试东方财富...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }
            
            # 尝试财经新闻首页
            urls = [
                'https://news.eastmoney.com/',
                'https://stock.eastmoney.com/',
            ]
            
            for url in urls:
                try:
                    resp = requests.get(url, headers=headers, timeout=10)
                    # 设置正确的编码
                    resp.encoding = resp.apparent_encoding or 'utf-8'
                    if resp.status_code == 200:
                        import re
                        # 提取标题
                        titles = re.findall(r'<a[^>]*title="([^"]{10,80})"', resp.text)
                        for title in titles[:20]:
                            title = title.strip()
                            if title and len(title) > 15:
                                news.append({
                                    'source': '东方财富',
                                    'title': title[:150],
                                    'content': '',
                                    'url': '',
                                    'timestamp': datetime.now().isoformat(),
                                    'stocks': self.extract_stocks(title),
                                    'sentiment': self.analyze_sentiment(title)
                                })
                        if news:
                            break
                except:
                    continue
            
            if news:
                print(f"    ✅ 东方财富: {len(news)} 条")
            else:
                print("    ⚠️  东方财富无数据")
                
        except Exception as e:
            print(f"    ❌ 东方财富错误: {str(e)[:50]}")
        
        return news
    
    def fetch_sina_news(self) -> List[Dict[str, Any]]:
        """新浪财经 - 国内财经资讯"""
        news = []
        
        try:
            print("  尝试新浪财经...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            urls = [
                'https://finance.sina.com.cn/stock/',
                'https://finance.sina.com.cn/realstock/company/hkstock.shtml',
            ]
            
            for url in urls:
                try:
                    resp = requests.get(url, headers=headers, timeout=10)
                    # 设置正确的编码
                    resp.encoding = resp.apparent_encoding or 'utf-8'
                    if resp.status_code == 200:
                        import re
                        titles = re.findall(r'<a[^>]*title="([^"]{10,80})"', resp.text)
                        for title in titles[:20]:
                            title = title.strip()
                            if title and len(title) > 15:
                                news.append({
                                    'source': '新浪财经',
                                    'title': title[:150],
                                    'content': '',
                                    'url': '',
                                    'timestamp': datetime.now().isoformat(),
                                    'stocks': self.extract_stocks(title),
                                    'sentiment': self.analyze_sentiment(title)
                                })
                        if news:
                            break
                except:
                    continue
            
            if news:
                print(f"    ✅ 新浪财经: {len(news)} 条")
            else:
                print("    ⚠️  新浪财经无数据")
                
        except Exception as e:
            print(f"    ❌ 新浪财经错误: {str(e)[:50]}")
        
        return news
    
    def fetch_hk_news(self) -> List[Dict[str, Any]]:
        """港股新闻 - 港交所、智通财经等"""
        news = []
        
        # 1. 港交所公告RSS
        try:
            print("  尝试港交所RSS...")
            url = "https://www.hkex.com.hk/News/News-Release?sc_lang=zh-HK"
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if resp.status_code == 200:
                # 简单提取标题
                titles = re.findall(r'<a[^>]*>([^<]{20,})</a>', resp.text)
                for title in titles[:15]:
                    title = title.strip()
                    if title and len(title) > 20 and 'HKEX' not in title:
                        news.append({
                            'source': '港交所',
                            'title': title[:100],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
                
                if news:
                    print(f"    ✅ 港交所: {len(news)} 条")
        except Exception as e:
            print(f"    ⚠️  港交所失败: {str(e)[:50]}")
        
        # 2. 智通财经
        try:
            print("  尝试智通财经...")
            url = "https://www.zhitongcaijing.com/"
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if resp.status_code == 200:
                # 提取标题
                titles = re.findall(r'<a[^>]*title="([^"]{20,})"', resp.text)
                for title in titles[:15]:
                    title = title.strip()
                    if title and len(title) > 20:
                        news.append({
                            'source': '智通财经',
                            'title': title[:100],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
                
                if len([n for n in news if n['source'] == '智通财经']) > 0:
                    print(f"    ✅ 智通财经: {len([n for n in news if n['source'] == '智通财经'])} 条")
        except Exception as e:
            print(f"    ⚠️  智通财经失败: {str(e)[:50]}")
        
        # 3. 信报财经
        try:
            print("  尝试信报财经...")
            url = "https://www2.hkej.com/instantnews/current"
            resp = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if resp.status_code == 200:
                # 提取标题
                titles = re.findall(r'<h[0-9][^>]*>([^<]{20,})</h[0-9]>', resp.text)
                for title in titles[:10]:
                    title = title.strip()
                    if title and len(title) > 20:
                        news.append({
                            'source': '信报财经',
                            'title': title[:100],
                            'content': '',
                            'url': '',
                            'timestamp': datetime.now().isoformat(),
                            'stocks': self.extract_stocks(title),
                            'sentiment': self.analyze_sentiment(title)
                        })
                
                hkej_count = len([n for n in news if n['source'] == '信报财经'])
                if hkej_count > 0:
                    print(f"    ✅ 信报财经: {hkej_count} 条")
        except Exception as e:
            print(f"    ⚠️  信报财经失败: {str(e)[:50]}")
        
        return news
    
    def fetch_sec_filings_simple(self) -> List[Dict[str, Any]]:
        """简化版SEC EDGAR获取 - 动态采集持仓股票公告"""
        news = []
        try:
            # 从trades.json获取当前持仓股票
            symbols = self.get_position_symbols()
            
            # 如果没有持仓，使用热门股票
            if not symbols:
                symbols = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'AMZN', 'GOOGL', 'AMD', 'INTC', 'AVGO']
            
            print(f"  📊 SEC EDGAR采集股票: {symbols[:10]}")
            
            for symbol in symbols[:10]:  # 最多采集10只股票
                try:
                    # 使用简化的SEC API
                    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={self.get_cik(symbol)}&type=8-k&dateb=&owner=exclude&start=0&count=5&output=atom"
                    headers = {
                        "User-Agent": "OpenClaw-NewsBot/1.0 (admin@openclaw.ai)",
                        "Accept": "application/atom+xml"
                    }
                    resp = requests.get(url, headers=headers, timeout=10)
                    
                    if resp.status_code == 200:
                        # 解析Atom feed
                        entries = re.findall(r'<entry>(.*?)</entry>', resp.text, re.DOTALL)
                        for entry in entries[:2]:
                            title_match = re.search(r'<title>(.*?)</title>', entry)
                            if title_match:
                                title = title_match.group(1)
                                news.append({
                                    'source': 'SEC EDGAR',
                                    'title': f"{symbol}: {title}",
                                    'content': '',
                                    'url': '',
                                    'symbol': symbol,
                                    'timestamp': datetime.now().isoformat(),
                                    'stocks': [symbol],
                                    'sentiment': 0.5
                                })
                    time.sleep(0.5)
                except:
                    continue
        except Exception as e:
            print(f"  SEC EDGAR错误: {e}")
        return news
    
    def get_position_symbols(self) -> List[str]:
        """获取当前持仓股票列表"""
        try:
            with (DATA_DIR / 'trades.json').open('r', encoding='utf-8') as f:
                data = json.load(f)
            
            symbols = []
            for pos in data.get('positions', []):
                sym = pos.get('symbol', '')
                # 清理股票代码
                sym = sym.replace('US.', '').replace('HK.', '')
                if sym and sym not in symbols:
                    symbols.append(sym)
            
            return symbols
        except:
            return []
    
    def get_cik(self, symbol: str) -> str:
        """获取公司CIK"""
        cik_map = {
            'AAPL': '0000320193',
            'MSFT': '0000789019',
            'GOOGL': '0001652044',
            'AMZN': '0001018724',
            'META': '0001326801',
            'TSLA': '0001318605',
            'NVDA': '0001045810',
            'AMD': '0000002488',
            'VRT': '0001704715'
        }
        return cik_map.get(symbol, '')
    
    # 港股公司名/简称 → 港股代码映射 (2026-06-18 east 修复 BUG 1)
    # 注意：news.db.stock_mentions 的 symbol 不带 HK. 前缀，统一存 5 位数字
    HK_COMPANY_TO_SYMBOL = {
        # 互联网科技
        '腾讯': '00700', '腾讯控股': '00700', 'tencent': '00700',
        '阿里巴巴': '09988', '阿里': '09988', 'alibaba': '09988',
        '美团': '03690', 'meituan': '03690',
        '京东': '09618', 'jd.com': '09618', 'jd集团': '09618',
        '小米': '01810', '小米集团': '01810', 'xiaomi': '01810',
        '快手': '01024', 'kuaishou': '01024',
        '网易': '09999', 'netease': '09999',
        '百度': '09888', 'baidu': '09888',
        '商汤': '00020', 'sensetime': '00020',
        '哔哩哔哩': '09626', 'b站': '09626', 'bilibili': '09626',
        # 金融
        '汇丰': '00005', '汇丰控股': '00005', 'hsbc': '00005',
        '友邦': '01299', '友邦保险': '01299', 'aia': '01299',
        '建设银行': '00939', '建行': '00939',
        '工商银行': '01398', '工行': '01398',
        '中国银行': '03988', '中行': '03988',
        '招商银行': '03968', '招行': '03968',
        '中国平安': '02318', '平安': '02318',
        '香港交易所': '00388', '港交所': '00388',
        # 新能源/汽车
        '比亚迪股份': '01211', '比亚迪': '01211',
        '小鹏汽车': '09868', '小鹏': '09868',
        '蔚来': '09866',
        '理想汽车': '02015', '理想': '02015',
        '吉利汽车': '00175', '吉利': '00175',
        '长城汽车': '02333',
        '宁德时代': '03750',  # CATL 港股
        # 消费
        '李宁': '02331',
        '安踏': '02020', '安踏体育': '02020',
        '蒙牛': '02319', '蒙牛乳业': '02319',
        '海底捞': '06862',
        '农夫山泉': '09633',
        '康师傅': '00322',
        # 医药
        '药明生物': '02269',
        '药明康德': '02359',
        '石药': '01093', '石药集团': '01093',
        '百济神州': '06160',
        '信达生物': '01801',
        # 能源/资源
        '中海油': '00883', '中国海洋石油': '00883',
        '中石油': '00857', '中国石油': '00857',
        '中石化': '00386', '中国石化': '00386',
        # 地产
        '新鸿基': '00016', '新鸿基地产': '00016',
        '长实': '01113', '长实集团': '01113',
        '万科': '02202',  # 万科企业H股
        # 公用事业 / 电信
        '中移动': '00941', '中国移动': '00941',
        '中电信': '00728', '中国电信': '00728',
        '中联通': '00762', '中国联通': '00762',
        '中电': '00002', '中电控股': '00002',
        # 其他常见
        '招金矿业': '01818',
        '紫金矿业': '02899',
        '复星医药': '02196',
        '中信证券': '06030',
        '海螺水泥': '00914',
    }

    # 公司名到股票代码映射
    COMPANY_TO_SYMBOL = {
        'apple': 'AAPL', 'alphabet': 'GOOGL', 'google': 'GOOGL',
        'microsoft': 'MSFT', 'amazon': 'AMZN', 'meta': 'META',
        'facebook': 'META', 'tesla': 'TSLA', 'nvidia': 'NVDA',
        'amd': 'AMD', 'intel': 'INTC', 'qualcomm': 'QCOM',
        'broadcom': 'AVGO', 'cisco': 'CSCO', 'oracle': 'ORCL',
        'salesforce': 'CRM', 'servicenow': 'NOW', 'adobe': 'ADBE',
        'micron': 'MU', 'western digital': 'WDC', 'seagate': 'STX',
        'nike': 'NKE', 'visa': 'V', 'mastercard': 'MA',
        'paypal': 'PYPL', 'square': 'SQ', 'stripe': 'STRIPE',
        'uber': 'UBER', 'lyft': 'LYFT', 'airbnb': 'ABNB',
        'spotify': 'SPOT', 'netflix': 'NFLX', 'disney': 'DIS',
        'jpmorgan': 'JPM', 'bank of america': 'BAC', 'goldman': 'GS',
        'wells fargo': 'WFC', 'citigroup': 'C', 'american express': 'AXP',
        'costco': 'COST', 'walmart': 'WMT', 'target': 'TGT',
        'home depot': 'HD', 'lowes': 'LOW', 'starbucks': 'SBUX',
        'mcdonald': 'MCD', 'coca-cola': 'KO', 'pepsi': 'PEP',
        'nvidia': 'NVDA', 'arm': 'ARM', 'supermicro': 'SMCI',
        '台积电': 'TSM', 'tsmc': 'TSM',
        '小鹏': 'XPEV', '蔚来': 'NIO', '理想': 'LI',
        '比亚迪': 'BYD', '宁德时代': 'CATL',
    }
    
    # 常见美股代码（用于从标题中直接匹配纯代码）
    COMMON_TICKERS = {
        'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'TSLA', 'NVDA',
        'AMD', 'INTC', 'QCOM', 'AVGO', 'CSCO', 'ORCL', 'CRM', 'NOW',
        'ADBE', 'MU', 'WDC', 'STX', 'NKE', 'V', 'MA', 'PYPL', 'SQ',
        'UBER', 'LYFT', 'ABNB', 'SPOT', 'NFLX', 'DIS', 'JPM', 'BAC',
        'GS', 'WFC', 'C', 'AXP', 'COST', 'WMT', 'TGT', 'HD', 'LOW',
        'SBUX', 'MCD', 'KO', 'PEP', 'ARM', 'SMCI', 'TSM', 'XPEV',
        'NIO', 'LI', 'BYD', 'CATL', 'HOOD', 'PLTR', 'SNOW', 'CRWD',
        'PANW', 'NET', 'DDOG', 'MDB', 'ZS', 'CRWD', 'MRVL', 'ON',
        'LLY', 'UNH', 'JNJ', 'PFE', 'MRK', 'ABT', 'TMO', 'ISRG',
        'CAT', 'DE', 'BA', 'GE', 'HON', 'RTX', 'LMT', 'NOC',
    }
    
    def extract_stocks(self, text: str) -> List[str]:
        """提取股票代码（美股 + 港股 5 位数字代码）

        2026-06-18 east 修复 BUG 1：补充港股识别
        - 港股代码统一存裸 5 位数字（不带 HK. 前缀），与美股保持一致
        - 识别来源：HK.xxxxx / xxxxx.HK / (xxxxx.HK) / 港股公司名
        """
        if not text:
            return []
        stocks = []
        text_lower = text.lower()

        # === 美股 ===
        # 美股代码格式 ($SYMBOL)
        stocks.extend(re.findall(r'\$([A-Z]{1,5})\b', text))
        # 公司名匹配
        for name, symbol in self.COMPANY_TO_SYMBOL.items():
            if name in text_lower:
                stocks.append(symbol)
        # 纯代码匹配（标题中直接出现的ticker如"AVGO surged"）
        for word in re.findall(r'\b([A-Z]{2,5})\b', text):
            if word in self.COMMON_TICKERS and word not in stocks:
                stocks.append(word)

        # === 港股 (5 位数字, 不带前缀) ===
        # 有效港股正股范围: 00001-09999 (主板正股) | 80000-89999 (指数/ETF)
        # 1xxxx-7xxxx 是窝轮/牛熊证/结构化产品，不计入
        def _is_valid_hk(code: str) -> bool:
            if not code.isdigit() or not (4 <= len(code) <= 5):
                return False
            n = int(code)
            return (1 <= n <= 9999) or (80000 <= n <= 89999)

        hk_candidates = []
        # 1) HK.00700 / HK.700  → 标准化为 5 位
        for m in re.findall(r'HK[.\-]\s*(\d{1,5})', text, re.IGNORECASE):
            hk_candidates.append(m)
        # 2) 00700.HK / 0700.HK / (00700.HK)  → 5 位
        for m in re.findall(r'\b(\d{1,5})\s*\.\s*HK\b', text, re.IGNORECASE):
            hk_candidates.append(m)
        # 3) 港股代码常见写法："港股00700" / "港股代码：00700" / "（00700）"
        for m in re.findall(r'(?:港股|代码[:：]?|（|\()\s*(\d{4,5})\s*(?:）|\)|HK)?', text):
            hk_candidates.append(m)
        # 过滤 + 统一補 0
        for m in hk_candidates:
            if _is_valid_hk(m):
                stocks.append(m.zfill(5))
        # 4) 港股公司名匹配
        for name, symbol in self.HK_COMPANY_TO_SYMBOL.items():
            if name in text_lower or name in text:  # 中文不区分大小写
                stocks.append(symbol)

        # 去重 + 限制数量
        seen = set()
        result = []
        for s in stocks:
            if s and s not in seen:
                seen.add(s)
                result.append(s)
        return result[:8]
    
    # ===== 情绪关键词词典 (v2 - 2026-06-16 扩词典) =====
    # 英文使用 \b 词边界正则，避免 "cut" 误匹配 "execute"、"up" 误匹配 "support" 等
    # 中文用 substring 匹配（中文无词边界）
    BULLISH_EN = [
        'bull', 'bullish', 'rise', 'rises', 'rising', 'rose',
        'up', 'gain', 'gains', 'gained', 'positive', 'beat', 'beats',
        'surge', 'surges', 'surged', 'soar', 'soars', 'soared',
        'jump', 'jumps', 'jumped', 'rally', 'rallies', 'rallied',
        'upgrade', 'upgraded', 'breakout', 'record', 'high', 'highs',
        'outperform', 'buyback', 'partnership', 'approval', 'approved',
    ]
    BEARISH_EN = [
        'bear', 'bearish', 'drop', 'drops', 'dropped',
        'down', 'loss', 'losses', 'negative', 'miss', 'misses', 'missed',
        'fall', 'falls', 'fell', 'decline', 'declines', 'declined',
        # ↓↓↓ 2026-06-16 新增利空词 ↓↓↓
        'sell', 'sells', 'sold', 'cut', 'cuts',
        'downgrade', 'downgraded', 'probe', 'probes',
        'lawsuit', 'sue', 'sues', 'sued',
        'warn', 'warns', 'warned', 'warning',
        'recall', 'recalls', 'recalled',
        'layoff', 'layoffs', 'fraud', 'investigation',
        'bankruptcy', 'bankrupt', 'crash', 'plunge', 'plunges',
        'slump', 'slumps', 'tumble', 'tumbles',
    ]
    BULLISH_CN = [
        '上涨', '大涨', '飙升', '走高', '突破', '创新高', '反弹',
        '利好', '增持', '回购', '上调', '超预期', '看多', '看涨',
        '强劲', '盈利', '扭亏', '中标', '获批',
    ]
    BEARISH_CN = [
        '下跌', '大跌', '跳水',
        # ↓↓↓ 2026-06-16 新增中文利空词 ↓↓↓
        '利空', '下调', '警示', '暴跌', '亏损', '裁员', '调查', '违规',
        '减持', '看空', '看跌', '诉讼', '处罚', '退市', '停牌',
        '腰斩', '跌停', '低于预期', '不及预期', '召回', '欺诈',
    ]

    def analyze_sentiment(self, text: str) -> float:
        """情绪分析 (v2: 词边界匹配 + 中英文双词典)

        英文用 \b...\b 词边界，避免 substring 误判（cut/execute, up/support 等）。
        中文直接 substring，因为中文无词边界。
        """
        if not text:
            return 0.5

        text_lower = text.lower()

        # 英文：词边界匹配
        bullish = sum(1 for w in self.BULLISH_EN if re.search(r'\b' + re.escape(w) + r'\b', text_lower))
        bearish = sum(1 for w in self.BEARISH_EN if re.search(r'\b' + re.escape(w) + r'\b', text_lower))

        # 中文：substring 匹配
        bullish += sum(1 for w in self.BULLISH_CN if w in text)
        bearish += sum(1 for w in self.BEARISH_CN if w in text)

        total = bullish + bearish
        if total == 0:
            return 0.5

        return round(bullish / total, 2)

# ========== 定时任务管理器 ==========
class NewsScheduler:
    def __init__(self):
        self.db = NewsDatabase()
        self.sources = StableNewsSources()
    
    def run_daily_fetch(self):
        """执行每日新闻获取"""
        print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 开始执行新闻获取...")
        
        all_news = []
        
        # 获取所有渠道新闻
        print("📡 获取Finnhub新闻...")
        finnhub_news = self.sources.fetch_finnhub()
        print(f"  ✅ 获取 {len(finnhub_news)} 条")
        all_news.extend(finnhub_news)
        
        print("📡 获取CNBC新闻...")
        cnbc_news = self.sources.fetch_cnbc_rss()
        print(f"  ✅ 获取 {len(cnbc_news)} 条")
        all_news.extend(cnbc_news)
        
        print("📡 获取雅虎财经新闻...")
        yahoo_news = self.sources.fetch_yahoo_finance_rss()
        print(f"  ✅ 获取 {len(yahoo_news)} 条")
        all_news.extend(yahoo_news)
        
        print("📡 获取36氪新闻...")
        kr36_news = self.sources.fetch_36kr_news()
        print(f"  ✅ 获取 {len(kr36_news)} 条")
        all_news.extend(kr36_news)
        
        print("📡 获取IT之家新闻...")
        ithome_news = self.sources.fetch_ithome_news()
        print(f"  ✅ 获取 {len(ithome_news)} 条")
        all_news.extend(ithome_news)
        
        print("📡 获取观察者网新闻...")
        guancha_news = self.sources.fetch_guancha_news()
        print(f"  ✅ 获取 {len(guancha_news)} 条")
        all_news.extend(guancha_news)
        
        print("📡 获取Ars Technica新闻...")
        ars_news = self.sources.fetch_ars_news()
        print(f"  ✅ 获取 {len(ars_news)} 条")
        all_news.extend(ars_news)
        
        print("📡 获取Wired新闻...")
        wired_news = self.sources.fetch_wired_news()
        print(f"  ✅ 获取 {len(wired_news)} 条")
        all_news.extend(wired_news)
        
        print("📡 获取Reuters Tech新闻...")
        reuters_news = self.sources.fetch_reuters_tech()
        print(f"  ✅ 获取 {len(reuters_news)} 条")
        all_news.extend(reuters_news)
        
        print("📡 获取Tushare新闻...")
        tushare_news = self.sources.fetch_tushare_news()
        print(f"  ✅ 获取 {len(tushare_news)} 条")
        all_news.extend(tushare_news)
        
        print("📡 获取金十数据...")
        jin10_news = self.sources.fetch_jin10_news()
        print(f"  ✅ 获取 {len(jin10_news)} 条")
        all_news.extend(jin10_news)
        
        print("📡 获取东方财富...")
        eastmoney_news = self.sources.fetch_eastmoney_news()
        print(f"  ✅ 获取 {len(eastmoney_news)} 条")
        all_news.extend(eastmoney_news)
        
        print("📡 获取新浪财经...")
        sina_news = self.sources.fetch_sina_news()
        print(f"  ✅ 获取 {len(sina_news)} 条")
        all_news.extend(sina_news)
        
        print("📡 获取港股新闻...")
        hk_news = self.sources.fetch_hk_news()
        print(f"  ✅ 获取 {len(hk_news)} 条")
        all_news.extend(hk_news)
        
        print("📡 获取SEC EDGAR公告...")
        sec_news = self.sources.fetch_sec_filings_simple()
        print(f"  ✅ 获取 {len(sec_news)} 条")
        all_news.extend(sec_news)
        
        # 保存到数据库
        print(f"\n💾 保存到数据库...")
        saved = self.db.save_news(all_news)
        print(f"  ✅ 保存 {saved} 条新新闻")
        
        # 统计
        source_counts = {}
        for n in all_news:
            source = n['source']
            source_counts[source] = source_counts.get(source, 0) + 1
        
        print("\n📊 来源统计:")
        for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {source}: {count}条")
        
        # 情绪统计
        bullish = sum(1 for n in all_news if n.get('sentiment', 0.5) > 0.6)
        bearish = sum(1 for n in all_news if n.get('sentiment', 0.5) < 0.4)
        neutral = len(all_news) - bullish - bearish
        
        print(f"\n📈 情绪分析:")
        print(f"  看涨: {bullish}条 ({bullish/len(all_news)*100:.1f}%)")
        print(f"  中性: {neutral}条 ({neutral/len(all_news)*100:.1f}%)")
        print(f"  看跌: {bearish}条 ({bearish/len(all_news)*100:.1f}%)")
        
        # 保存摘要文件
        self.save_summary(all_news)
        
        # 清理超过15天的旧新闻
        print(f"\n🧹 清理超过15天的旧新闻...")
        deleted = self.db.cleanup_old_news(days=15)
        if deleted > 0:
            print(f"  ✅ 已清理 {deleted} 条旧新闻")
        else:
            print(f"  ℹ️ 没有超过15天的旧新闻需要清理")
        
        # 同步警报到alerts.json（用于心跳检查）
        # 2026-06-18 east 修复 BUG 5：写入具体 symbol 让 "重大利空触发分级减仓" 能够生效
        try:
            import json
            extractor = StableNewsSources()
            alerts = []
            # 1. 全局重要新闻 (使用原逻辑)
            for n in all_news[:50]:
                title = n.get('title', '')
                content = n.get('content', '')
                sentiment = n.get('sentiment', 0.5)
                # 提取 symbol
                syms = extractor.extract_stocks((title or '') + ' ' + (content or '')[:300])
                # 计算重要性
                is_high = (
                    sentiment <= 0.2 or sentiment >= 0.8
                    or any(kw in title for kw in ['重大利空', '重大利好', '人事地震', '调查', '诉讼',
                                                   '召回', '减持', '裁员', '欺诈', '退市', '停牌',
                                                   '超预期', '全面发布'])
                    or any(kw in title.lower() for kw in ['lawsuit', 'probe', 'recall', 'fraud',
                                                          'bankruptcy', 'crash', 'plunge'])
                )
                importance = '高' if is_high else '中'
                # 重大利空识别
                is_negative_major = (
                    is_high and sentiment <= 0.3
                    and any(kw in title for kw in ['重大利空', '被调查', '诉讼', '缚费', '警示',
                                                   '欺诈', '退市', '裁员', '下调', '低于预期'])
                )
                alert_type = '重大利空' if is_negative_major else '重大利好' if (is_high and sentiment >= 0.7) else '新闻'
                if syms:
                    # 有个股命中，为每个 symbol 各存一条
                    for sym in syms[:3]:  # 最多取前 3 个 symbol
                        alerts.append({
                            'symbol': sym,
                            'title': title,
                            'source': n.get('source', ''),
                            'sentiment': sentiment,
                            'timestamp': n.get('timestamp', datetime.now().isoformat()),
                            'importance': importance,
                            'alert_type': alert_type,
                        })
                else:
                    # 没命中个股记录为市场新闻 (只抽高重要性的记录)
                    if is_high:
                        alerts.append({
                            'symbol': '',
                            'title': title,
                            'source': n.get('source', ''),
                            'sentiment': sentiment,
                            'timestamp': n.get('timestamp', datetime.now().isoformat()),
                            'importance': importance,
                            'alert_type': alert_type,
                        })
            
            # 限制总数为 100 条（有 symbol 优先）
            alerts.sort(key=lambda a: (0 if a.get('symbol') else 1, 0 if a.get('importance')=='高' else 1))
            alerts = alerts[:100]

            data = {
                'time': datetime.now().isoformat(),
                'source': 'news_integration',
                'alerts': alerts
            }
            
            with (DATA_DIR / 'alerts.json').open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            sym_count = sum(1 for a in alerts if a.get('symbol'))
            print(f"\n🔔 已同步 {len(alerts)} 条警报到 alerts.json (个股命中 {sym_count} 条)")
        except Exception as e:
            print(f"\n⚠️  同步警报失败: {e}")
        
        return all_news
    
    def save_summary(self, news_list):
        """保存摘要文件"""
        try:
            date_str = datetime.now().strftime('%Y-%m-%d')
            summary_path = NEWS_DIR / f'summary_{date_str}.md'
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(f"# 新闻摘要 {date_str}\n\n")
                f.write(f"**获取时间:** {datetime.now().strftime('%H:%M:%S')}\n")
                f.write(f"**总条数:** {len(news_list)}\n\n")
                
                # 按来源分组
                news_by_source = {}
                for n in news_list:
                    source = n['source']
                    if source not in news_by_source:
                        news_by_source[source] = []
                    news_by_source[source].append(n)
                
                for source, items in sorted(news_by_source.items()):
                    f.write(f"## {source} ({len(items)}条)\n\n")
                    for i, n in enumerate(items[:10], 1):
                        sentiment_emoji = '📈' if n.get('sentiment', 0.5) > 0.6 else '📉' if n.get('sentiment', 0.5) < 0.4 else '📊'
                        stocks_str = f" ({', '.join(n.get('stocks', []))})" if n.get('stocks') else ""
                        f.write(f"{i}. {sentiment_emoji} {n['title'][:100]}{stocks_str}\n")
                    f.write("\n")
            
            print(f"📝 摘要已保存到: {summary_path}")
        except Exception as e:
            print(f"  ❌ 保存摘要失败: {e}")
    
    def create_cron_job(self):
        """创建定时任务"""
        cron_content = f'''# 新闻获取定时任务
# 每日执行4次：开盘前、盘中、收盘后、深夜
0 8 * * * cd {os.path.dirname(__file__)} && {sys.executable} {__file__} --schedule=premarket
30 12 * * * cd {os.path.dirname(__file__)} && {sys.executable} {__file__} --schedule=midday
0 16 * * * cd {os.path.dirname(__file__)} && {sys.executable} {__file__} --schedule=postmarket
30 22 * * * cd {os.path.dirname(__file__)} && {sys.executable} {__file__} --schedule=night

# 每周六生成周报
0 10 * * 6 cd {os.path.dirname(__file__)} && {sys.executable} {__file__} --report=weekly
'''
        
        cron_file = config_path('news_cron.txt')
        with open(cron_file, 'w', encoding='utf-8') as f:
            f.write(cron_content)
        
        print(f"⏰ 定时任务配置已保存到: {cron_file}")
        print("\n要安装定时任务，请运行:")
        print(f"crontab {cron_file}")

# ========== 主函数 ==========
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='新闻管道系统')
    parser.add_argument('--schedule', choices=['premarket', 'midday', 'postmarket', 'night'], 
                       help='定时任务类型')
    parser.add_argument('--report', choices=['daily', 'weekly'], help='生成报告')
    parser.add_argument('--test', action='store_true', help='测试模式')
    parser.add_argument('--cron', action='store_true', help='定时任务模式（非交互）')
    args = parser.parse_args()
    
    scheduler = NewsScheduler()
    
    if args.test:
        print("🧪 测试模式...")
        news = scheduler.run_daily_fetch()
        print(f"\n✅ 测试完成，获取 {len(news)} 条新闻")
        
        # 显示最新10条
        print("\n📰 最新10条新闻:")
        latest = scheduler.db.get_latest_news(10)
        for i, n in enumerate(latest, 1):
            source = n['source']
            title = n['title'][:80] + '...' if len(n['title']) > 80 else n['title']
            sentiment = n['sentiment']
            sentiment_str = f"{'📈' if sentiment > 0.6 else '📉' if sentiment < 0.4 else '📊'} {sentiment:.2f}"
            print(f"{i:2d}. [{source:15s}] {title} {sentiment_str}")
    
    elif args.report:
        if args.report == 'weekly':
            print("📊 生成周报...")
            # TODO: 生成周报
            pass
    elif args.cron:
        # 定时任务模式：只执行采集，不交互
        print(f"🚀 新闻管道系统启动（定时任务） - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        scheduler.run_daily_fetch()
        print(f"\n✅ 定时任务完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        # 正常执行
        print(f"🚀 新闻管道系统启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        scheduler.run_daily_fetch()
        
        if not args.schedule:
            # 交互模式，显示选项
            print("\n🔧 可用选项:")
            print("1. 创建定时任务配置")
            print("2. 查看最新新闻")
            print("3. 查看来源统计")
            
            choice = input("\n请选择 (1-3): ").strip()
            if choice == '1':
                scheduler.create_cron_job()
            elif choice == '2':
                latest = scheduler.db.get_latest_news(20)
                print("\n📰 最新20条新闻:")
                for i, n in enumerate(latest, 1):
                    source = n['source']
                    title = n['title'][:70] + '...' if len(n['title']) > 70 else n['title']
                    stocks = n.get('stocks', [])
                    stocks_str = f" 📈{stocks}" if stocks else ""
                    print(f"{i:2d}. [{source:15s}] {title}{stocks_str}")
            elif choice == '3':
                stats = scheduler.db.get_source_stats(3)
                print("\n📊 最近3天来源统计:")
                for date in sorted(stats.keys(), reverse=True):
                    print(f"\n{date}:")
                    for source, count in sorted(stats[date].items(), key=lambda x: x[1], reverse=True):
                        print(f"  {source:20s}: {count:3d}条")

if __name__ == "__main__":
    main()
# 新增对外统一调用接口，兼容现有调用
def fetch_stock_news(symbol, limit=10):
    """对外暴露的拉取股票新闻接口，兼容原有调用"""
    return run_news_pipeline(symbol, limit=limit)

