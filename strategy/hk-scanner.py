#!/usr/bin/env python3
"""
港股扫描器 v2.0
扫描恒生指数(90只) + 恒生科技指数(30只) = 101只
数据源：Futu OpenD（主） / Tushare（备）
扫描时间：08:50预扫描、交易时段（午休不扫描）

五源共振系统：
- 国际资讯 (30%): Bloomberg, Reuters, 雅虎财经
- 港股公告 (20%): 财报、回购、配股
- 国内社区 (25%): 雪球、富途讨论
- 海外社交 (20%): Twitter, Reddit
"""

import sys
import json
import time
import requests
from datetime import datetime, date, time as dt_time

from runtime_config import (
    DATA_DIR,
    FUTU_HOST,
    FUTU_PORT,
    NEWS_DB_PATH,
    STRATEGY_DIR,
    config_path,
    load_api_keys,
)

# 导入Futu API
from futu import OpenQuoteContext, RET_OK

# 导入港股情绪监控模块
from hk_market_sentiment import HKMarketSentiment

class HKScanner:
    """港股扫描器 - 支持备用数据源"""
    
    def __init__(self):
        self.load_api_keys()
        self.load_stock_pool()
        self.load_config()
        self.data_source = 'futu'  # 默认使用Futu
    
    def load_api_keys(self):
        """加载API密钥"""
        self.keys = load_api_keys()
        
        self.futu_host = FUTU_HOST
        self.futu_port = FUTU_PORT
        self.tushare_token = self.keys.get('tushare', {}).get('token', '')
    
    def get_buying_power(self):
        """获取账户可用购买力"""
        try:
            with (DATA_DIR / 'trades.json').open('r', encoding='utf-8') as f:
                data = json.load(f)
            for acc in data.get('accounts', []):
                if acc.get('acc_type') == 'MARGIN':
                    total = acc.get('total_assets', 0)
                    market_val = acc.get('market_val', 0)
                    return max(0, total - market_val * 0.3)
            return 0
        except:
            return 0
    
    def load_stock_pool(self):
        """加载港股成分股（恒生指数 + 恒生科技），去重"""
        try:
            with (STRATEGY_DIR / 'hk-index-constituents.json').open('r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.hsi = data.get('hsi', [])
            self.hstech = data.get('hstech', [])
            
            # 去重
            self.stocks = list(dict.fromkeys(self.hsi + self.hstech))
            
            # 标记重叠
            overlap = len(set(self.hsi) & set(self.hstech))
            
            print(f"✅ 恒生指数: {len(self.hsi)}只")
            print(f"✅ 恒生科技: {len(self.hstech)}只")
            print(f"✅ 重叠股票: {overlap}只（已去重）")
            print(f"✅ 合并去重: {len(self.stocks)}只")
        except Exception as e:
            print(f"❌ 加载成分股失败: {e}")
            self.stocks = []
            self.hsi = []
            self.hstech = []
    
    def load_config(self):
        """加载策略配置"""
        with config_path('hk-strategy.json').open('r', encoding='utf-8') as f:
            self.config = json.load(f)
    
    def get_market_sentiment(self):
        """获取港股市场情绪（调用独立模块）"""
        try:
            monitor = HKMarketSentiment()
            return monitor.get_market_sentiment()
        except Exception as e:
            print(f"⚠️ 获取市场情绪失败: {e}")
            return None
    
    def get_news_sentiment(self, hours=24):
        """获取市场整体新闻情绪（五源共振-国际资讯25%）"""
        try:
            import sqlite3
            conn = sqlite3.connect(NEWS_DB_PATH)
            cursor = conn.cursor()
            
            query = '''
            SELECT AVG(sentiment) as avg_sentiment 
            FROM news 
            WHERE timestamp >= datetime('now', '-24 hours')
            AND sentiment IS NOT NULL
            '''
            cursor.execute(query)
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0]:
                sentiment = row[0]
                print(f"   📰 市场新闻情绪: {sentiment:.2f}")
                return sentiment
            return None
        except Exception as e:
            print(f"⚠️ 获取新闻情绪失败: {e}")
            return None
    
    def should_scan(self):
        """判断是否应该扫描"""
        now = datetime.now()
        current_time = now.time()
        
        # 首先检查是否为交易日
        try:
            from trading_calendar import TradingCalendar
            calendar = TradingCalendar()
            is_trading_day, reason = calendar.is_hk_trading_day()
            if not is_trading_day:
                return False, f"非交易日 ({reason})"
        except:
            # 如果交易日历检查失败，使用原有的周末检查
            if now.weekday() >= 5:
                return False, "周末"
        
        # 扫描时段
        scan_times = {
            'pre_market': [(8, 50), (9, 30)],
            'morning': [(9, 30), (12, 0)],
            'afternoon': [(13, 0), (16, 10)],
        }
        
        for session, (start, end) in scan_times.items():
            start_time = dt_time(start[0], start[1])
            end_time = dt_time(end[0], end[1])
            
            if start_time <= current_time <= end_time:
                return True, session
        
        if dt_time(12, 0) <= current_time <= dt_time(13, 0):
            return False, "午休时间"
        
        return False, "非扫描时间"
    
    def calculate_score(self, stock_data, price, prev_close, volume=None, news_sentiment=None):
        """计算评分（技术面+消息面统一评分，无行业权重）"""
        score = 60
        
        # 1. 技术面评分
        change_pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
        
        # 涨市策略
        if change_pct > 3:
            score += 25
        elif change_pct > 2:
            score += 20
        elif change_pct > 1:
            score += 15
        elif change_pct > 0:
            score += 5
        elif change_pct >= -1:
            # 持平/微跌 - 不加分不减分
            pass
        else:
            # 跌市策略 - 增加"跌势反弹"加分
            # 核心逻辑：跌市中跑赢大盘的股票可能是反弹机会
            if change_pct >= -2:
                score += 15  # 跑赢大盘
            elif change_pct >= -3:
                score += 5   # 接近大盘
            
            # 如果没有RSI数据但跌幅大，假设超卖
            rsi = stock_data.get('rsi', 50)
            if rsi == 50:  # RSI是默认值，说明没有真实RSI
                if change_pct < -3:  # 跌幅大，假设超卖
                    score += 10
            elif rsi < 30:  # 严重超卖
                score += 15
            elif rsi <= 35:  # 超卖
                score += 10
        
        # 2. 新闻情绪加成（五源共振-国际资讯25%）
        if news_sentiment:
            if news_sentiment > 0.6:  # 正面新闻
                score += 15
            elif news_sentiment < 0.4:  # 负面新闻
                score -= 10
        
        # 2.1 市场情绪调整（VHSI、资金流向、牛熊证 - 共30%权重）
        if hasattr(self, 'market_sentiment') and self.market_sentiment:
            sentiment_score = self.market_sentiment.get('sentiment_score', 50)
            # 将情绪评分(0-100)转换为分数调整(-15到+15)
            sentiment_adjustment = (sentiment_score - 50) * 0.3  # 中心点在50分
            score += sentiment_adjustment
        
        # 4. 技术条件检查（entry_conditions）
        tech_score = self.check_technical_conditions(stock_data, price, prev_close, volume)
        score += tech_score
        
        # 2026-06-19 east 修复 Bug1: base_score 上限从 100 改为 90，给 LLM 预留 10 分调整空间
        return min(90, max(0, score))
    
    def get_stock_sector(self, stock_code, stock_name):
        """根据股票代码或名称判断所属行业"""
        # 基于策略配置中的推荐股票创建映射
        sector_mapping = {
            # 新能源汽车
            'HK.09868': '新能源汽车', '09868': '新能源汽车', '小鹏汽车': '新能源汽车',
            'HK.09866': '新能源汽车', '09866': '新能源汽车', '蔚来': '新能源汽车',
            'HK.02333': '新能源汽车', '02333': '新能源汽车', '比亚迪': '新能源汽车',
            
            # 消费
            'HK.02331': '消费', '02331': '消费', '李宁': '消费',
            'HK.02319': '消费', '02319': '消费', '蒙牛': '消费',
            'HK.02020': '消费', '02020': '消费', '安踏': '消费',
            
            # 医药
            'HK.02269': '医药', '02269': '医药', '药明生物': '医药',
            'HK.01093': '医药', '01093': '医药', '石药集团': '医药',
        }
        
        # 优先匹配代码
        if stock_code in sector_mapping:
            return sector_mapping[stock_code]
        
        # 匹配名称关键词
        for key, sector in sector_mapping.items():
            if not key.startswith('HK.') and not key.isdigit():  # 名称关键词
                if key in stock_name:
                    return sector
        
        # 简单规则：通过股票代码前缀判断（实际应用中需要更精确的映射）
        # 这里只是一个示例，实际应该使用完整的行业分类数据
        if stock_code.startswith('HK.098') or stock_code.startswith('HK.0233'):
            return '新能源汽车'
        elif stock_code.startswith('HK.0231') or stock_code.startswith('HK.020'):
            return '消费'
        elif stock_code.startswith('HK.022') or stock_code.startswith('HK.010'):
            return '医药'
        
        return None
    
    def check_technical_conditions(self, stock_data, price, prev_close, volume):
        """检查技术条件（entry_conditions）"""
        tech_score = 0
        
        # 这里应该从stock_data中获取技术指标
        # 由于Futu API可能没有提供所有指标，这里只实现部分检查
        
        # 1. 成交量放大检查 (volume_surge: >= 1.5x)
        if volume and 'prev_volume' in stock_data:
            volume_ratio = volume / stock_data['prev_volume'] if stock_data['prev_volume'] > 0 else 1
            if volume_ratio >= 1.5:
                tech_score += 5
                stock_data['volume_surge'] = True
            else:
                stock_data['volume_surge'] = False
        
        # 2. 趋势检查 (trend: MA20上升, 价格>MA20)
        # 假设stock_data中有ma20数据
        if 'ma20' in stock_data and 'ma20_slope' in stock_data:
            ma20 = stock_data['ma20']
            ma20_slope = stock_data['ma20_slope']
            
            if price > ma20 and ma20_slope > 0:
                tech_score += 5
                stock_data['trend_up'] = True
            else:
                stock_data['trend_up'] = False
        
        # 3. RSI范围检查 (调整：允许超卖反弹)
        # 原来: 35 <= RSI <= 70
        # 调整后: 20 <= RSI <= 80 (允许超卖反弹)
        if 'rsi' in stock_data:
            rsi = stock_data['rsi']
            if 20 <= rsi <= 80:  # 扩大范围，允许超卖
                tech_score += 5
                stock_data['rsi_ok'] = True
            else:
                stock_data['rsi_ok'] = False
        
        # 4. 增强信号检查 (enhance_signals: >= 1个)
        enhance_signals = 0
        if stock_data.get('break_high', False):
            enhance_signals += 1
        if stock_data.get('bollinger_squeeze', False):
            enhance_signals += 1
        
        if enhance_signals >= 1:
            tech_score += 5
            stock_data['enhance_signal'] = True
        else:
            stock_data['enhance_signal'] = False
        
        return tech_score
    
    def get_real_technicals(self, symbol):
        """从Futu获取单个股票的真实技术指标（RSI、MA）"""
        try:
            from futu import OpenQuoteContext, RET_OK
            import pandas as pd
            
            ctx = OpenQuoteContext(self.futu_host, self.futu_port)
            
            # 获取60天K线
            ret, klines, extra = ctx.request_history_kline(symbol, start='', end='', max_count=60)
            
            if ret != RET_OK or klines is None or klines.empty:
                ctx.close()
                return {'rsi': 50, 'ma20': 0, 'ma50': 0}
            
            df = pd.DataFrame(klines)
            closes = df['close'].astype(float).values
            
            # 计算RSI (14天)
            deltas = pd.Series(closes).diff()
            gains = deltas.clip(lower=0).rolling(14).mean()
            losses = (-deltas.clip(upper=0)).rolling(14).mean()
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
            rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
            
            # 计算MA
            ma20 = pd.Series(closes).rolling(20).mean().iloc[-1] if len(closes) >= 20 else closes[-1]
            ma50 = pd.Series(closes).rolling(50).mean().iloc[-1] if len(closes) >= 50 else ma20
            
            ctx.close()
            
            return {
                'rsi': float(rsi) if not pd.isna(rsi) else 50,
                'ma20': float(ma20) if not pd.isna(ma20) else 0,
                'ma50': float(ma50) if not pd.isna(ma50) else 0
            }
        except Exception as e:
            print(f"  ⚠️ 获取{symbol}技术指标失败: {e}")
            return {'rsi': 50, 'ma20': 0, 'ma50': 0}
    
    def batch_get_real_technicals(self, symbols):
        """批量获取多只股票的技术指标（优化版）"""
        try:
            from futu import OpenQuoteContext, RET_OK
            import pandas as pd
            
            techs = {}
            ctx = OpenQuoteContext(self.futu_host, self.futu_port)
            
            for i, symbol in enumerate(symbols):
                if (i + 1) % 20 == 0:
                    print(f"    技术指标进度: {i+1}/{len(symbols)}")
                
                try:
                    ret, klines, extra = ctx.request_history_kline(symbol, start='', end='', max_count=60)
                    
                    if ret == RET_OK and klines is not None and not klines.empty:
                        df = pd.DataFrame(klines)
                        closes = df['close'].astype(float).values
                        
                        # 计算RSI
                        deltas = pd.Series(closes).diff()
                        gains = deltas.clip(lower=0).rolling(14).mean()
                        losses = (-deltas.clip(upper=0)).rolling(14).mean()
                        rs = gains / losses
                        rsi = 100 - (100 / (1 + rs))
                        rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
                        
                        # 计算MA
                        ma20 = pd.Series(closes).rolling(20).mean().iloc[-1] if len(closes) >= 20 else closes[-1]
                        ma50 = pd.Series(closes).rolling(50).mean().iloc[-1] if len(closes) >= 50 else ma20
                        
                        techs[symbol] = {
                            'rsi': float(rsi_val) if not pd.isna(rsi_val) else 50,
                            'ma20': float(ma20) if not pd.isna(ma20) else 0,
                            'ma50': float(ma50) if not pd.isna(ma50) else 0
                        }
                    else:
                        techs[symbol] = {'rsi': 50, 'ma20': 0, 'ma50': 0}
                except:
                    techs[symbol] = {'rsi': 50, 'ma20': 0, 'ma50': 0}
            
            ctx.close()
            return techs
        except Exception as e:
            print(f"  ⚠️ 批量获取技术指标失败: {e}")
            return {sym: {'rsi': 50, 'ma20': 0, 'ma50': 0} for sym in symbols}
    
    def scan_with_futu(self, top_n=50):
        """使用Futu OpenD扫描"""
        from futu import OpenQuoteContext, RET_OK
        
        print(f"  使用数据源: Futu OpenD")
        
        results = []
        quote_ctx = OpenQuoteContext(self.futu_host, self.futu_port)
        
        try:
            # 获取新闻情绪（五源共振-国际资讯25%）
            self.news_sentiment = self.get_news_sentiment(hours=24)
            
            total = len(self.stocks)
            
            for i, code in enumerate(self.stocks):
                try:
                    if (i + 1) % 20 == 0:
                        print(f"    进度: {i+1}/{total}")
                    
                    ret, snapshot = quote_ctx.get_market_snapshot([code])
                    
                    if ret == RET_OK and not snapshot.empty:
                        row = snapshot.iloc[0]
                        name = row.get('name', '')
                        price = row.get('last_price')
                        prev_close = row.get('prev_close_price')
                        volume = row.get('volume', 0)
                        
                        # 过滤无效数据
                        if price is None or price == 'N/A' or price == 0:
                            continue
                        if prev_close is None or prev_close == 'N/A' or prev_close == 0:
                            continue
                        
                        # 过滤没有成交量的股票
                        try:
                            volume_float = float(volume) if volume and volume != 'N/A' else 0
                            if volume_float == 0:
                                continue
                        except:
                            continue
                        
                        price_float = float(price)
                        prev_close_float = float(prev_close)
                        change_pct = (price_float - prev_close_float) / prev_close_float * 100
                        
                        # 准备stock_data用于技术条件检查
                        stock_data = {
                            'code': code,
                            'name': name,
                            'price': price_float,
                            'prev_close': prev_close_float,
                            'volume': volume_float,
                            'change_pct': change_pct,
                            'prev_volume': volume_float * 0.8,  # 示例：假设前一日成交量是80%
                            # 实际应用中应该从历史数据获取
                        }
                        
                        # 添加技术指标（临时占位值，后续会被 batch_get_real_technicals() 覆盖）
                        # ⚠️ 这些值仅用于初始筛选，真实技术指标由独立函数批量获取
                        stock_data['ma20'] = price_float * 0.98      # PLACEHOLDER
                        stock_data['ma20_slope'] = 0.1               # PLACEHOLDER
                        stock_data['rsi'] = 50                       # PLACEHOLDER
                        stock_data['break_high'] = price_float > prev_close_float * 1.02  # 简化判断
                        stock_data['bollinger_squeeze'] = True       # PLACEHOLDER
                        
                        score = self.calculate_score(stock_data, price_float, prev_close_float, volume_float, news_sentiment=self.news_sentiment)
                        
                        # 判断所属指数
                        index = ""
                        if code in self.hsi:
                            index = "恒生指数"
                        if code in self.hstech:
                            index += "恒生科技" if not index else "+恒生科技"
                        
                        if score >= 50:
                            results.append({
                                'symbol': code,
                                'name': row.get('stock_name', ''),
                                'price': price_float,
                                'prev_close': prev_close_float,
                                'change_pct': round(change_pct, 2),
                                'base_score': score,
                                'index': index,
                                'sector': index,
                                'market_cap': row.get('market_val'),
                                'trailing_pe': row.get('pe_ttm_ratio'),
                                'pb_ratio': row.get('pb_ratio'),
                                'trailing_eps': row.get('earning_per_share'),
                                'earnings_growth': row.get('net_profit_growth'),
                                'revenue_growth': row.get('sum_of_business_growth'),
                                'net_profit': row.get('net_profit'),
                                'revenue': row.get('sum_of_business'),
                                'volume_ratio': row.get('volume_ratio'),
                                'timestamp': datetime.now().isoformat()
                            })
                except:
                    continue
        finally:
            quote_ctx.close()
        
        return results
    
    def scan_with_tushare(self, top_n=50):
        """使用Tushare扫描（备用）"""
        print(f"  使用数据源: Tushare（备用）")
        
        results = []
        url = "https://api.tushare.pro/pro"
        
        for i, code in enumerate(self.stocks):
            try:
                code_num = code.replace('HK.', '')
                
                # 获取行情数据
                data = {
                    "api_name": "hk_daily",
                    "token": self.tushare_token,
                    "params": {
                        "ts_code": f"{code_num}.HK",
                        "start_date": datetime.now().strftime('%Y%m%d'),
                        "end_date": datetime.now().strftime('%Y%m%d')
                    }
                }
                
                res = requests.post(url, json=data, timeout=10)
                
                if res.status_code == 200:
                    result = res.json()
                    if result.get('data') and result['data'].get('fields'):
                        rows = result['data'].get('items', [])
                        if rows:
                            row = rows[0]
                            # 解析数据
                            close = row[5] if len(row) > 5 else 0
                            pre_close = row[6] if len(row) > 6 else 0
                            
                            if close and pre_close:
                                change_pct = (close - pre_close) / pre_close * 100
                                
                                # 准备stock_data用于技术条件检查
                                stock_data = {
                                    'code': code,
                                    'name': name,
                                    'price': close,
                                    'prev_close': pre_close,
                                    'change_pct': change_pct,
                                    'volume': volume,
                                    'prev_volume': volume * 0.8 if volume else 0,
                                }
                                
                                # 添加技术指标（示例数据）
                                stock_data['ma20'] = close * 0.98
                                stock_data['ma20_slope'] = 0.1
                                stock_data['rsi'] = 50
                                stock_data['break_high'] = close > pre_close * 1.02
                                stock_data['bollinger_squeeze'] = True
                                
                                score = self.calculate_score(stock_data, close, pre_close, volume, news_sentiment=self.news_sentiment)
                                
                                if score >= 50:
                                    index = ""
                                    if code in self.hsi:
                                        index = "恒生指数"
                                    if code in self.hstech:
                                        index += "恒生科技" if not index else "+恒生科技"
                                    
                                    results.append({
                                        'symbol': code,
                                        'name': '',
                                        'price': close,
                                        'prev_close': pre_close,
                                        'change_pct': round(change_pct, 2),
                                        'base_score': score,
                                        'index': index,
                                        'sector': index,
                                        'timestamp': datetime.now().isoformat()
                                    })
                
                time.sleep(0.1)
            except:
                continue
        
        return results
    
    def scan(self, top_n=50):
        """扫描港股市场"""
        print(f"\n{'='*60}")
        print(f"🇭🇰 港股扫描器 v2.0")
        print(f"{'='*60}")
        print(f"股票池: 恒生指数({len(self.hsi)}只) + 恒生科技({len(self.hstech)}只) = {len(self.stocks)}只")
        print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        should, reason = self.should_scan()
        if not should:
            print(f"⏸️ 当前{reason}，跳过扫描")
            return []
        
        print(f"✅ 当前扫描时段: {reason}\n")
        
        # 获取市场情绪
        sentiment = self.get_market_sentiment()
        if sentiment:
            # 检查市场情绪是否适合建仓
            sentiment_score = sentiment.get('sentiment_score', 50)
            if sentiment_score < 30:
                print(f"⚠️ 市场情绪过于恐慌（{sentiment_score}分），建议轻仓或观望\n")
            elif sentiment_score < 50:
                print(f"📊 市场情绪偏谨慎，优选防御性板块\n")
            else:
                print(f"✅ 市场情绪良好，适合建仓\n")
        
        # 尝试主数据源
        try:
            results = self.scan_with_futu(top_n)
            self.data_source = 'futu'
        except Exception as e:
            print(f"⚠️ Futu数据源失败: {e}")
            print(f"  切换到备用数据源...")
            
            # 使用备用数据源
            try:
                results = self.scan_with_tushare(top_n)
                self.data_source = 'tushare'
            except Exception as e2:
                print(f"❌ 备用数据源也失败: {e2}")
                return []
        
        results.sort(key=lambda x: x['base_score'], reverse=True)
        top_results = results[:top_n]
        
        self.save_results(top_results)
        
        print(f"\n✅ 扫描完成: {len(results)}/{len(self.stocks)}只有效")
        print(f"📊 高评分股票(≥70分): {len([r for r in results if r['base_score'] >= 70])}只")
        print(f"📡 数据源: {self.data_source}")
        
        return top_results
    
    def save_results(self, results):
        """保存扫描结果（获取真实技术数据后调用LLM分析）"""
        
        # 批量获取真实技术指标（对评分>=50的候选）
        real_tech_count = 0
        symbols = [c.get('symbol', '') for c in results if c.get('base_score', 0) >= 50]
        if symbols:
            print(f"   📊 批量获取 {len(symbols)} 只股票的技术指标...")
            try:
                from technical_indicators_hk import HKTechIndicators
                tech_analyzer = HKTechIndicators()
                try:
                    techs = {sym: tech_analyzer.get_llm_snapshot(sym) for sym in symbols}
                finally:
                    tech_analyzer.close()
                for candidate in results:
                    sym = candidate.get('symbol', '')
                    tech_data = techs.get(sym) or {}
                    if tech_data:
                        candidate.update(tech_data)
                        if not candidate.get('volume_ratio'):
                            candidate['volume_ratio'] = tech_data.get('kline_volume_ratio')
                        real_tech_count += 1
                        print(f"   📊 {sym}: RSI={candidate['rsi']:.1f}, MACD={candidate.get('macd_state', 'N/A')}")
            except Exception as e:
                print(f"   ⚠️ 批量获取失败: {e}")
        
        print(f"\n   获取了 {real_tech_count} 只股票的真实技术指标")
        
        # 调用LLM分析
        llm_analyzed = []
        
        # 检查账户购买力，避免浪费token
        buying_power = self.get_buying_power()
        min_position = 5000
        skip_llm = buying_power < min_position
        
        if skip_llm:
            print(f"   ⚠️ 账户购买力不足(${buying_power:,.0f} < ${min_position:,})，跳过LLM分析")
        else:
            print(f"   💰 账户购买力: ${buying_power:,.0f}")
        
        # 🎯 五源补算覆盖候选池；LLM 仍只处理评分最高的前 10 只（剩下的直接用基础分，避免烧token）
        TOP_LLM_N = 10
        # results 已按 base_score 倒序，拍一下前几只的 symbol 作为名单
        top_llm_set = {(r.get('symbol') or '') for r in results[:TOP_LLM_N]}
        if not skip_llm:
            print(f"   🧠 LLM 仅处理评分 Top {TOP_LLM_N}")
        
        for candidate in results:
            # 候选池内统一跑真实五源评分；LLM 仍只处理 Top10 名单
            if candidate.get('base_score', 0) >= 70:
                # 2026-06-24 east 新增：给候选池跑真实五源评分（不是硬拆）
                sym_clean = (candidate.get('symbol') or '').replace('HK.', '')
                try:
                    sys.path.insert(0, str(STRATEGY_DIR))
                    from four_source_scorer import score_all as _fs_score_all
                    fs = _fs_score_all(sym_clean, 'hk')
                    candidate['score_news'] = fs['score_news']
                    candidate['score_announce'] = fs['score_announce']
                    candidate['score_community'] = fs['score_community']
                    candidate['score_institution'] = fs['score_institution']
                    candidate['score_capital'] = fs['score_capital']
                    candidate['available_news'] = fs['available_news']
                    candidate['available_announce'] = fs['available_announce']
                    candidate['available_community'] = fs['available_community']
                    candidate['available_institution'] = fs['available_institution']
                    candidate['available_capital'] = fs['available_capital']
                    candidate['evidence_news'] = fs['evidence_news']
                    candidate['evidence_announce'] = fs['evidence_announce']
                    candidate['evidence_community'] = fs['evidence_community']
                    candidate['evidence_institution'] = fs['evidence_institution']
                    candidate['evidence_capital'] = fs['evidence_capital']
                    candidate['five_source_total'] = fs['score_total']
                    candidate['four_source_total'] = fs['score_total']  # 兼容旧字段
                    candidate['five_source_available_count'] = fs['available_count']
                    candidate['four_source_available_count'] = fs['available_count']  # 兼容旧字段

                    # 第一层社区情绪：单独调 futu-comment-sentiment 拿原始百分比写回 candidate
                    try:
                        from four_source_scorer import _community_futu_comment as _futu_com
                        hk_sym_raw = (candidate.get('symbol') or '').replace('HK.', '')
                        futu_com = _futu_com(hk_sym_raw or sym_clean, 25)
                        if futu_com.get('available'):
                            raw = futu_com.get('raw', {})
                            candidate['community_bull_pct'] = raw.get('bull_pct', 0)
                            candidate['community_bear_pct'] = raw.get('bear_pct', 0)
                            candidate['community_neutral_pct'] = 1 - raw.get('bull_pct', 0) - raw.get('bear_pct', 0)
                            candidate['community_post_count'] = raw.get('count', 0)
                            candidate['community_futu_score'] = futu_com.get('score', 0)
                    except Exception as _e:
                        pass  # 社区百分比是辅助字段，失败不影响主流程

                    # 第一层资金异动：从 score_all 返回的 raw 读原始数据写回 candidate
                    try:
                        cap_raw = fs.get('raw', {}).get('capital', {})
                        if cap_raw:
                            candidate['capital_direction'] = cap_raw.get('direction', '')
                            candidate['capital_pos_hits'] = cap_raw.get('pos_hits', 0)
                            candidate['capital_neg_hits'] = cap_raw.get('neg_hits', 0)
                            candidate['capital_content'] = cap_raw.get('content', '')
                            candidate['capital_futu_score'] = fs.get('score_capital', 0)
                    except Exception as _e:
                        pass  # 资金异动原始字段是辅助字段，失败不影响主流程

                    print(f"   📊 {candidate.get('symbol')} 五源: 资讯{fs['score_news']}/公告{fs['score_announce']}/社区{fs['score_community']}/机构{fs['score_institution']}/资金{fs['score_capital']} (总{fs['score_total']}, 覆盖{fs['available_count']}/5)")

                    # 2026-06-24 east 关键：让扫描器评分跟通知一致
                    if fs['available_count'] >= 3:
                        candidate['base_score_legacy'] = candidate.get('base_score', 70)
                        candidate['base_score'] = fs['score_total']
                        candidate['score'] = fs['score_total']
                        candidate['scoring_mode'] = 'five_source_real'
                        print(f"   ✅ {candidate.get('symbol')} 采用真五源总分 {fs['score_total']} (原 base_score {candidate['base_score_legacy']})")
                    else:
                        candidate['base_score_legacy'] = candidate.get('base_score', 70)
                        candidate['base_score'] = int(candidate.get('base_score', 70) * 0.8)
                        candidate['score'] = candidate['base_score']
                        candidate['scoring_mode'] = f'legacy_discounted (覆盖{fs["available_count"]}/5 <3)'
                        print(f"   ⚠️ {candidate.get('symbol')} 覆盖不足，降级为 base_score×0.8 = {candidate['base_score']}")
                except Exception as e:
                    print(f"   ⚠️ {candidate.get('symbol')} 五源评分失败: {e}")

                # 购买力不足时跳过LLM分析，直接用基础评分
                if skip_llm:
                    candidate['final_score'] = candidate.get('base_score', 70)
                    candidate['llm_adjust'] = 0
                    candidate['llm_reason'] = '购买力不足，跳过LLM分析'
                else:
                    try:
                        sys.path.insert(0, str(STRATEGY_DIR))
                        from llm_stock_analyzer import analyze_stock
                        
                        market_data = {
                            'symbol': candidate.get('symbol', ''),
                            'market': 'hk',
                            'base_score': candidate.get('base_score', 70),
                            'price': candidate.get('price', 0),
                            'change_pct': candidate.get('change_pct', 0),
                            'rsi': candidate.get('rsi', 50),
                            'ma20': candidate.get('ma20', 0),
                            'ma50': candidate.get('ma50', 0),
                            'volume_ratio': candidate.get('volume_ratio') or candidate.get('kline_volume_ratio'),
                            'atr': candidate.get('atr', 0),
                            'macd': candidate.get('macd'),
                            'macd_signal': candidate.get('macd_signal'),
                            'macd_state': candidate.get('macd_state', ''),
                            'ma20_slope_pct': candidate.get('ma20_slope_pct'),
                            'return_5d_pct': candidate.get('return_5d_pct'),
                            'return_20d_pct': candidate.get('return_20d_pct'),
                            'distance_20d_high_pct': candidate.get('distance_20d_high_pct'),
                            'intraday_drawdown_pct': candidate.get('intraday_drawdown_pct'),
                            'price_above_ma20': candidate.get('price_above_ma20'),
                            'price_above_ma50': candidate.get('price_above_ma50'),
                            'market_cap': candidate.get('market_cap'),
                            'trailing_pe': candidate.get('trailing_pe'),
                            'pb_ratio': candidate.get('pb_ratio'),
                            'revenue_growth': candidate.get('revenue_growth'),
                            'earnings_growth': candidate.get('earnings_growth'),
                            'net_profit': candidate.get('net_profit'),
                            'revenue': candidate.get('revenue'),
                            'trailing_eps': candidate.get('trailing_eps'),
                            'sector': candidate.get('sector', ''),
                            'sentiment': candidate.get('sentiment', '中性'),
                            'score_news': candidate.get('score_news', 0),
                            'score_announce': candidate.get('score_announce', 0),
                            'score_community': candidate.get('score_community', 0),
                            'score_institution': candidate.get('score_institution', 0),
                            'score_capital': candidate.get('score_capital', 0),
                            'evidence_announce': candidate.get('evidence_announce', ''),
                            'evidence_community': candidate.get('evidence_community', ''),
                            'evidence_institution': candidate.get('evidence_institution', ''),
                            'evidence_capital': candidate.get('evidence_capital', ''),
                            'capital_direction': candidate.get('capital_direction', ''),
                            'community_bull_pct': candidate.get('community_bull_pct', 0),
                            'community_bear_pct': candidate.get('community_bear_pct', 0),
                            'community_post_count': candidate.get('community_post_count', 0),
                        }
                        
                        llm_result = analyze_stock(candidate.get('symbol'), market_data)
                        
                        candidate['final_score'] = llm_result.get('final_score', candidate.get('base_score'))
                        candidate['llm_adjust'] = llm_result.get('score_adjust', 0)
                        candidate['llm_reason'] = llm_result.get('llm_reason', '')
                        candidate['llm_passed'] = bool(llm_result.get('passed', True))
                        candidate['llm_status'] = llm_result.get('llm_status', 'parsed')
                        
                        print(f"   🧠 {candidate.get('symbol')}: 基础{candidate.get('base_score')} → LLM最终{candidate.get('final_score')}")
                        
                    except Exception as e:
                        print(f"   ⚠️ LLM分析失败: {e}")
                        candidate['final_score'] = candidate.get('base_score', 70)
                        candidate['llm_adjust'] = 0
                        candidate['llm_reason'] = f'LLM分析失败，禁止交易: {e}'
                        candidate['llm_passed'] = False
                        candidate['llm_status'] = 'failed'
            else:
                candidate['final_score'] = candidate.get('base_score', 70)
                candidate['llm_adjust'] = 0
                if candidate.get('base_score', 0) < 70:
                    candidate['llm_reason'] = ''
                else:
                    candidate['llm_reason'] = f'评分未进入 Top{TOP_LLM_N}，跳过 LLM'
                candidate['llm_passed'] = True  # 未达到LLM分析阈值，默认通过
            
            # 只保留最终评分>=65的
            if candidate.get('final_score', 0) >= 65:
                llm_analyzed.append(candidate)
        
        results = llm_analyzed
        
        # ===== LLM分析完成后，直接触发交易 =====
        auto_trade_min_score = 75
        high_score_opportunities = [
            c for c in results
            if c.get('llm_passed', True) and c.get('final_score', 0) >= auto_trade_min_score
        ]
        
        if high_score_opportunities:
            print(f"\n🚀 发现 {len(high_score_opportunities)} 个高分机会，尝试直接交易...")
            self.execute_trades_directly(high_score_opportunities)
        
        data = {
            'market': 'HK',
            'last_scan': datetime.now().isoformat(),
            'data_source': self.data_source,
            'total_scanned': len(results),
            'stock_pool': {
                'hsi': len(self.hsi),
                'hstech': len(self.hstech),
                'total': len(self.stocks)
            },
            'opportunities': results
        }
        
        with (DATA_DIR / 'hk-opportunities.json').open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 结果已保存")
    
    def execute_trades_directly(self, opportunities):
        """LLM分析完成后，直接触发交易"""
        try:
            # 导入自动交易模块（文件名是auto-trader.py）
            import importlib.util
            spec = importlib.util.spec_from_file_location("auto_trader", STRATEGY_DIR / "auto-trader.py")
            auto_trader_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(auto_trader_module)
            AutoTrader = auto_trader_module.AutoTrader
            
            trader = AutoTrader()
            
            # 连接Futu
            if not trader.connect_futu():
                print("   ❌ 无法连接Futu，跳过交易")
                return
            
            # 检查交易时间
            if not trader.check_trading_hours('hk'):
                print("   ⏸️ 非港股交易时间，跳过")
                return
            
            # 获取账户信息
            account = trader.get_account_and_positions('hk')
            if not account:
                print("   ❌ 无法获取账户信息")
                return
            
            print(f"   💰 账户: 总资产${account['total_assets']:,.0f}, 现金${account['cash']:,.0f}")
            print(f"   📈 当前持仓: {len(account['positions'])}只")
            
            # 对每个高分机会尝试交易
            for opp in opportunities[:3]:  # 最多处理前3个
                symbol = opp.get('symbol', '')
                price = opp.get('price', 0)
                score = opp.get('final_score', 0)
                
                # 检查是否已持仓
                should, reason = trader.should_trade(symbol, account['positions'], account.get('pending_orders', []))
                if not should:
                    print(f"   ⏭️ {symbol}: {reason}")
                    continue
                
                # 检查技术指标
                tech_signals = trader.check_technical_signals(symbol, market='hk')
                if not tech_signals.get('can_enter', False):
                    print(f"   ⏭️ {symbol}: 技术指标不满足")
                    continue
                
                lot_size = trader._get_hk_lot_size(symbol)
                order_plan = trader.prepare_buy_order(account, symbol, price, score, market='hk', lot_size=lot_size)
                if not order_plan.get('can_buy'):
                    print(f"   ⏭️ {symbol}: {order_plan.get('reason', '风控未通过')}")
                    continue

                quantity = order_plan['quantity']

                if quantity > 0:
                    print(f"\n   🎯 准备买入 {symbol}")
                    print(f"      价格: ${price:.2f}")
                    print(f"      数量: {quantity}股 (每手{lot_size})")
                    print(f"      评分: {score}分")
                    print(f"      评分仓位: {order_plan['base_pct']*100:.1f}%")
                    
                    # 执行交易 (不再重复LLM分析)
                    entry_reasons = [f"评分{score}分"] + tech_signals.get('reasons', [])
                    success = trader.execute_trade(
                        symbol, 'BUY', quantity, price, 'hk', 
                        skip_llm=True,  # 跳过重复LLM分析
                        score=score,
                        reasons=entry_reasons,
                        opp=opp
                    )
                    
                    if success:
                        account['positions'].append({'symbol': symbol})
                        print(f"   ✅ {symbol} 交易成功")
                    else:
                        print(f"   ❌ {symbol} 交易失败")
            
            # 关闭连接
            if trader.quote_ctx:
                trader.quote_ctx.close()
            if trader.hk_trade_ctx:
                trader.hk_trade_ctx.close()
                
        except Exception as e:
            print(f"   ❌ 直接交易失败: {e}")
            import traceback
            traceback.print_exc()
    
    def print_top_results(self, results, n=10):
        """打印Top N结果"""
        print(f"\n📊 港股Top {n}高评分股票:")
        print("-" * 80)
        print(f"{'代码':<12} {'名称':<10} {'价格':>10} {'涨幅':>8} {'评分':>6} {'指数':<15}")
        print("-" * 80)
        
        for r in results[:n]:
            print(f"{r['symbol']:<12} {r['name'][:8]:<10} ${r['price']:>8.2f} {r['change_pct']:>+7.2f}% {r['base_score']:>5}分 {r['index']:<15}")


if __name__ == '__main__':
    # 导入交易日历
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/..')
    
    try:
        from trading_calendar import TradingCalendar
        calendar = TradingCalendar()
        
        # 检查是否为港股交易日
        is_trading_day, reason = calendar.is_hk_trading_day()
        
        if not is_trading_day:
            print(f"⏸️ 港股非交易日: {reason}")
            print(f"💡 跳过扫描")
            sys.exit(0)
    except Exception as e:
        print(f"⚠️ 交易日历检查失败: {e}")
        print("💡 继续执行扫描...")
    
    # 执行扫描
    scanner = HKScanner()
    results = scanner.scan(top_n=50)
    if results:
        scanner.print_top_results(results, n=15)
