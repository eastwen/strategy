#!/usr/bin/env python3
"""
港股扫描器（版本由 runtime_config.SYSTEM_VERSION 管理）
扫描恒生指数(90只) + 恒生科技指数(30只) = 101只
数据源：Futu OpenD（主） / Tushare / Yahoo Finance / 长桥 / AlphaVantage（备）
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, time as dt_time

from runtime_config import (
    DATA_DIR,
    FUTU_HOST,
    FUTU_PORT,
    NEWS_DB_PATH,
    STRATEGY_DIR,
    STRATEGY_POLICY,
    SYSTEM_VERSION,
    config_path,
    load_api_keys,
)

# 导入Futu API
from futu import OpenQuoteContext, RET_OK

LAYER2_CANDIDATE_MIN_SCORE = 65

# 港股量能闸门（对齐美股流动性闸门意图，数值按港股市场口径调整）
# 判据：kline_volume_ratio = 当天累计成交量 / 20日均量（Futu K线可得）
# 港股低价迷你股多、日内累计量天然偏低，阈值比美股(极端无量0.009)放宽两档：
#   ratio < 0.3  → 无量假冲高，一票否决，压到候选线以下（不进入五源/交易）
#   0.3 ≤ r < 0.5 → 量能明显不足，降10分（仅观察，不直接禁）
HK_VOLUME_GATE_SEVERE = 0.3    # 低于此值视为「无量」→ 禁入交易候选
HK_VOLUME_GATE_WARN = 0.5      # 低于此值视为「量能不足」→ 降10分观察
HK_VOLUME_GATE_WARN_PENALTY = 10      # 量能不足惩罚分

def combine_layer_scores(first_layer_score, five_source_score):
    """第一层主导总分，港股五源只提供10%的深度校验权重。"""
    first = float(first_layer_score or 0)
    second = float(five_source_score or 0)
    return int(round(first * 0.9 + second * 0.1))

# 导入港股情绪监控模块
from hk_market_sentiment import HKMarketSentiment

class HKScanner:
    """港股扫描器 - 支持备用数据源"""
    
    def __init__(self):
        self.load_api_keys()
        self.load_stock_pool()
        self.load_config()
        self.data_source = 'futu'  # 默认使用Futu
        self.news_sentiment = None
        self.market_sentiment = None
    
    def load_api_keys(self):
        """加载API密钥"""
        self.keys = load_api_keys()
        
        self.futu_host = FUTU_HOST
        self.futu_port = FUTU_PORT
        self.tushare_token = self.keys.get('tushare', {}).get('token', '')
        self.alphavantage_key = self.keys.get('alphavantage', {}).get('api_key', '')
        self.longbridge_token = self.keys.get('longbridge', {}).get('token', '')
    
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
            self.custom_stocks = data.get('custom', [])
            # 官方指数成分股与明确配置的自定义标的按代码合并去重。
            self.stocks = list(dict.fromkeys(
                self.hsi + self.hstech + self.custom_stocks
            ))
            
            # 标记重叠
            overlap = len(set(self.hsi) & set(self.hstech))
            
            print(f"✅ 恒生指数: {len(self.hsi)}只")
            print(f"✅ 恒生科技: {len(self.hstech)}只")
            print(f"✅ 重叠股票: {overlap}只（已去重）")
            print(f"✅ 自定义标的: {len(self.custom_stocks)}只")
            print(f"✅ 合并去重: {len(self.stocks)}只")
        except Exception as e:
            print(f"❌ 加载成分股失败: {e}")
            self.stocks = []
            self.hsi = []
            self.hstech = []
            self.custom_stocks = []
    
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
                        fields = result['data'].get('fields', [])
                        rows = result['data'].get('items', [])
                        if rows:
                            row = rows[0]
                            values = dict(zip(fields, row))
                            close = values.get('close', 0)
                            pre_close = values.get('pre_close', 0)
                            volume = values.get('vol', 0) or 0
                            name = values.get('name', '') or ''
                            
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

    @staticmethod
    def _hk_vendor_symbol(code, suffix):
        raw = str(code).replace('HK.', '').lstrip('0') or '0'
        return f"{raw.zfill(4)}.{suffix}"

    def _quote_candidate(self, code, price, prev_close, volume=0, name='', source=''):
        try:
            price = float(price)
            prev_close = float(prev_close)
            volume = float(volume or 0)
            if price <= 0 or prev_close <= 0:
                return None
            change_pct = (price - prev_close) / prev_close * 100
            stock_data = {
                'code': code, 'name': name, 'price': price,
                'prev_close': prev_close, 'volume': volume,
                'prev_volume': volume * 0.8 if volume else 0,
                'change_pct': change_pct, 'ma20': price * 0.98,
                'ma20_slope': 0.1, 'rsi': 50,
                'break_high': price > prev_close * 1.02,
                'bollinger_squeeze': True,
            }
            score = self.calculate_score(
                stock_data, price, prev_close, volume,
                news_sentiment=self.news_sentiment,
            )
            if score < 50:
                return None
            index = ''
            if code in self.hsi:
                index = '恒生指数'
            if code in self.hstech:
                index += '恒生科技' if not index else '+恒生科技'
            return {
                'symbol': code, 'name': name, 'price': price,
                'prev_close': prev_close, 'change_pct': round(change_pct, 2),
                'base_score': score, 'index': index, 'sector': index,
                'data_source': source, 'timestamp': datetime.now().isoformat(),
            }
        except (TypeError, ValueError):
            return None

    def scan_with_yahoo(self, top_n=50):
        """Yahoo chart API backup; no yfinance package required."""
        print("  使用数据源: Yahoo Finance（备用）")

        def fetch(code):
            symbol = self._hk_vendor_symbol(code, 'HK')
            response = requests.get(
                f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
                params={'range': '2d', 'interval': '1d'}, timeout=5,
                headers={'User-Agent': 'Mozilla/5.0'},
            )
            if response.status_code != 200:
                return None
            result = (response.json().get('chart', {}).get('result') or [None])[0]
            if not result:
                return None
            meta = result.get('meta', {}) or {}
            indicators = result.get('indicators', {}).get('quote', [{}])[0] or {}
            volumes = indicators.get('volume') or []
            return self._quote_candidate(
                code,
                meta.get('regularMarketPrice'),
                meta.get('previousClose') or meta.get('chartPreviousClose'),
                next((v for v in reversed(volumes) if v is not None), 0),
                meta.get('longName') or meta.get('shortName') or '',
                'yahoo',
            )

        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch, code) for code in self.stocks]
            for future in as_completed(futures):
                try:
                    candidate = future.result()
                    if candidate:
                        results.append(candidate)
                except Exception:
                    continue
        return results

    def scan_with_longbridge(self, top_n=50):
        """Longbridge batch quote backup."""
        if not self.longbridge_token:
            raise RuntimeError('长桥 token 未配置')
        print("  使用数据源: 长桥（备用）")
        headers = {'Authorization': f'Bearer {self.longbridge_token}'}
        vendor_to_code = {
            self._hk_vendor_symbol(code, 'HK'): code for code in self.stocks
        }
        results = []
        symbols = list(vendor_to_code)
        for offset in range(0, len(symbols), 50):
            batch = symbols[offset:offset + 50]
            response = requests.get(
                'https://openapi.longbridgeapp.com/v1/quote',
                headers=headers,
                params={'symbol': batch, 'what': 'latest_price,previous_close,change_percent'},
                timeout=10,
            )
            if response.status_code != 200:
                continue
            for item in response.json().get('data', []) or []:
                code = vendor_to_code.get(item.get('symbol'))
                quote = item.get('quote', {}) or {}
                if not code:
                    continue
                candidate = self._quote_candidate(
                    code,
                    (quote.get('latest_price') or {}).get('value'),
                    (quote.get('previous_close') or {}).get('value'),
                    source='longbridge',
                )
                if candidate:
                    results.append(candidate)
        return results

    def scan_with_alphavantage(self, top_n=50, time_budget_seconds=120):
        """AlphaVantage final backup, bounded to avoid holding up the HK scan."""
        if not self.alphavantage_key:
            raise RuntimeError('AlphaVantage key 未配置')
        print("  使用数据源: AlphaVantage（最终备用，最多2分钟）")
        results = []
        started = time.time()
        for code in self.stocks:
            if time.time() - started >= time_budget_seconds:
                break
            symbol = self._hk_vendor_symbol(code, 'HKG')
            try:
                response = requests.get(
                    'https://www.alphavantage.co/query',
                    params={'function': 'GLOBAL_QUOTE', 'symbol': symbol,
                            'apikey': self.alphavantage_key},
                    timeout=6,
                )
                quote = response.json().get('Global Quote', {}) if response.status_code == 200 else {}
                candidate = self._quote_candidate(
                    code, quote.get('05. price'), quote.get('08. previous close'),
                    quote.get('06. volume', 0), source='alphavantage',
                )
                if candidate:
                    results.append(candidate)
            except Exception:
                continue
        return results
    
    def scan(self, top_n=50):
        """扫描港股市场"""
        print(f"\n{'='*60}")
        print(f"🇭🇰 港股扫描器 {SYSTEM_VERSION}")
        print(f"{'='*60}")
        print(f"股票池: 恒生指数({len(self.hsi)}只) + 恒生科技({len(self.hstech)}只) = {len(self.stocks)}只")
        print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        should, reason = self.should_scan()
        if not should:
            print(f"⏸️ 当前{reason}，跳过扫描")
            return []
        
        print(f"✅ 当前扫描时段: {reason}\n")

        # 各行情源共用同一份市场新闻情绪，主源失败不影响备用源评分。
        self.news_sentiment = self.get_news_sentiment(hours=24)
        
        # 获取市场情绪
        sentiment = self.get_market_sentiment()
        self.market_sentiment = sentiment
        if sentiment:
            # 检查市场情绪是否适合建仓
            sentiment_score = sentiment.get('sentiment_score', 50)
            if sentiment_score < 30:
                print(f"⚠️ 市场情绪过于恐慌（{sentiment_score}分），建议轻仓或观望\n")
            elif sentiment_score < 50:
                print(f"📊 市场情绪偏谨慎，优选防御性板块\n")
            else:
                print(f"✅ 市场情绪良好，适合建仓\n")
        
        # 逐源降级；返回空列表也视为失败，继续尝试下一行情源。
        results = []
        quote_sources = (
            ('futu', self.scan_with_futu),
            ('tushare', self.scan_with_tushare),
            ('yahoo', self.scan_with_yahoo),
            ('longbridge', self.scan_with_longbridge),
            ('alphavantage', self.scan_with_alphavantage),
        )
        for source_name, scanner in quote_sources:
            try:
                source_results = scanner(top_n)
                if not source_results:
                    raise RuntimeError('未返回有效行情')
                results = source_results
                self.data_source = source_name
                print(f"✅ {source_name} 行情源成功: {len(results)}只有效")
                break
            except Exception as e:
                print(f"⚠️ {source_name} 行情源失败: {e}")
        if not results:
            print("❌ 所有港股行情源均失败，本轮不生成交易候选")
            return []
        
        results.sort(key=lambda x: x['base_score'], reverse=True)
        top_results = results[:top_n]
        layer2_candidates = [
            candidate for candidate in results
            if candidate.get('base_score', 0) >= LAYER2_CANDIDATE_MIN_SCORE
        ]

        self.save_results(layer2_candidates)
        
        print(f"\n✅ 扫描完成: {len(results)}/{len(self.stocks)}只有效")
        print(f"📊 高评分股票(≥70分): {len([r for r in results if r['base_score'] >= 70])}只")
        print(f"📡 数据源: {self.data_source}")
        
        return top_results
    
    @staticmethod
    def _apply_five_source_score(candidate, fs):
        """写回真实五源明细，并生成第一层90%+第二层10%的综合基础分。"""
        field_map = {
            'score_news': 'score_news',
            'score_announce': 'score_announce',
            'score_community': 'score_community',
            'score_institution': 'score_institution',
            'score_capital': 'score_capital',
            'available_news': 'available_news',
            'available_announce': 'available_announce',
            'available_community': 'available_community',
            'available_institution': 'available_institution',
            'available_capital': 'available_capital',
            'evidence_news': 'evidence_news',
            'evidence_announce': 'evidence_announce',
            'evidence_community': 'evidence_community',
            'evidence_institution': 'evidence_institution',
            'evidence_capital': 'evidence_capital',
        }
        for target, source in field_map.items():
            candidate[target] = fs.get(source)
        for field in (
            'neutral_news', 'neutral_announce', 'neutral_community',
            'neutral_institution', 'neutral_capital',
            'adjust_news', 'adjust_announce', 'adjust_community',
            'adjust_institution', 'adjust_capital',
            'neutral_total', 'score_adjustment_total', 'scoring_semantics',
        ):
            candidate[field] = fs.get(field)

        first_score = int(candidate.get('first_layer_score', candidate.get('base_score', 0)) or 0)
        if int(fs.get('available_count', 0) or 0) >= 3:
            five_source_score = int(fs.get('score_total', 0) or 0)
            coverage_mode = 'five_source_real'
        else:
            five_source_score = int(first_score * 0.8)
            coverage_mode = f"legacy_discounted (覆盖{fs.get('available_count', 0)}/5 <3)"

        candidate['five_source_total'] = int(fs.get('score_total', 0) or 0)
        candidate['four_source_total'] = candidate['five_source_total']
        candidate['five_source_available_count'] = int(fs.get('available_count', 0) or 0)
        candidate['four_source_available_count'] = candidate['five_source_available_count']
        candidate['five_source_effective_score'] = five_source_score
        candidate['combined_base_score'] = combine_layer_scores(first_score, five_source_score)
        candidate['score'] = candidate['combined_base_score']
        candidate['scoring_mode'] = f'first90_five10:{coverage_mode}'
        candidate['second_layer_news_events'] = (
            fs.get('raw', {}).get('news', {}).get('events', [])
        )

        community_raw = fs.get('raw', {}).get('community', {}) or {}
        community_total = float(community_raw.get('count', 0) or 0)
        if community_total > 0:
            candidate['community_bull_pct'] = float(community_raw.get('bull', 0) or 0) / community_total
            candidate['community_bear_pct'] = float(community_raw.get('bear', 0) or 0) / community_total
            candidate['community_post_count'] = int(round(community_total))

        capital_raw = fs.get('raw', {}).get('capital', {}) or {}
        if capital_raw:
            candidate['capital_direction'] = capital_raw.get('direction', '')
            candidate['capital_pos_hits'] = capital_raw.get('pos_hits', 0)
            candidate['capital_neg_hits'] = capital_raw.get('neg_hits', 0)
            candidate['capital_content'] = capital_raw.get('content', '')
        return candidate

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

        # 港股量能闸门：真实技术回填后、进入五源层前，对无量/量能不足的候选降分。
        # 对齐美股流动性闸门对“低量假冲高”的拦截意图，数值按港股市场口径放宽。
        for candidate in results:
            vol_ratio = candidate.get('kline_volume_ratio')
            candidates_prev_score = candidate.get('base_score', candidate.get('score', 0))
            if vol_ratio is None:
                # 拿不到真实量能：交易不可靠，压制到候选线以下，避免无依据下单
                candidate['base_score'] = min(candidates_prev_score, LAYER2_CANDIDATE_MIN_SCORE - 5)
                candidate['score'] = candidate['base_score']
                candidate['volume_gate'] = 'no_data'
                print(f"   💧 {candidate.get('symbol')}: 无真实量能数据，压到候选线以下 {candidate['base_score']}")
                continue
            if vol_ratio < HK_VOLUME_GATE_SEVERE:
                # 无量：一票否决，直接压到候选线以下，不再进入五源/交易候选
                candidate['base_score'] = min(candidates_prev_score, LAYER2_CANDIDATE_MIN_SCORE - 5)
                candidate['score'] = candidate['base_score']
                candidate['volume_gate'] = (f"无量({vol_ratio:.3f}×<{HK_VOLUME_GATE_SEVERE})，"
                                            f"一票否决压到候选线以下")
                print(f"   💧 {candidate.get('symbol')}: 量能闸门 无量({vol_ratio:.3f})，"
                      f"base_score {candidates_prev_score}→{candidate['base_score']}，禁入候选")
                continue
            elif vol_ratio < HK_VOLUME_GATE_WARN:
                penalty = HK_VOLUME_GATE_WARN_PENALTY
                reason = f"量能不足({vol_ratio:.3f}×<{HK_VOLUME_GATE_WARN})，降{penalty}分"
            else:
                candidate.setdefault('volume_gate', 'passed')
                continue
            candidate['base_score'] = max(0, candidates_prev_score - penalty)
            candidate['score'] = candidate['base_score']
            candidate['volume_gate'] = reason
            print(f"   💧 {candidate.get('symbol')}: 量能闸门 {reason}，base_score {candidates_prev_score}→{candidate['base_score']}")

        # 第二层：第一层达标候选按分数降序逐只执行真实港股五源评分。
        eligible = sorted(
            (c for c in results if c.get('base_score', 0) >= LAYER2_CANDIDATE_MIN_SCORE),
            key=lambda c: c.get('base_score', 0),
            reverse=True,
        )
        fs_map = {}
        if eligible:
            from four_source_scorer import score_all
            print(f"   🔄 港股五源第二层: {len(eligible)}只候选，单线程按第一层分数降序执行")
            for candidate in eligible:
                symbol = candidate.get('symbol', '')
                try:
                    fs_map[symbol] = score_all(symbol, 'hk', candidate.get('name', ''))
                except Exception as e:
                    print(f"   ⚠️ {symbol} 港股五源评分失败: {e}")

        # 五源综合基础分随后进入现有 LLM 验真与调整。
        llm_analyzed = []

        # 检查账户购买力，避免浪费token
        buying_power = self.get_buying_power()
        min_position = 5000
        skip_llm = buying_power < min_position
        
        if skip_llm:
            print(f"   ⚠️ 账户购买力不足(${buying_power:,.0f} < ${min_position:,})，跳过LLM分析")
        else:
            print(f"   💰 账户购买力: ${buying_power:,.0f}")
        
        # 90/10综合基础分达到70分的候选继续执行 LLM 验真。
        if not skip_llm:
            print("   🧠 LLM 验真港股90/10综合评分 >= 70 的候选")

        for candidate in results:
            first_layer_score = int(candidate.get('base_score', 0) or 0)
            candidate['first_layer_score'] = first_layer_score
            candidate['score'] = first_layer_score
            candidate['scoring_mode'] = 'hk_first_layer_only'

            fs = fs_map.get(candidate.get('symbol', ''))
            if first_layer_score >= LAYER2_CANDIDATE_MIN_SCORE and fs is None:
                candidate['final_score'] = 0
                candidate['llm_adjust'] = 0
                candidate['llm_reason'] = '港股五源评分未完成，禁止进入交易候选'
                candidate['llm_passed'] = False
                candidate['llm_status'] = 'five_source_failed'
                continue
            if fs is not None:
                self._apply_five_source_score(candidate, fs)
                print(
                    f"   ✅ {candidate.get('symbol')} 综合基础分 {candidate['score']} "
                    f"(第一层{first_layer_score}×90% + 五源"
                    f"{candidate['five_source_effective_score']}×10%，"
                    f"覆盖{candidate['five_source_available_count']}/5)"
                )

            if candidate.get('score', 0) >= 70:
                # 购买力不足时跳过LLM分析，直接用基础评分
                if skip_llm:
                    candidate['final_score'] = candidate.get('score', 70)
                    candidate['llm_adjust'] = 0
                    candidate['llm_reason'] = '购买力不足，跳过LLM分析并禁止交易'
                    candidate['llm_passed'] = False
                    candidate['llm_status'] = 'skipped_no_buying_power'
                else:
                    try:
                        sys.path.insert(0, str(STRATEGY_DIR))
                        from llm_stock_analyzer import analyze_stock
                        hk_sentiment = self.market_sentiment or {}
                        market_data = {
                            'symbol': candidate.get('symbol', ''),
                            'company_name': candidate.get('name', ''),
                            'market': 'hk',
                            'base_score': candidate.get('score', 70),
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
                            'index_membership': candidate.get('index', ''),
                            'quote_source': candidate.get('data_source', self.data_source),
                            'market_news_sentiment': self.news_sentiment,
                            'hk_sentiment_score': hk_sentiment.get('sentiment_score'),
                            'vhsi': hk_sentiment.get('vhsi'),
                            'vhsi_sentiment': hk_sentiment.get('vhsi_sentiment', ''),
                            'hk_capital_flow': hk_sentiment.get('capital_flow'),
                            'hk_flow_sentiment': hk_sentiment.get('flow_sentiment', ''),
                            'bull_bear_ratio': hk_sentiment.get('bull_bear_ratio'),
                            'warrant_sentiment': hk_sentiment.get('warrant_sentiment', ''),
                            'score_news': candidate.get('score_news', 0),
                            'score_announce': candidate.get('score_announce', 0),
                            'score_community': candidate.get('score_community', 0),
                            'score_institution': candidate.get('score_institution', 0),
                            'score_capital': candidate.get('score_capital', 0),
                            'neutral_news': candidate.get('neutral_news', 12.5),
                            'neutral_announce': candidate.get('neutral_announce', 10.0),
                            'neutral_community': candidate.get('neutral_community', 12.5),
                            'neutral_institution': candidate.get('neutral_institution', 10.0),
                            'neutral_capital': candidate.get('neutral_capital', 5.0),
                            'adjust_news': candidate.get('adjust_news'),
                            'adjust_announce': candidate.get('adjust_announce'),
                            'adjust_community': candidate.get('adjust_community'),
                            'adjust_institution': candidate.get('adjust_institution'),
                            'adjust_capital': candidate.get('adjust_capital'),
                            'scoring_semantics': candidate.get('scoring_semantics', ''),
                            'evidence_news': candidate.get('evidence_news', ''),
                            'second_layer_news_events': candidate.get('second_layer_news_events', []),
                            'available_news': candidate.get('available_news', False),
                            'available_announce': candidate.get('available_announce', False),
                            'available_community': candidate.get('available_community', False),
                            'available_institution': candidate.get('available_institution', False),
                            'available_capital': candidate.get('available_capital', False),
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
                        
                        candidate['final_score'] = llm_result.get('final_score', candidate.get('score'))
                        candidate['llm_adjust'] = llm_result.get('score_adjust', 0)
                        candidate['llm_reason'] = llm_result.get('llm_reason', '')
                        candidate['llm_passed'] = bool(llm_result.get('passed', True))
                        candidate['llm_status'] = llm_result.get('llm_status', 'parsed')
                        
                        print(f"   🧠 {candidate.get('symbol')}: 基础{candidate.get('score')} → LLM最终{candidate.get('final_score')}")
                        
                    except Exception as e:
                        print(f"   ⚠️ LLM分析失败: {e}")
                        candidate['final_score'] = candidate.get('score', 70)
                        candidate['llm_adjust'] = 0
                        candidate['llm_reason'] = f'LLM分析失败，禁止交易: {e}'
                        candidate['llm_passed'] = False
                        candidate['llm_status'] = 'failed'
            else:
                candidate['final_score'] = candidate.get('score', 70)
                candidate['llm_adjust'] = 0
                if candidate.get('score', 0) < 70:
                    candidate['llm_reason'] = ''
                candidate['llm_passed'] = True  # 低于LLM线且低于交易线，仅用于展示
            
            # 只保留最终评分>=65的
            if candidate.get('final_score', 0) >= 65:
                llm_analyzed.append(candidate)
        
        results = llm_analyzed
        
        # ===== LLM分析完成后，直接触发交易 =====
        auto_trade_min_score = STRATEGY_POLICY['hk']['min_score']
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
                tech_signals = trader.check_technical_signals(
                    symbol, market='hk', entry_score=score
                )
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
