#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
美股扫描器 v2.0
扫描标普500(503只) + 纳斯达克综合指数(3000+只)
数据源：Finnhub（主） / AlphaVantage（备） / 长桥（备）
扫描时间：夜盘、盘前、盘中、盘后
"""

import sys
import os
import json
import time
import requests
from datetime import datetime, date, time as dt_time

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/futu-venv/lib/python3.14/site-packages')

class USScanner:
    """美股扫描器 - 支持备用数据源"""
    
    def __init__(self, scan_limit=None):
        # None表示无限制，扫描所有股票
        self.scan_limit = scan_limit
        self.load_api_keys()
        self.load_stock_pool(limit=self.scan_limit)
        self.load_config()
        self.data_source = 'finnhub'
    
    def load_api_keys(self):
        """加载API密钥"""
        with open('/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json', 'r') as f:
            self.keys = json.load(f)
        
        self.finnhub_key = self.keys.get('finnhub', {}).get('api_key', '')
        self.alphavantage_key = self.keys.get('alphavantage', {}).get('api_key', '')
        self.longbridge_token = self.keys.get('longbridge', {}).get('token', '')
        self.tinkclaw_key = self.keys.get('tinkclaw', {}).get('api_key', '') or os.environ.get('TINKCLAW_API_KEY', '')
    
    def load_stock_pool(self, limit=None):
        """加载美股成分股（标普500 + 纳斯达克综合指数），去重，可限制数量"""
        try:
            # 加载标普500和纳斯达克综合指数
            with open('/home/admin/.openclaw/workspace-stock/strategy/us-index-constituents.json', 'r') as f:
                data = json.load(f)
            
            self.sp500 = data.get('sp500', [])
            self.nasdaq = data.get('nasdaq', [])
            
            # 去重
            unique_symbols = list(dict.fromkeys(self.sp500 + self.nasdaq))
            
            # 如果有限制，使用分层抽样；否则加载所有股票
            if limit and limit > 0 and len(unique_symbols) > limit:
                print(f"⚠️  限制扫描数量: {limit}只（原本{len(unique_symbols)}只）")
                
                # 分层抽样：按指数比例选择
                # 1. 计算每个指数的比例
                sp500_count = len(self.sp500)
                nasdaq_count = len(self.nasdaq)
                total = sp500_count + nasdaq_count
                
                if total > 0:
                    # 2. 按比例分配名额
                    sp500_limit = max(1, int(limit * (sp500_count / total)))
                    nasdaq_limit = max(1, limit - sp500_limit)
                    
                    # 3. 分别选择（先选标普500，再选纳斯达克）
                    selected_symbols = []
                    selected_symbols.extend(self.sp500[:sp500_limit])
                    
                    # 从纳斯达克中选择，避免与标普500重复
                    nasdaq_unique = [s for s in self.nasdaq if s not in selected_symbols]
                    selected_symbols.extend(nasdaq_unique[:nasdaq_limit])
                    
                    print(f"   📊 分层抽样: 标普500({sp500_limit}只) + 纳斯达克({nasdaq_limit}只)")
                    unique_symbols = selected_symbols
                else:
                    # 如果数据异常，使用简单限制
                    unique_symbols = unique_symbols[:limit]
            else:
                print(f"✅ 完整扫描: {len(unique_symbols)}只股票")
            
            self.stocks = [{'symbol': s, 'name': ''} for s in unique_symbols]
            
            # 标记重叠
            overlap = len(set(self.sp500) & set(self.nasdaq))
            
            print(f"✅ 标普500: {len(self.sp500)}只")
            print(f"✅ 纳斯达克综合: {len(self.nasdaq)}只")
            print(f"✅ 重叠股票: {overlap}只（已去重）")
            print(f"✅ 实际扫描: {len(self.stocks)}只")
        except Exception as e:
            print(f"❌ 加载成分股失败: {e}")
            self.stocks = []
            self.sp500 = []
            self.nasdaq = []
    
    def load_config(self):
        """加载策略配置"""
        with open('/home/admin/.openclaw/workspace-stock/config/us-strategy-v1.6.json', 'r') as f:
            self.config = json.load(f)
    
    def get_buying_power(self):
        """获取账户可用购买力"""
        try:
            with open('/home/admin/.openclaw/workspace-stock/data/trades.json', 'r') as f:
                data = json.load(f)
            # 尝试从账户数据获取
            for acc in data.get('accounts', []):
                if acc.get('acc_type') == 'MARGIN':
                    # 融资账户：总资产 - 持仓市值 = 净资产
                    total = acc.get('total_assets', 0)
                    market_val = acc.get('market_val', 0)
                    # 可用资金约等于净资产
                    return max(0, total - market_val * 0.3)  # 留30%buffer
            return 0
        except:
            return 0
    
    def get_news_sentiment(self):
        """从新闻数据库加载股票情绪，返回 dict{symbol: sentiment}"""
        sentiment_map = {}
        try:
            import sqlite3
            db_path = '/home/admin/.openclaw/workspace-stock/data/news/news.db'
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # 查询最近24小时内有新闻的股票平均情绪
            cursor.execute("""
                SELECT sm.symbol, ROUND(AVG(n.sentiment), 2) as avg_sent, COUNT(*) as cnt
                FROM stock_mentions sm
                JOIN news n ON n.id = sm.news_id
                WHERE n.timestamp > datetime('now', '-24 hours')
                GROUP BY sm.symbol
                HAVING cnt >= 1
            """)
            for row in cursor.fetchall():
                symbol, avg_sent, cnt = row
                sentiment_map[symbol] = avg_sent
            conn.close()
        except Exception as e:
            pass  # 静默失败，使用默认中性
        return sentiment_map
    
    def should_scan(self):
        """判断是否应该扫描（夏令时北京时间）"""
        now = datetime.now()
        current_time = now.time()
        
        # 首先检查是否为交易日
        try:
            from trading_calendar import TradingCalendar
            calendar = TradingCalendar()
            is_trading_day, reason = calendar.is_us_trading_day(now)
            if not is_trading_day:
                return False, f"非交易日 ({reason})"
        except:
            pass  # 如果交易日历检查失败，继续时间判断
        
        # 盘中: 21:00-次日04:00 (当晚到凌晨)
        if current_time >= dt_time(21, 0):
            return True, "盘中"
        if current_time <= dt_time(4, 0):
            return True, "盘中"
        
        # 盘后: 04:00-08:00 (第二天凌晨)
        if dt_time(4, 0) <= current_time <= dt_time(7, 59):
            return True, "盘后"
        
        return False, "非扫描时间"
    
    def calculate_score(self, price, prev_close, change_pct, news_sentiment=None):
        """计算评分（包含新闻情绪因素）"""
        score = 60
        
        # 1. 技术面评分（60%）
        if change_pct > 3:
            score += 25
        elif change_pct > 2:
            score += 20
        elif change_pct > 1:
            score += 15
        elif change_pct > 0:
            score += 5
        elif change_pct < -3:
            score -= 25
        elif change_pct < -2:
            score -= 20
        elif change_pct < -1:
            score -= 10
        
        # 2. 新闻情绪加成（四源共振-国际资讯35%）
        if news_sentiment:
            if news_sentiment > 0.6:  # 正面新闻
                score += 15
            elif news_sentiment < 0.4:  # 负面新闻
                score -= 10
        
        return min(100, max(0, score))
    
    def scan_with_finnhub(self, top_n=50):
        """使用Finnhub扫描"""
        print(f"  使用数据源: Finnhub")
        
        results = []
        total = len(self.stocks)
        
        for i, stock in enumerate(self.stocks):
            try:
                symbol = stock['symbol']
                if (i + 1) % 100 == 0:
                    print(f"    进度: {i+1}/{total}")
                
                url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
                res = requests.get(url, timeout=10)
                
                if res.status_code == 200:
                    data = res.json()
                    price = data.get('c', 0)
                    prev_close = data.get('pc', 0)
                    change_pct = data.get('dp', 0)
                    
                    # 过滤无效数据
                    if price is None or price == 0:
                        continue
                    if prev_close is None or prev_close == 0:
                        continue
                    
                    # 过滤没有成交量的股票（价格过低通常是仙股或无交易）
                    if price < 0.1:
                        continue
                    
                    price_float = float(price)
                    prev_close_float = float(prev_close)
                    change_pct_float = float(change_pct) if change_pct else 0
                    
                    stock_sentiment = self.news_sentiment.get(symbol)
                    score = self.calculate_score(price_float, prev_close_float, change_pct_float, stock_sentiment)
                    
                    # 判断所属指数
                    index = ""
                    if symbol in self.sp500:
                        index = "标普500"
                    if symbol in self.nasdaq:
                        index += "纳斯达克" if not index else "+纳斯达克"
                    
                    if score >= 50:
                        results.append({
                            'symbol': symbol,
                            'name': '',
                            'price': price_float,
                            'prev_close': prev_close_float,
                            'change_pct': round(change_pct_float, 2),
                            'base_score': score,
                            'score': score,
                            'index': index,
                            'timestamp': datetime.now().isoformat()
                        })
                
                time.sleep(0.1)
            
            except Exception as e:
                continue
        
        return results
    
    def scan_with_alphavantage(self, top_n=50):
        """使用AlphaVantage扫描（备用）"""
        print(f"  使用数据源: AlphaVantage（备用）")
        
        results = []
        total = len(self.stocks)
        
        for i, stock in enumerate(self.stocks):
            try:
                symbol = stock['symbol']
                if (i + 1) % 50 == 0:
                    print(f"    进度: {i+1}/{total}")
                
                url = f'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={self.alphavantage_key}'
                res = requests.get(url, timeout=10)
                
                if res.status_code == 200:
                    data = res.json()
                    quote = data.get('Global Quote', {})
                    
                    price = float(quote.get('05. price', 0))
                    prev_close = float(quote.get('08. previous close', 0))
                    change_pct = float(quote.get('10. change percent', '0').replace('%', ''))
                    volume = int(quote.get('06. volume', 0))
                    
                    # 过滤无效数据
                    if price and prev_close:
                        # 过滤没有成交量的股票
                        if price < 0.1 or volume == 0:
                            continue
                        
                        stock_sentiment = self.news_sentiment.get(symbol)
                        score = self.calculate_score(price, prev_close, change_pct, stock_sentiment)
                        
                        index = ""
                        if symbol in self.sp500:
                            index = "标普500"
                        if symbol in self.nasdaq:
                            index += "纳斯达克" if not index else "+纳斯达克"
                        
                        if score >= 50:
                            results.append({
                                'symbol': symbol,
                                'name': '',
                                'price': price,
                                'prev_close': prev_close,
                                'change_pct': round(change_pct, 2),
                                'base_score': score,
                                'score': score,
                                'index': index,
                                'timestamp': datetime.now().isoformat()
                            })
                
                time.sleep(0.2)  # AlphaVantage限流
            
            except:
                continue
        
        return results
    
    def scan_with_yfinance(self, top_n=None):
        """使用yfinance批量获取（主数据源）"""
        try:
            import yfinance as yf
        except ImportError:
            print("❌ yfinance未安装，无法使用批量获取")
            return []
        
        # 总是扫描所有股票，top_n只用于结果过滤
        # self.stocks是字典列表，需要提取symbol
        scan_symbols = [stock['symbol'] for stock in self.stocks]
        
        print(f"📡 使用yfinance批量扫描: {len(scan_symbols)}只股票")
        
        results = []
        batch_size = 100  # 分批获取，避免一次请求太多
        
        for i in range(0, len(scan_symbols), batch_size):
            batch = scan_symbols[i:i+batch_size]
            batch_num = i//batch_size + 1
            print(f"   🔄 批次 {batch_num}/{len(scan_symbols)//batch_size + 1}: {len(batch)}只股票")
            
            # 添加延迟，避免API限制
            if batch_num > 1:
                time.sleep(5)  # 批次间延迟5秒
            
            try:
                # 使用yfinance批量获取
                tickers = yf.Tickers(" ".join(batch))
                
                # 添加额外延迟
                time.sleep(3)
                
                for symbol in batch:
                    try:
                        ticker = tickers.tickers[symbol]
                        info = ticker.info
                        
                        if info:
                            # 盘后/盘前价格（如果有）
                            post_price = info.get('postMarketPrice') or info.get('postMarketChange', 0)
                            pre_price = info.get('preMarketPrice') or info.get('preMarketChange', 0)
                            
                            # 优先使用盘后/盘前价格（如果存在且非0）
                            if post_price and post_price > 0:
                                price = post_price
                                price_type = '盘后'
                            elif pre_price and pre_price > 0:
                                price = pre_price
                                price_type = '盘前'
                            else:
                                price = info.get('regularMarketPrice') or info.get('currentPrice')
                                price_type = '常规'
                            
                            prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
                            
                            if price and prev_close and price > 0 and prev_close > 0:
                                change_pct = (price - prev_close) / prev_close * 100
                                
                                stock_sentiment = self.news_sentiment.get(symbol)
                                score = self.calculate_score(price, prev_close, change_pct, stock_sentiment)
                                
                                index = ""
                                if symbol in self.sp500:
                                    index = "标普500"
                                if symbol in self.nasdaq:
                                    index += "纳斯达克" if not index else "+纳斯达克"
                                
                                if score >= 50:
                                    results.append({
                                        'symbol': symbol,
                                        'name': info.get('shortName') or info.get('longName') or symbol,
                                        'price': price,
                                        'prev_close': prev_close,
                                        'change_pct': round(change_pct, 2),
                                        'base_score': score,
                                        'score': score,
                                        'index': index,
                                        'data_source': 'yfinance',
                                        'price_type': price_type,
                                        'market_cap': info.get('marketCap'),
                                        'volume': info.get('regularMarketVolume'),
                                        'timestamp': datetime.now().isoformat()
                                    })
                    except Exception as e:
                        # 单个股票失败不影响整体
                        continue
                
                print(f"   ✅ 批次 {batch_num} 完成")
                
            except Exception as e:
                error_msg = str(e)
                print(f"   ⚠️ 批次 {batch_num} 失败: {error_msg[:100]}")
                
                # 检查是否是API限制错误
                if 'Too Many Requests' in error_msg or 'Rate limited' in error_msg:
                    print(f"   ⏸️  API限制，等待5秒后重试单个获取...")
                    time.sleep(5)
                
                # 如果批量失败，尝试单个获取（带延迟）
                single_success = 0
                for idx, symbol in enumerate(batch):
                    try:
                        # 单个请求间添加延迟
                        if idx > 0:
                            time.sleep(0.5)
                        
                        ticker = yf.Ticker(symbol)
                        info = ticker.info
                        
                        if info:
                            # 盘后/盘前价格（如果有）
                            post_price = info.get('postMarketPrice') or info.get('postMarketChange', 0)
                            pre_price = info.get('preMarketPrice') or info.get('preMarketChange', 0)
                            
                            # 优先使用盘后/盘前价格（如果存在且非0）
                            if post_price and post_price > 0:
                                price = post_price
                                price_type = '盘后'
                            elif pre_price and pre_price > 0:
                                price = pre_price
                                price_type = '盘前'
                            else:
                                price = info.get('regularMarketPrice') or info.get('currentPrice')
                                price_type = '常规'
                            
                            prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
                            
                            if price and prev_close and price > 0 and prev_close > 0:
                                change_pct = (price - prev_close) / prev_close * 100
                                
                                stock_sentiment = self.news_sentiment.get(symbol)
                                score = self.calculate_score(price, prev_close, change_pct, stock_sentiment)
                                
                                index = ""
                                if symbol in self.sp500:
                                    index = "标普500"
                                if symbol in self.nasdaq:
                                    index += "纳斯达克" if not index else "+纳斯达克"
                                
                                if score >= 50:
                                    results.append({
                                        'symbol': symbol,
                                        'name': info.get('shortName') or info.get('longName') or symbol,
                                        'price': price,
                                        'prev_close': prev_close,
                                        'change_pct': round(change_pct, 2),
                                        'base_score': score,
                                        'score': score,
                                        'index': index,
                                        'data_source': 'yfinance_single',
                                        'market_cap': info.get('marketCap'),
                                        'volume': info.get('regularMarketVolume'),
                                        'timestamp': datetime.now().isoformat()
                                    })
                    except:
                        continue
        
        print(f"✅ yfinance扫描完成: 找到 {len(results)} 个机会")
        
        # 检查是否获取到有效数据，如果没有则触发备用数据源
        if len(results) == 0:
            raise Exception("yfinance未获取到任何有效数据，触发备用数据源")
        
        return results
    
    def scan_with_tinkclaw(self, top_n=50):
        """使用TinkClaw AI交易信号（智能备用）"""
        if not self.tinkclaw_key:
            print("⚠️  TinkClaw API密钥未配置，跳过")
            return []
        
        try:
            import requests
            import json
        except ImportError:
            print("❌ 缺少requests库，无法使用TinkClaw")
            return []
        
        print(f"📡 使用TinkClaw AI信号扫描")
        
        results = []
        total = len(self.stocks)
        
        for i, stock in enumerate(self.stocks):
            if (i + 1) % 10 == 0:
                print(f"    进度: {i+1}/{total}")
            
            try:
                symbol = stock['symbol']
                # 调用TinkClaw API获取交易信号
                url = 'https://tinkclaw.com/api/v1/signal'
                headers = {
                    'Authorization': f'Bearer {self.tinkclaw_key}',
                    'Content-Type': 'application/json'
                }
                data = {
                    'symbol': symbol,
                    'asset_type': 'stock'
                }
                
                res = requests.post(url, headers=headers, json=data, timeout=15)
                
                if res.status_code == 200:
                    signal_data = res.json()
                    
                    # 解析信号数据
                    signal = signal_data.get('signal', {}).get('direction', 'HOLD')
                    confidence = signal_data.get('signal', {}).get('confidence', 50)
                    price = signal_data.get('price', {}).get('current', 0)
                    prev_price = signal_data.get('price', {}).get('previous_close', price)
                    
                    if price > 0 and prev_price > 0:
                        change_pct = (price - prev_price) / prev_price * 100
                        
                        # TinkClaw信号评分转换
                        base_score = 60  # 基础分
                        
                        # 根据信号调整分数
                        if signal == 'BUY':
                            base_score += 20 + (confidence - 50) / 2
                        elif signal == 'SELL':
                            base_score -= 20 - (confidence - 50) / 2
                        # HOLD保持基础分
                        
                        # 价格变化调整
                        if change_pct > 2:
                            base_score += 10
                        elif change_pct > 0:
                            base_score += 5
                        elif change_pct < -2:
                            base_score -= 10
                        elif change_pct < 0:
                            base_score -= 5
                        
                        # 确保分数在合理范围
                        final_score = max(0, min(100, base_score))
                        
                        if final_score >= 50:
                            index = ""
                            if symbol in self.sp500:
                                index = "标普500"
                            if symbol in self.nasdaq:
                                index += "纳斯达克" if not index else "+纳斯达克"
                            
                            results.append({
                                'symbol': symbol,
                                'name': '',
                                'price': price,
                                'prev_close': prev_price,
                                'change_pct': round(change_pct, 2),
                                'base_score': final_score,
                                'score': final_score,
                                'index': index,
                                'signal': signal,
                                'confidence': confidence,
                                'data_source': 'tinkclaw',
                                'timestamp': datetime.now().isoformat()
                            })
                
                # TinkClaw免费版限制（10次/天），需要控制频率
                time.sleep(1)
                
            except Exception as e:
                print(f"   ⚠️  {symbol} TinkClaw失败: {e}")
                continue
        
        print(f"✅ TinkClaw扫描完成: 找到 {len(results)} 个AI信号机会")
        return results
    
    def scan(self, top_n=50):
        """扫描美股市场"""
        print(f"\n{'='*60}")
        print(f"🇺🇸 美股扫描器 v2.0")
        print(f"{'='*60}")
        print(f"股票池: 标普500({len(self.sp500)}只) + 纳斯达克({len(self.nasdaq)}只) = {len(self.stocks)}只")
        print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"扫描时段: 夜盘 | 盘前 | 盘中 | 盘后")
        print(f"{'='*60}\n")
        
        should, reason = self.should_scan()
        if not should:
            print(f"⏸️ 当前{reason}，跳过扫描")
            return []
        
        print(f"✅ 当前扫描时段: {reason}\n")
        
        # 先获取新闻情绪（四源共振-国际资讯35%）
        self.news_sentiment = self.get_news_sentiment()
        sentiment_count = len(self.news_sentiment)
        if sentiment_count > 0:
            print(f"   📰 新闻情绪: 已加载 {sentiment_count} 只股票的情绪数据")
        else:
            print(f"   📰 新闻情绪: 无数据")
        
        # 尝试主数据源 - Finnhub（快，实时）
        try:
            results = self.scan_with_finnhub(top_n)
            self.data_source = 'finnhub'
            print(f"✅ Finnhub数据源成功")
        except Exception as e:
            print(f"⚠️ Finnhub数据源失败: {e}")
            print(f"  切换到备用数据源...")
            
            # 第一备用：AlphaVantage
            try:
                results = self.scan_with_alphavantage(top_n)
                self.data_source = 'alphavantage'
                print(f"✅ AlphaVantage备用数据源成功")
            except Exception as e2:
                print(f"⚠️ AlphaVantage备用也失败: {e2}")
                print(f"  切换到第二备用数据源...")
                
                # 第二备用：yfinance批量获取（慢但数据全）
                try:
                    results = self.scan_with_yfinance(top_n)
                    self.data_source = 'yfinance'
                    print(f"✅ yfinance备用数据源成功")
                except Exception as e3:
                    print(f"⚠️ yfinance备用也失败: {e3}")
                    print(f"  切换到第三备用数据源...")
                    
                    # 第三备用：TinkClaw AI信号
                    try:
                        results = self.scan_with_tinkclaw(top_n)
                        self.data_source = 'tinkclaw'
                        print(f"✅ TinkClaw AI信号备用成功")
                    except Exception as e4:
                        print(f"⚠️ TinkClaw备用也失败: {e4}")
                        print(f"  尝试长桥作为最后备用...")
                        
                        # 第四备用：长桥
                        try:
                            results = self.scan_with_longbridge(top_n)
                            self.data_source = 'longbridge'
                            print(f"✅ 长桥备用数据源成功")
                        except Exception as e5:
                            print(f"⚠️ 长桥备用也失败: {e5}")
                            raise Exception("所有数据源都失败了")
                            print(f"❌ 所有数据源都失败")
                            return []
        
        results.sort(key=lambda x: x['base_score'], reverse=True)
        top_results = results[:top_n]
        
        self.save_results(top_results)
        
        print(f"\n✅ 扫描完成: 扫描{len(self.stocks)}只，获得{len(results)}个有效机会")
        print(f"📊 高评分股票(≥70分): {len([r for r in results if r['base_score'] >= 70])}只")
        print(f"📡 数据源: {self.data_source}")
        
        return top_results
    
    def save_results(self, results):
        """保存扫描结果（加入LLM分析）"""
        
        # 调用LLM分析
        llm_analyzed = []
        
        # 检查账户购买力，避免浪费token
        buying_power = self.get_buying_power()
        # 单票仓位约12%，最小买入金额约$5000
        min_position = 5000
        skip_llm = buying_power < min_position
        
        if skip_llm:
            print(f"   ⚠️ 账户购买力不足(${buying_power:,.0f} < ${min_position:,})，跳过LLM分析")
        else:
            print(f"   💰 账户购买力: ${buying_power:,.0f}")
        
        # 加载新闻情绪
        news_sentiment = self.get_news_sentiment()
        sentiment_count = len(news_sentiment)
        if sentiment_count > 0:
            print(f"   📰 新闻情绪: 已加载 {sentiment_count} 只股票的情绪数据")
        else:
            print(f"   📰 新闻情绪: 无数据")
        
        for candidate in results:
            # 注入新闻情绪到候选股票
            symbol = candidate.get('symbol', '').replace('US.', '')
            if symbol in news_sentiment:
                candidate['sentiment'] = news_sentiment[symbol]
                # 用新闻情绪重新调整基础评分
                sentiment_val = news_sentiment[symbol]
                base = candidate.get('base_score', candidate.get('score', 60))
                if sentiment_val > 0.6:  # 正面新闻
                    base = min(100, base + 15)
                elif sentiment_val < 0.4:  # 负面新闻
                    base = max(0, base - 10)
                candidate['base_score'] = base
                candidate['score'] = base
            # 只分析基础评分>=70的候选
            if candidate.get('score', 0) >= 70:
                # 购买力不足时跳过LLM分析，直接用基础评分
                if skip_llm:
                    candidate['final_score'] = candidate.get('score', 70)
                    candidate['llm_adjust'] = 0
                    candidate['llm_reason'] = '购买力不足，跳过LLM分析'
                else:
                    try:
                        sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
                        from llm_stock_analyzer import analyze_stock
                        
                        market_data = {
                            'symbol': candidate.get('symbol', ''),
                            'market': 'us',
                            'base_score': candidate.get('score', 70),
                            'price': candidate.get('price', 0),
                            'change_pct': candidate.get('change_pct', 0),
                            'rsi': candidate.get('rsi', 50),
                            'ma20': candidate.get('ma20', 0),
                            'ma50': candidate.get('ma50', 0),
                            'volume_ratio': candidate.get('volume_ratio', 1.0),
                            'atr': candidate.get('atr', 0),
                            'sentiment': candidate.get('sentiment', '中性')
                        }
                        
                        llm_result = analyze_stock(candidate.get('symbol'), market_data)
                        
                        candidate['final_score'] = llm_result.get('final_score', candidate.get('score'))
                        candidate['llm_adjust'] = llm_result.get('score_adjust', 0)
                        candidate['llm_reason'] = llm_result.get('llm_reason', '')
                        
                        print(f"   🧠 {candidate.get('symbol')}: 基础{candidate.get('score')} → LLM最终{candidate.get('final_score')}")
                        
                    except Exception as e:
                        print(f"   ⚠️ LLM分析失败: {e}")
                        candidate['final_score'] = candidate.get('score', 70)
                        candidate['llm_adjust'] = 0
                        candidate['llm_reason'] = 'LLM分析失败'
            else:
                candidate['final_score'] = candidate.get('score', 70)
                candidate['llm_adjust'] = 0
                candidate['llm_reason'] = ''
            
            # 只保留最终评分>=65的
            if candidate.get('final_score', 0) >= 65:
                llm_analyzed.append(candidate)
        
        results = llm_analyzed
        
        data = {
            'market': 'US',
            'last_scan': datetime.now().isoformat(),
            'data_source': self.data_source,
            'total_scanned': len(self.stocks),
            'stock_pool': {
                'sp500': len(self.sp500),
                'nasdaq': len(self.nasdaq),
                'total': len(self.stocks)
            },
            'opportunities': results
        }
        
        opportunities_path = '/home/admin/.openclaw/workspace-stock/data/opportunities.json'
        os.makedirs(os.path.dirname(opportunities_path), exist_ok=True)
        
        with open(opportunities_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 结果已保存")
    
    def print_top_results(self, results, n=10):
        """打印Top N结果"""
        print(f"\n📊 美股Top {n}高评分股票:")
        print("-" * 80)
        print(f"{'代码':<10} {'价格':>10} {'涨幅':>8} {'评分':>6} {'指数':<15}")
        print("-" * 80)
        
        for r in results[:n]:
            print(f"{r['symbol']:<10} ${r['price']:>8.2f} {r['change_pct']:>+7.2f}% {r['base_score']:>5}分 {r['index']:<15}")


if __name__ == '__main__':
    # 导入交易日历
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/..')
    
    try:
        from trading_calendar import TradingCalendar
        calendar = TradingCalendar()
        
        # 检查是否为美股交易日
        is_trading_day, reason = calendar.is_us_trading_day()
        
        if not is_trading_day:
            print(f"⏸️ 美股非交易日: {reason}")
            print(f"💡 跳过扫描")
            sys.exit(0)
    except Exception as e:
        print(f"⚠️ 交易日历检查失败: {e}")
        print("💡 继续执行扫描...")
    
    # 执行扫描
    scanner = USScanner()  # 不传递scan_limit参数，扫描所有股票
    results = scanner.scan(top_n=50)  # top_n只限制输出结果数量，不限制扫描股票数量
    if results:
        scanner.print_top_results(results, n=15)

    def scan_with_longbridge(self, top_n=50):
        """使用长桥获取数据（备用数据源）"""
        try:
            import requests
        except ImportError:
            print("⚠️  缺少requests库，跳过长桥")
            return []
        
        if not self.longbridge_token:
            print("⚠️  长桥token未配置，跳过")
            return []
        
        print("📡 使用长桥获取数据...")
        
        results = []
        total = min(len(self.stocks), top_n * 10)  # 扫描更多股票以找到机会
        
        # 长桥API端点
        base_url = "https://openapi.longbridgeapp.com/v1/quote"
        
        headers = {
            "Authorization": f"Bearer {self.longbridge_token}",
            "Content-Type": "application/json"
        }
        
        # 批量获取（每次最多50只）
        batch_size = 50
        for i in range(0, total, batch_size):
            batch = self.stocks[i:i+batch_size]
            symbols = [s['symbol'] for s in batch]
            
            try:
                # 构建请求
                params = {
                    "symbol": symbols,
                    "what": "latest_price,previous_close,change_percent"
                }
                
                resp = requests.get(base_url, headers=headers, params=params, timeout=30)
                
                if resp.status_code == 200:
                    data = resp.json()
                    
                    for item in data.get('data', []):
                        try:
                            symbol = item.get('symbol', '')
                            quote = item.get('quote', {})
                            
                            price = quote.get('latest_price', {}).get('value')
                            prev_close = quote.get('previous_close', {}).get('value')
                            change_pct = quote.get('change_percent', {}).get('value')
                            
                            if price and prev_close and change_pct is not None:
                                # 计算评分
                                stock_sentiment = self.news_sentiment.get(symbol)
                                score = self.calculate_score(price, prev_close, change_pct, stock_sentiment)
                                
                                if score >= 50:
                                    index = ""
                                    if symbol in self.sp500:
                                        index = "标普500"
                                    if symbol in self.nasdaq:
                                        index += "纳斯达克" if not index else "+纳斯达克"
                                    
                                    results.append({
                                        'symbol': symbol,
                                        'name': '',
                                        'price': price,
                                        'prev_close': prev_close,
                                        'change_pct': round(change_pct, 2),
                                        'base_score': score,
                                        'score': score,
                                        'index': index,
                                        'data_source': 'longbridge',
                                        'timestamp': datetime.now().isoformat()
                                    })
                        except Exception:
                            continue
                
                elif resp.status_code == 429:
                    print(f"   ⚠️ 长桥API限制，等待后重试...")
                    time.sleep(5)
                
            except Exception as e:
                print(f"   ⚠️ 批次失败: {str(e)[:50]}")
                continue
            
            # 批次间延迟
            if i + batch_size < total:
                time.sleep(1)
        
        print(f"✅ 长桥扫描完成: 找到 {len(results)} 个机会")
        return results

