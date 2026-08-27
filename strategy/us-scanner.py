#!/usr/bin/env python3
"""
美股扫描器（版本由 runtime_config.SYSTEM_VERSION 管理）
扫描标普500(503只) + 纳斯达克综合指数(3000+只)
数据源:Finnhub(主) / AlphaVantage(备) / 长桥(备)
扫描时间:夜盘、盘前、盘中、盘后
"""

import sys
import os
import json
import time
import threading
import requests
from datetime import datetime, date, time as dt_time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from runtime_config import (
    DATA_DIR,
    FUTU_HOST,
    FUTU_PORT,
    NEWS_DB_PATH,
    PYTHON_BIN,
    STRATEGY_DIR,
    STRATEGY_POLICY,
    SYSTEM_VERSION,
    SKILLS_DIR,
    config_path,
    load_api_keys,
)

# 仅第一层达到该分数的标的进入耗时的五源第二层；最终交易线仍由策略配置控制。
LAYER2_CANDIDATE_MIN_SCORE = 65


def in_us_extended_session():
    """是否处于美股非常规时段（盘前/盘后/夜盘）。此时常规报价冻结在收盘价，
    财报等盘后异动必须靠盘后/盘前价才能发现。"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('America/New_York'))
        t = now.hour * 60 + now.minute
        return not (9 * 60 + 30 <= t < 16 * 60)
    except Exception:
        return False


def combine_layer_scores(first_layer_score, five_source_score):
    """第一层主导总分，五源只提供10%的深度校验权重。"""
    first = float(first_layer_score or 0)
    second = float(five_source_score or 0)
    return int(round(first * 0.9 + second * 0.1))


class USScanner:
    """美股扫描器 - 支持备用数据源"""

    def __init__(self, scan_limit=None):
        # None表示无限制,扫描所有股票
        self.scan_limit = scan_limit
        self.load_api_keys()
        self.load_stock_pool(limit=self.scan_limit)
        self.load_config()
        self.data_source = 'finnhub'
        # 单股行情兜底可在完整 scan() 之前调用；完整扫描随后会加载真实新闻情绪覆盖它。
        self.news_sentiment = {}
        # Futu 行情源有额度限制，只作为最后兜底；本轮不可用时自动禁用，避免逐股反复消耗。
        self.quote_ctx = None
        self._futu_quote_disabled = False
        self._futu_lock = threading.Lock()  # 并发扫描时保护 Futu 行情上下文
        # 第一层低于门槛被丢弃的统计（含贴近门槛的标的，便于事后排查"为什么没推送"）
        self._layer1_drop_stats = {'dropped': 0, 'near_miss': []}
        self._drop_stats_lock = threading.Lock()  # 并发扫描时保护丢弃统计
        # 市场情绪指标缓存（一次扫描只算一次，避免对 5251 只股票重复调用 VIX/CNN/期权 API）
        self._sentiment_cache = None
        self._sentiment_cache_time = 0
        self._sentiment_cache_ttl = 1800  # 30 分钟过期

    def load_api_keys(self):
        """加载API密钥"""
        self.keys = load_api_keys()

        self.finnhub_key = self.keys.get('finnhub', {}).get('api_key', '')
        self.alphavantage_key = self.keys.get('alphavantage', {}).get('api_key', '')
        self.longbridge_token = self.keys.get('longbridge', {}).get('token', '')
        self.tinkclaw_key = self.keys.get('tinkclaw', {}).get('api_key', '') or os.environ.get('TINKCLAW_API_KEY', '')

    def load_stock_pool(self, limit=None):
        """加载美股成分股(标普500 + 纳斯达克综合指数),去重,可限制数量"""
        try:
            # 加载标普500和纳斯达克综合指数
            with (STRATEGY_DIR / 'us-index-constituents.json').open('r', encoding='utf-8') as f:
                data = json.load(f)

            self.sp500 = data.get('sp500', [])
            self.nasdaq = data.get('nasdaq', [])
            self.alphavantage_us = data.get('alphavantage_us', [])
            self.finnhub_us = data.get('finnhub_us', [])
            self.custom_stocks = data.get('custom', [])
            # 合并真实股票名录，同一代码只扫描一次。
            unique_symbols = list(dict.fromkeys(
                self.sp500 + self.nasdaq
                + self.alphavantage_us + self.finnhub_us + self.custom_stocks
            ))

            # 如果有限制,使用分层抽样;否则加载所有股票
            if limit and limit > 0 and len(unique_symbols) > limit:
                print(f"⚠️  限制扫描数量: {limit}只(原本{len(unique_symbols)}只)")

                # 分层抽样:按指数比例选择
                # 1. 计算每个指数的比例
                sp500_count = len(self.sp500)
                nasdaq_count = len(self.nasdaq)
                total = sp500_count + nasdaq_count

                if total > 0:
                    # 2. 按比例分配名额
                    sp500_limit = max(1, int(limit * (sp500_count / total)))
                    nasdaq_limit = max(1, limit - sp500_limit)

                    # 3. 分别选择(先选标普500,再选纳斯达克)
                    selected_symbols = []
                    selected_symbols.extend(self.sp500[:sp500_limit])

                    # 从纳斯达克中选择,避免与标普500重复
                    nasdaq_unique = [s for s in self.nasdaq if s not in selected_symbols]
                    selected_symbols.extend(nasdaq_unique[:nasdaq_limit])

                    print(f"   📊 分层抽样: 标普500({sp500_limit}只) + 纳斯达克({nasdaq_limit}只)")
                    unique_symbols = selected_symbols
                else:
                    # 如果数据异常,使用简单限制
                    unique_symbols = unique_symbols[:limit]
            else:
                print(f"✅ 完整扫描: {len(unique_symbols)}只股票")

            self.stocks = [{'symbol': s, 'name': ''} for s in unique_symbols]

            # 标记重叠
            overlap = len(set(self.sp500) & set(self.nasdaq))

            print(f"✅ 标普500: {len(self.sp500)}只")
            print(f"✅ 纳斯达克综合: {len(self.nasdaq)}只")
            print(f"✅ AlphaVantage活跃美股: {len(self.alphavantage_us)}只")
            print(f"✅ Finnhub美国交易所股票: {len(self.finnhub_us)}只")
            print(f"✅ 自定义标的: {len(self.custom_stocks)}只")
            print(f"✅ 重叠股票: {overlap}只(已去重)")
            print(f"✅ 实际扫描: {len(self.stocks)}只")
        except Exception as e:
            print(f"❌ 加载成分股失败: {e}")
            self.stocks = []
            self.sp500 = []
            self.nasdaq = []
            self.alphavantage_us = []
            self.finnhub_us = []
            self.custom_stocks = []

    def load_config(self):
        """加载策略配置"""
        with config_path('us-strategy.json').open('r', encoding='utf-8') as f:
            self.config = json.load(f)

    def get_buying_power(self):
        """获取账户可用购买力"""
        try:
            with (DATA_DIR / 'trades.json').open('r', encoding='utf-8') as f:
                data = json.load(f)
            # 尝试从账户数据获取
            for acc in data.get('accounts', []):
                if acc.get('acc_type') == 'MARGIN':
                    # 融资账户:总资产 - 持仓市值 = 净资产
                    total = acc.get('total_assets', 0)
                    market_val = acc.get('market_val', 0)
                    # 可用资金约等于净资产
                    return max(0, total - market_val * 0.3)  # 留30%buffer
            return 0
        except:
            return 0

    def get_news_sentiment(self):
        """从新闻数据库加载股票情绪,返回 dict{symbol: sentiment}"""
        sentiment_map = {}
        try:
            import sqlite3
            conn = sqlite3.connect(NEWS_DB_PATH)
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
            pass  # 静默失败,使用默认中性
        return sentiment_map

    def should_scan(self):
        """判断是否应该扫描

        策略：美股 24 小时全天扫描，仅非交易日跳过。
        “非交易日”含义：周末、美股节假日。其余时间都会扫，拿到什么算什么。
        """
        now = datetime.now()
        current_time = now.time()

        # 仅以交易日为判断依据，无论盘中/盘后/盘前都扫
        try:
            from trading_calendar import TradingCalendar
            calendar = TradingCalendar()
            is_trading_day, reason = calendar.is_us_trading_day(now)
            if not is_trading_day:
                return False, f"非交易日 ({reason})"
        except Exception:
            pass  # 交易日历不可用 → 默认扫描，不丢过机会

        # 返回详细的市场阶段标签（仅供日志用）
        if current_time >= dt_time(21, 0):
            label = "盘中"
        elif current_time <= dt_time(4, 0):
            label = "盘中"
        elif dt_time(4, 0) <= current_time <= dt_time(7, 59):
            label = "盘后"
        elif dt_time(8, 0) <= current_time <= dt_time(16, 59):
            label = "休市 (24h扫描)"
        else:
            label = "盘前"
        return True, label

    def calculate_score(self, price, prev_close, change_pct, news_sentiment=None):
        """计算评分(包含技术面和市场情绪)"""
        score = 60

        # 1. 技术面评分(~40%)
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

        # 2. 市场情绪综合评分(~20-25%)
        emotion_score = self.calculate_market_sentiment(news_sentiment)
        score += emotion_score

        # 第一层仅用于初筛与候选排序；五源评分会在第二层接管交易候选的基础分。
        return min(90, max(0, score))

    def calculate_market_sentiment(self, news_sentiment=None):
        """市场情绪综合评分
        
        权重分配:
        - 新闻情绪: 40%
        - VIX恐慌指数: 30%
        - CNN恐慌贪婪: 20%
        - 期权比例: 10%
        
        返回: +/-15分范围
        
        性能优化：VIX/CNN/期权 都是市场级别指标，一次扫描只算一次，结果缓存 30 分钟
        避免对 5251 只股票重复调用同一个 API（API 限流 + 垃圾日志污染）
        """
        import time as _time
        # 1. 新闻情绪是每只股票独有的，必须每次重算
        news_part = 0
        if news_sentiment:
            if news_sentiment > 0.6:  # 正面新闻
                news_part = 6  # +15*0.4
            elif news_sentiment < 0.4:  # 负面新闻
                news_part = -4  # -10*0.4

        # 2. 市场级别指标从缓存拿
        now = _time.time()
        if self._sentiment_cache is None or (now - self._sentiment_cache_time) > self._sentiment_cache_ttl:
            market_part = 0
            try:
                vix = self.get_vix_realtime()
                if vix >= 30:
                    market_part -= 9
                elif vix >= 25:
                    market_part -= 5
                elif vix <= 15:
                    market_part += 6
            except Exception:
                pass
            try:
                cnn_score = self.get_cnn_fear_greed_realtime()
                if cnn_score <= 25:
                    market_part -= 4
                elif cnn_score >= 75:
                    market_part += 3
            except Exception:
                pass
            _opt_ok = False
            try:
                option_ratio = self.get_option_ratio_realtime()
                if option_ratio >= 1.2:
                    market_part += 1.5
                elif option_ratio <= 0.8:
                    market_part -= 1.5
                _opt_ok = True
            except Exception:
                pass
            # 期权P/C获取失败时，用衍生品异动作为备用源
            if not _opt_ok:
                try:
                    deriv = self._check_derivatives_sentiment_fallback()
                    if deriv:
                        market_part += deriv
                except Exception:
                    pass
            self._sentiment_cache = market_part
            self._sentiment_cache_time = now
            print(f"   📈 市场情绪缓存已更新: 市场级加减 {market_part:+.1f} (TTL=30min)")

        return news_part + self._sentiment_cache

    def get_vix_realtime(self):
        """获取实时VIX数据"""
        try:
            import requests
            url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get('chart', {}).get('result', [])
                if result:
                    meta = result[0].get('meta', {})
                    price = meta.get('regularMarketPrice', 20)
                    if price and price > 0:
                        return float(price)
        except Exception as e:
            print(f"⚠️ 获取VIX失败: {e}")
        return 20.0  # 默认返回中性值

    def get_cnn_fear_greed_realtime(self):
        """获取实时CNN恐慌贪婪指数"""
        try:
            import requests
            from datetime import datetime
            
            date_str = datetime.now().strftime("%Y-%m-%d")
            url = f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{date_str}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Origin': 'https://edition.cnn.com',
                'Referer': 'https://edition.cnn.com/markets/fear-and-greed'
            }
            
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if 'fear_and_greed' in data:
                    score = data['fear_and_greed'].get('score', 50)
                    return float(score)
        except Exception as e:
            print(f"⚠️ 获取CNN失败: {e}")
        return 50.0  # 默认返回中性值

    def get_option_ratio_realtime(self):
        """获取实时期权比例
        
        使用标普500 ETF (SPY) 的期权比例作为市场情绪参考
        """
        try:
            if not self.quote_ctx:
                return 1.0  # 中性
            
            from futu import OptionType
            
            # 获取SPY期权链
            ret, data = self.quote_ctx.get_option_chain('US.SPY')
            if ret != 0 or not data:
                return 1.0
            
            call_volume = 0
            put_volume = 0
            
            for option in data:
                option_type = option.get('option_type', '')
                volume = option.get('volume', 0) or 0
                
                if option_type == OptionType.CALL:
                    call_volume += volume
                elif option_type == OptionType.PUT:
                    put_volume += volume
            
            if put_volume > 0:
                return call_volume / put_volume
            return 1.0
        except Exception as e:
            print(f"⚠️ 获取期权比例失败: {e}")
        return 1.0  # 默认返回中性值

    def _check_derivatives_sentiment_fallback(self):
        """衍生品异动作为期权P/C的备用源（futu-derivatives-anomaly skill）。

        调 futu-derivatives-anomaly 脚本拿衍生品异动文本，
        按关键词判断看多/看空，返回市场情绪调整值。
        看多 +1.5 / 看空 -1.5 / 中性或失败 0
        """
        import subprocess, json as _json
        FUTU_DERIV_SCRIPT = str(SKILLS_DIR / 'futu-derivatives-anomaly/scripts/handle_derivatives_anomaly.py')
        FUTU_PY = str(PYTHON_BIN)
        _POS = ['看涨期权大单', '做多', '牛证', '看多情绪', '反弹机会', '看涨']
        _NEG = ['看跌期权大单', '看空情绪', '熊证', '看跌期权活跃度', '阻力位', '看跌']
        try:
            proc = subprocess.run(
                [FUTU_PY, FUTU_DERIV_SCRIPT, 'US.SPY', '--time-range', '7', '--json'],
                capture_output=True, text=True, timeout=20,
            )
            if proc.returncode != 0:
                return 0
            stdout = proc.stdout.strip()
            json_start = stdout.find('{')
            if json_start < 0:
                return 0
            payload, _end = _json.JSONDecoder().raw_decode(stdout[json_start:])
            data = payload.get('data') or {}
            if str(data.get('err_code', -1)) != '0':
                return 0
            content = data.get('content') or ''
            if not content:
                return 0
            low = content.lower()
            pos_hits = sum(1 for w in _POS if w in low)
            neg_hits = sum(1 for w in _NEG if w in low)
            if neg_hits > pos_hits:
                print(f"   📉 衍生品异动备用源: 看空 (正{pos_hits}/负{neg_hits})")
                return -1.5
            elif pos_hits > neg_hits:
                print(f"   📈 衍生品异动备用源: 看多 (正{pos_hits}/负{neg_hits})")
                return 1.5
            return 0
        except Exception:
            return 0

    def _build_quote_candidate(self, symbol, price, prev_close, change_pct, data_source):
        """把单股报价统一转换为第一层候选结构。"""
        try:
            price_float = float(price or 0)
            prev_close_float = float(prev_close or 0)
            change_pct_float = float(change_pct or 0)
        except Exception:
            return None

        if price_float <= 0 or prev_close_float <= 0 or price_float < 0.1:
            return None

        stock_sentiment = self.news_sentiment.get(symbol)
        score = self.calculate_score(price_float, prev_close_float, change_pct_float, stock_sentiment)
        if score < LAYER2_CANDIDATE_MIN_SCORE:
            with self._drop_stats_lock:
                stats = self._layer1_drop_stats
                stats['dropped'] += 1
                stats['near_miss'].append((score, symbol))
                stats['near_miss'].sort(reverse=True)
                del stats['near_miss'][3:]
            return None

        index = ""
        if symbol in self.sp500:
            index = "标普500"
        if symbol in self.nasdaq:
            index += "纳斯达克" if not index else "+纳斯达克"

        return {
            'symbol': symbol,
            'name': '',
            'price': price_float,
            'prev_close': prev_close_float,
            'change_pct': round(change_pct_float, 2),
            'base_score': score,
            'score': score,
            'index': index,
            'data_source': data_source,
            'timestamp': datetime.now().isoformat()
        }

    def _fetch_single_quote_finnhub(self, symbol, timeout=2):
        if not self.finnhub_key:
            return None
        url = f'https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}'
        res = requests.get(url, timeout=timeout)
        if res.status_code != 200:
            return None
        data = res.json()
        return self._build_quote_candidate(symbol, data.get('c'), data.get('pc'), data.get('dp'), 'finnhub')

    def _fetch_single_quote_alphavantage(self, symbol, timeout=2):
        if not self.alphavantage_key:
            return None
        url = f'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={self.alphavantage_key}'
        res = requests.get(url, timeout=timeout)
        if res.status_code != 200:
            return None
        quote = res.json().get('Global Quote', {})
        raw_change = str(quote.get('10. change percent', '0')).replace('%', '')
        return self._build_quote_candidate(
            symbol,
            quote.get('05. price'),
            quote.get('08. previous close'),
            raw_change,
            'alphavantage_single'
        )

    def _fetch_single_quote_yfinance(self, symbol, timeout=2):
        # yfinance 没有简单的 per-request timeout 参数，这里用 query1 chart 接口做单股兜底。
        # includePrePost=true 时K线带盘后/盘前成交；非常规时段常规价冻结在收盘价，
        # 财报夜的盘后异动（如 NVDA +4.7%）只有这里能看到。
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        res = requests.get(
            url,
            params={'range': '1d', 'interval': '5m', 'includePrePost': 'true'},
            headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'},
            timeout=timeout,
        )
        if res.status_code != 200:
            return None
        result = (res.json().get('chart', {}).get('result') or [None])[0]
        if not result:
            return None
        meta = result.get('meta', {})
        price = meta.get('regularMarketPrice')
        prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
        if price is None or prev_close in (None, 0):
            return None

        if in_us_extended_session():
            # 盘后/盘前价以最近一次常规收盘价为基准，与富途的 after/pre_change_rate 口径一致。
            # 盘前窗口(ET 4:00-9:30)优先 preMarketPrice，避免残留的前日盘后价盖掉新鲜盘前价。
            post_p, pre_p = meta.get('postMarketPrice'), meta.get('preMarketPrice')
            try:
                from zoneinfo import ZoneInfo
                _et_now = datetime.now(ZoneInfo('America/New_York'))
                _et_min = _et_now.hour * 60 + _et_now.minute
            except Exception:
                _et_min = -1
            in_pre_window = 240 <= _et_min < 570
            if in_pre_window:
                ext_price = pre_p or post_p
                ext_label = '盘前' if pre_p else ('盘后' if post_p else None)
            else:
                ext_price = post_p or pre_p
                ext_label = '盘后' if post_p else ('盘前' if pre_p else None)
            if ext_price is None:
                quotes = (result.get('indicators', {}).get('quote') or [{}])[0]
                closes = [c for c in (quotes.get('close') or []) if c is not None]
                # 最后一根K线与常规收盘价偏差>0.5%视为存在扩展时段成交（夜盘时为盘后收盘价）
                if closes and abs(float(closes[-1]) - float(price)) / float(price) > 0.005:
                    ext_price = closes[-1]
                    ext_label = ext_label or '盘后'
            try:
                ext_price = float(ext_price) if ext_price is not None else None
            except (TypeError, ValueError):
                ext_price = None
            if ext_price and ext_price > 0:
                change_pct = (ext_price - float(price)) / float(price) * 100
                candidate = self._build_quote_candidate(symbol, ext_price, price, change_pct, 'yfinance')
                if candidate:
                    candidate['price_type'] = ext_label or '扩展'
                return candidate

        change_pct = (float(price) - float(prev_close)) / float(prev_close) * 100
        return self._build_quote_candidate(symbol, price, prev_close, change_pct, 'yfinance_single')

    def _fetch_single_quote_longbridge(self, symbol, timeout=2):
        if not self.longbridge_token:
            return None
        url = 'https://openapi.longbridgeapp.com/v1/quote'
        headers = {
            'Authorization': f'Bearer {self.longbridge_token}',
            'Content-Type': 'application/json',
        }
        params = {
            'symbol': [symbol],
            'what': 'latest_price,previous_close,change_percent',
        }
        res = requests.get(url, headers=headers, params=params, timeout=timeout)
        if res.status_code != 200:
            return None
        for item in res.json().get('data', []):
            quote = item.get('quote', {})
            price = quote.get('latest_price', {}).get('value')
            prev_close = quote.get('previous_close', {}).get('value')
            change_pct = quote.get('change_percent', {}).get('value')
            candidate = self._build_quote_candidate(symbol, price, prev_close, change_pct, 'longbridge_single')
            if candidate:
                return candidate
        return None

    def _get_futu_quote_ctx(self):
        with self._futu_lock:
            if self._futu_quote_disabled:
                return None
            if self.quote_ctx:
                return self.quote_ctx
            try:
                from futu import OpenQuoteContext
                self.quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
                return self.quote_ctx
            except Exception as e:
                self._futu_quote_disabled = True
                print(f"      ⚠️ Futu行情源不可用，本轮不再尝试: {e}")
                return None

    def _fetch_single_quote_futu(self, symbol, timeout=2):
        ctx = self._get_futu_quote_ctx()
        if not ctx:
            return None
        try:
            from futu import RET_OK
            full_symbol = symbol if str(symbol).startswith('US.') else f'US.{symbol}'
            # Futu OpenQuoteContext 不保证线程安全；只允许一个工作线程同时调用。
            with self._futu_lock:
                ret, snapshot = ctx.get_market_snapshot([full_symbol])
            if ret != RET_OK or snapshot is None or len(snapshot) == 0:
                return None
            row = snapshot.iloc[0]
            price = row.get('last_price') or row.get('cur_price')
            prev_close = row.get('prev_close_price') or row.get('prev_close')
            change_pct = row.get('change_rate')
            # 部分美股快照没有 change_rate，或返回 NaN；同一份行情有现价与昨收时直接推导。
            try:
                change_valid = change_pct is not None and float(change_pct) == float(change_pct)
            except (TypeError, ValueError):
                change_valid = False
            if not change_valid and price and prev_close:
                change_pct = (float(price) - float(prev_close)) / float(prev_close) * 100
            return self._build_quote_candidate(symbol.replace('US.', ''), price, prev_close, change_pct, 'futu')
        except Exception:
            return None

    def fetch_single_quote_with_fallbacks(self, symbol, per_source_timeout=2, per_symbol_budget=10):
        """单股逐源兜底：所有可用源都试过才放弃，但受单股总预算限制。"""
        started = time.time()
        sources = (
            ('finnhub', self._fetch_single_quote_finnhub),
            ('alphavantage', self._fetch_single_quote_alphavantage),
            ('yfinance', self._fetch_single_quote_yfinance),
            ('longbridge', self._fetch_single_quote_longbridge),
            ('futu', self._fetch_single_quote_futu),
        )
        for source_name, fetcher in sources:
            if time.time() - started >= per_symbol_budget:
                break
            try:
                quote = fetcher(symbol, timeout=per_source_timeout)
                if quote:
                    if source_name != 'finnhub':
                        print(f"      ↪ {symbol}: Finnhub失败，使用{source_name}兜底")
                    return quote
            except Exception:
                continue
        return None

    def scan_with_finnhub(self, top_n=50, time_budget_seconds=2040, max_workers=3):
        """使用Finnhub扫描。第一层动态预算，默认最多约34分钟，给第二层保底25分钟。
        支持多线程并发扫描加速（max_workers），超时后返回已扫到的结果。"""
        print(f"  使用数据源: Finnhub (时间预算 {time_budget_seconds//60} 分钟, 并发{max_workers})")

        results = []
        total = len(self.stocks)
        if total == 0:
            return results
        start_time = time.time()
        self._layer1_drop_stats = {'dropped': 0, 'near_miss': []}
        self._drop_stats_lock = threading.Lock()
        stop_event = threading.Event()
        progress = {'done': 0}
        progress_lock = threading.Lock()

        def worker(chunk):
            """工作线程：扫描分配到的股票块，受 stop_event 控制提前退出。"""
            local_results = []
            for stock in chunk:
                if stop_event.is_set():
                    break
                try:
                    symbol = stock['symbol']
                    candidate = self.fetch_single_quote_with_fallbacks(
                        symbol,
                        per_source_timeout=2,
                        per_symbol_budget=10,
                    )
                    if candidate:
                        local_results.append(candidate)
                except Exception:
                    continue
                time.sleep(0.05)  # 保持 API 礼貌，避免触发限流
                with progress_lock:
                    progress['done'] += 1
                    done = progress['done']
                if done % 100 == 0:
                    elapsed = time.time() - start_time
                    print(f"    进度: {done}/{total} ({elapsed/60:.1f}分钟)")
            return local_results

        # 将股票池均匀切片为 max_workers 块（轮流分配，保证两类指数均匀）
        chunks = [self.stocks[i::max_workers] for i in range(max_workers)]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, chunk) for chunk in chunks]
            # 监控总预算：超时就通知所有工作线程停止
            while not all(f.done() for f in futures):
                if time.time() - start_time > time_budget_seconds:
                    stop_event.set()
                    break
                time.sleep(0.1)
            for f in futures:
                try:
                    results.extend(f.result())
                except Exception:
                    pass

        elapsed = time.time() - start_time
        scanned = progress['done']
        print(f"    Finnhub扫描完成: {len(results)}/{total}只有效 "
              f"({scanned}只已扫描, {elapsed/60:.1f}分钟)")
        drop_stats = self._layer1_drop_stats
        near_miss = ', '.join(f"{sym}({sc}分)" for sc, sym in drop_stats['near_miss'])
        print(f"    🗑️ 第一层评分<{LAYER2_CANDIDATE_MIN_SCORE}丢弃 {drop_stats['dropped']} 次"
              f"(逐源计数)；贴近门槛Top3: {near_miss or '无'}")
        return results

    def scan_with_alphavantage(self, top_n=50, time_budget_seconds=1200):
        """使用AlphaVantage扫描(备用)。时间预算20分钟。"""
        print(f"  使用数据源: AlphaVantage(备用, 时间预算 {time_budget_seconds//60} 分钟)")

        results = []
        total = len(self.stocks)
        start_time = time.time()

        for i, stock in enumerate(self.stocks):
            elapsed = time.time() - start_time
            if elapsed > time_budget_seconds:
                print(f"    ⏰ 时间预算耗尽({elapsed/60:.1f}分钟)，已扫描{i}/{total}只")
                break

            try:
                symbol = stock['symbol']
                if (i + 1) % 50 == 0:
                    print(f"    进度: {i+1}/{total} ({elapsed/60:.1f}分钟)")

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

                        if score >= LAYER2_CANDIDATE_MIN_SCORE:
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
        """使用yfinance批量获取(主数据源)"""
        try:
            import yfinance as yf
        except ImportError:
            print("❌ yfinance未安装,无法使用批量获取")
            return []

        # 总是扫描所有股票,top_n只用于结果过滤
        # self.stocks是字典列表,需要提取symbol
        scan_symbols = [stock['symbol'] for stock in self.stocks]

        print(f"📡 使用yfinance批量扫描: {len(scan_symbols)}只股票")

        results = []
        batch_size = 100  # 分批获取,避免一次请求太多

        for i in range(0, len(scan_symbols), batch_size):
            batch = scan_symbols[i:i+batch_size]
            batch_num = i//batch_size + 1
            print(f"   🔄 批次 {batch_num}/{len(scan_symbols)//batch_size + 1}: {len(batch)}只股票")

            # 添加延迟,避免API限制
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
                            # 盘后/盘前价格(如果有)
                            post_price = info.get('postMarketPrice') or info.get('postMarketChange', 0)
                            pre_price = info.get('preMarketPrice') or info.get('preMarketChange', 0)

                            # 优先使用盘后/盘前价格(如果存在且非0)
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

                                if score >= LAYER2_CANDIDATE_MIN_SCORE:
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
                                        'trailing_pe': info.get('trailingPE'),
                                        'forward_pe': info.get('forwardPE'),
                                        'revenue_growth': (info.get('revenueGrowth') * 100 if isinstance(info.get('revenueGrowth'), (int, float)) else None),
                                        'earnings_growth': (info.get('earningsGrowth') * 100 if isinstance(info.get('earningsGrowth'), (int, float)) else None),
                                        'profit_margin': (info.get('profitMargins') * 100 if isinstance(info.get('profitMargins'), (int, float)) else None),
                                        'trailing_eps': info.get('trailingEps'),
                                        'sector': info.get('sector', ''),
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
                    print(f"   ⏸️  API限制,等待5秒后重试单个获取...")
                    time.sleep(5)

                # 如果批量失败,尝试单个获取(带延迟)
                single_success = 0
                for idx, symbol in enumerate(batch):
                    try:
                        # 单个请求间添加延迟
                        if idx > 0:
                            time.sleep(0.5)

                        ticker = yf.Ticker(symbol)
                        info = ticker.info

                        if info:
                            # 盘后/盘前价格(如果有)
                            post_price = info.get('postMarketPrice') or info.get('postMarketChange', 0)
                            pre_price = info.get('preMarketPrice') or info.get('preMarketChange', 0)

                            # 优先使用盘后/盘前价格(如果存在且非0)
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

                                if score >= LAYER2_CANDIDATE_MIN_SCORE:
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
                                        'trailing_pe': info.get('trailingPE'),
                                        'forward_pe': info.get('forwardPE'),
                                        'revenue_growth': (info.get('revenueGrowth') * 100 if isinstance(info.get('revenueGrowth'), (int, float)) else None),
                                        'earnings_growth': (info.get('earningsGrowth') * 100 if isinstance(info.get('earningsGrowth'), (int, float)) else None),
                                        'profit_margin': (info.get('profitMargins') * 100 if isinstance(info.get('profitMargins'), (int, float)) else None),
                                        'trailing_eps': info.get('trailingEps'),
                                        'sector': info.get('sector', ''),
                                        'volume': info.get('regularMarketVolume'),
                                        'timestamp': datetime.now().isoformat()
                                    })
                    except:
                        continue

        print(f"✅ yfinance扫描完成: 找到 {len(results)} 个机会")

        # 检查是否获取到有效数据,如果没有则触发备用数据源
        if len(results) == 0:
            raise Exception("yfinance未获取到任何有效数据,触发备用数据源")

        return results

    def scan_with_tinkclaw(self, top_n=50):
        """使用TinkClaw AI交易信号(智能备用)"""
        if not self.tinkclaw_key:
            print("⚠️  TinkClaw API密钥未配置,跳过")
            return []

        try:
            import requests
            import json
        except ImportError:
            print("❌ 缺少requests库,无法使用TinkClaw")
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

                        # 第一层仅用于初筛与候选排序；五源评分会在第二层接管交易候选的基础分。
                        final_score = max(0, min(90, base_score))

                        if final_score >= LAYER2_CANDIDATE_MIN_SCORE:
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

                # TinkClaw免费版限制(10次/天),需要控制频率
                time.sleep(1)

            except Exception as e:
                print(f"   ⚠️  {symbol} TinkClaw失败: {e}")
                continue

        print(f"✅ TinkClaw扫描完成: 找到 {len(results)} 个AI信号机会")
        return results

    def scan(self, top_n=50, max_workers=3):
        """扫描美股市场"""
        self._scan_max_workers = max_workers
        total_budget_seconds = 59 * 60
        min_layer2_seconds = 25 * 60
        scan_started_at = time.time()
        self._scan_deadline = scan_started_at + total_budget_seconds
        layer1_budget_seconds = max(60, total_budget_seconds - min_layer2_seconds)
        print(f"\n{'='*60}")
        print(f"🇺🇸 美股扫描器 {SYSTEM_VERSION}")
        print(f"{'='*60}")
        print(f"股票池: 标普500({len(self.sp500)}只) + 纳斯达克({len(self.nasdaq)}只) = {len(self.stocks)}只")
        print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"扫描时段: 夜盘 | 盘前 | 盘中 | 盘后")
        print(f"{'='*60}\n")

        should, reason = self.should_scan()
        if not should:
            print(f"⏸️ 当前{reason},跳过扫描")
            return []

        print(f"✅ 当前扫描时段: {reason}\n")

        # 先获取新闻情绪(五源共振-国际资讯25%)
        self.news_sentiment = self.get_news_sentiment()
        sentiment_count = len(self.news_sentiment)
        if sentiment_count > 0:
            print(f"   📰 新闻情绪: 已加载 {sentiment_count} 只股票的情绪数据")
        else:
            print(f"   📰 新闻情绪: 无数据")

        # 尝试主数据源 - Finnhub(快,实时)
        try:
            results = self.scan_with_finnhub(top_n, time_budget_seconds=layer1_budget_seconds, max_workers=max_workers)
            self.data_source = 'finnhub'
            print(f"✅ Finnhub数据源成功")
        except Exception as e:
            print(f"⚠️ Finnhub数据源失败: {e}")
            print(f"  切换到备用数据源...")

            # 第一备用:AlphaVantage
            try:
                results = self.scan_with_alphavantage(top_n)
                self.data_source = 'alphavantage'
                print(f"✅ AlphaVantage备用数据源成功")
            except Exception as e2:
                print(f"⚠️ AlphaVantage备用也失败: {e2}")
                print(f"  切换到第二备用数据源...")

                # 第二备用:yfinance批量获取(慢但数据全)
                try:
                    results = self.scan_with_yfinance(top_n)
                    self.data_source = 'yfinance'
                    print(f"✅ yfinance备用数据源成功")
                except Exception as e3:
                    print(f"⚠️ yfinance备用也失败: {e3}")
                    print(f"  切换到第三备用数据源...")

                    # 第三备用:TinkClaw AI信号
                    try:
                        results = self.scan_with_tinkclaw(top_n)
                        self.data_source = 'tinkclaw'
                        print(f"✅ TinkClaw AI信号备用成功")
                    except Exception as e4:
                        print(f"⚠️ TinkClaw备用也失败: {e4}")
                        print(f"  尝试长桥作为最后备用...")

                        # 第四备用:长桥
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
        # 所有第一层评分达到候选线的标的进入五源深度评分；LLM 仍只处理五源 Top 20。
        all_candidates = results

        self.save_results(all_candidates)

        display_results = [
            r for r in all_candidates
            if r.get('final_score', r.get('score', r.get('base_score', 0))) >= 65
        ]
        display_results.sort(
            key=lambda x: x.get('final_score', x.get('score', x.get('base_score', 0))),
            reverse=True,
        )

        print(f"\n✅ 扫描完成: 扫描{len(self.stocks)}只,获得{len(results)}个有效机会")
        print(f"📊 最终高评分股票(≥70分): {len([r for r in display_results if r.get('final_score', r.get('score', 0)) >= 70])}只")
        print(f"📡 数据源: {self.data_source}")

        return display_results[:top_n]

    def _flush_opportunities(self, analyzed, partial=True):
        """增量保存 us-opportunities.json。任何时刻被调用都能安全落盘。

        Args:
            analyzed: 已完成（包含/不含LLM）的候选列表
            partial: True=中间快照；False=本次扫描全部完成
        """
        # 过滤出最终评分 >=65 的、有效机会
        valid = [c for c in analyzed if c.get('final_score', c.get('score', 0)) >= 65]
        # 按 final_score 降序
        valid.sort(key=lambda x: x.get('final_score', x.get('score', 0)), reverse=True)

        data = {
            'market': 'US',
            'last_scan': datetime.now().isoformat(),
            'data_source': getattr(self, 'data_source', 'unknown'),
            'total_scanned': len(getattr(self, 'stocks', [])),
            'analyzed_count': len(analyzed),
            'partial': partial,
            'stock_pool': {
                'sp500': len(getattr(self, 'sp500', [])),
                'nasdaq': len(getattr(self, 'nasdaq', [])),
                'total': len(getattr(self, 'stocks', [])),
            },
            'opportunities': valid,
        }

        path = DATA_DIR / 'us-opportunities.json'
        tmp_path = str(path) + '.tmp'
        try:
            os.makedirs(os.path.dirname(str(path)), exist_ok=True)
            # 先写 tmp 再 rename，避免写到一半被kill后文件损坏
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
            tag = '快照' if partial else '完成'
            print(f"   💾 增量保存({tag}): 已分析{len(analyzed)}只/有效{len(valid)}只")
        except Exception as e:
            print(f"   ⚠️ 增量保存失败: {e}")

    def save_results(self, results):
        """保存扫描结果(加入LLM分析)"""

        # 调用LLM分析
        llm_analyzed = []

        # === 保命机制：被kill/Ctrl+C时 flush 已分析部分 ===
        import signal as _signal

        def _emergency_flush(signum, frame):
            print(f"\n⚠️ 收到信号 {signum}，紧急 flush 已分析数据...")
            try:
                self._flush_opportunities(llm_analyzed, partial=True)
            finally:
                _signal.signal(signum, _signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        for _sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(_sig, _emergency_flush)
            except Exception:
                pass

        # 检查账户购买力,避免浪费token
        buying_power = self.get_buying_power()
        # 单票仓位约12%,最小买入金额约$5000
        min_position = 5000
        skip_llm = buying_power < min_position

        # 🎯 五源补算覆盖候选池；LLM 在五源评分完成后再处理真实评分 Top 20
        TOP_LLM_N = 20
        if not skip_llm:
            print(f"   🧠 LLM 将在五源评分后处理真实评分 Top {TOP_LLM_N}")

        if skip_llm:
            print(f"   ⚠️ 账户购买力不足(${buying_power:,.0f} < ${min_position:,}),跳过LLM分析")
        else:
            print(f"   💰 账户购买力: ${buying_power:,.0f}")

        # 加载新闻情绪
        news_sentiment = self.get_news_sentiment()
        sentiment_count = len(news_sentiment)
        if sentiment_count > 0:
            print(f"   📰 新闻情绪: 已加载 {sentiment_count} 只股票的情绪数据")
        else:
            print(f"   📰 新闻情绪: 无数据")

        # 第二层时间预算：使用总预算剩余时间。
        # scan() 总预算 59 分钟，第一层动态运行但给第二层保底 25 分钟；cron 60 分钟只做硬上限。
        layer2_start = time.time()
        deadline = getattr(self, '_scan_deadline', layer2_start + 25 * 60)
        layer2_budget = max(0, int(deadline - layer2_start))
        print(f"   ⏱️ 第二层剩余预算: {layer2_budget//60}分{layer2_budget%60}秒")

        # === 第二层 Phase 1: 并行跑五源评分（最耗时，每个候选 5 次 Futu API）===
        # 先并行把 score_all 算完，Phase 2 再顺序做新闻情绪注入/LLM/flush，避免串行瓶颈
        def _prefetch_fs(candidate):
            symbol_raw = (candidate.get('symbol') or '').replace('US.', '')
            if candidate.get('score', 0) < LAYER2_CANDIDATE_MIN_SCORE:
                return symbol_raw, None
            try:
                sys.path.insert(0, str(STRATEGY_DIR))
                from four_source_scorer import score_all as _fs_score_all
                fs = _fs_score_all(symbol_raw, 'us', candidate.get('name', ''))
                return symbol_raw, fs
            except Exception as e:
                print(f"   ⚠️ {symbol_raw} 五源评分失败: {e}")
                return symbol_raw, None

        fs_map = {}
        eligible = sorted(
            (c for c in results
             if c.get('score', 0) >= LAYER2_CANDIDATE_MIN_SCORE),
            key=lambda c: c.get('score', 0),
            reverse=True,
        )
        layer2_workers = getattr(self, '_scan_max_workers', 3)
        if layer2_budget >= 12 * 60:
            finalize_reserve = min(6 * 60, max(60, layer2_budget // 4))
        else:
            finalize_reserve = max(2, layer2_budget // 3)
        prefetch_deadline = deadline - finalize_reserve
        print(f"   🔄 并行五源评分中: {len(eligible)}只候选 (并发{layer2_workers}, 预留收尾{finalize_reserve//60}分{finalize_reserve%60}秒)")
        _ex = ThreadPoolExecutor(max_workers=layer2_workers)
        pending = {_ex.submit(_prefetch_fs, candidate) for candidate in eligible}
        try:
            while pending:
                remaining = prefetch_deadline - time.time()
                if remaining <= 0:
                    print(f"   ⏰ 五源预取时间到，已完成{len(fs_map)}只，取消{len(pending)}个未完成任务，进入LLM/保存阶段")
                    break
                done, pending = wait(
                    pending,
                    timeout=min(1.0, remaining),
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    try:
                        _sym, _fs = future.result()
                        if _fs is not None:
                            fs_map[_sym] = _fs
                    except Exception:
                        pass
        finally:
            for future in pending:
                future.cancel()
            # 不等待仍处于网络调用中的线程，立即进入 LLM/保存阶段并释放 cron 锁。
            _ex.shutdown(wait=False, cancel_futures=True)

        llm_ranked_symbols = []
        if not skip_llm:
            ranked_for_llm = []
            for candidate in results:
                symbol_raw = (candidate.get('symbol') or '').replace('US.', '')
                fs = fs_map.get(symbol_raw)
                if not fs:
                    continue
                first_score = candidate.get('score', 70)
                five_source_score = (
                    fs['score_total'] if fs['available_count'] >= 3
                    else int(first_score * 0.8)
                )
                score_for_rank = combine_layer_scores(first_score, five_source_score)
                ranked_for_llm.append((score_for_rank, symbol_raw))
        ranked_for_llm.sort(key=lambda x: x[0], reverse=True)
        llm_ranked_symbols = [sym for _, sym in ranked_for_llm[:TOP_LLM_N]]
        print(f"   🧠 LLM 实际处理90/10综合分 Top {TOP_LLM_N}: {llm_ranked_symbols}")
        # 2026-08-20 east 铁律：只有 Top N 走 LLM；名单外 llm_passed=False 禁单（不再强制补验）
        top_llm_set = set(llm_ranked_symbols)
        llm_tech = None
        if top_llm_set:
            try:
                from technical_indicators_us import USTechIndicators
                llm_tech = USTechIndicators()
            except Exception as e:
                print(f"   ⚠️ LLM技术摘要模块不可用: {e}")
        if top_llm_set:
            llm_order = {symbol: idx for idx, symbol in enumerate(llm_ranked_symbols)}
            top_candidates = sorted(
                [c for c in results if (c.get('symbol') or '').replace('US.', '') in top_llm_set],
                key=lambda c: llm_order.get((c.get('symbol') or '').replace('US.', ''), len(llm_order)),
            )
            remaining_candidates = [
                c for c in results if (c.get('symbol') or '').replace('US.', '') not in top_llm_set
            ]
            results = top_candidates + remaining_candidates

        for idx, candidate in enumerate(results):
            # 第二层总截止检查：五源预取已预留收尾时间，这里只防止越过 cron 硬上限。
            remaining_total = deadline - time.time()
            stop_guard = 10 if layer2_budget >= 60 else 1
            if remaining_total <= stop_guard:
                l2_elapsed = time.time() - layer2_start
                print(f"   ⏰ 第二层总预算接近耗尽({l2_elapsed/60:.1f}分钟)，已分析{len(llm_analyzed)}只，flush保存")
                break
            try:
                # 注入新闻情绪到候选股票
                symbol = candidate.get('symbol', '').replace('US.', '')
                if symbol in news_sentiment:
                    candidate['sentiment'] = news_sentiment[symbol]
                    # 用新闻情绪重新调整基础评分
                    sentiment_val = news_sentiment[symbol]
                    base = candidate.get('base_score', candidate.get('score', 60))
                    if sentiment_val > 0.6:  # 正面新闻
                        # 2026-06-19 east 修复 Bug1: 正面新闻加分也不能越过 90，预留 LLM 调整空间
                        base = min(90, base + 15)
                    elif sentiment_val < 0.4:  # 负面新闻
                        base = max(0, base - 10)
                    candidate['base_score'] = base
                    candidate['score'] = base
                candidate['first_layer_score'] = candidate.get('score', 0)
                # 候选池内统一跑真实五源评分；LLM 仍只处理 TopN 名单
                # 五源评分已在 Phase 1 并行算完，这里直接从 fs_map 取，不再串行调 API
                symbol_raw = (candidate.get('symbol') or '').replace('US.', '')
                fs = fs_map.get(symbol_raw)
                if fs is not None:
                    # 将真实分项写回 candidate：供 auto-trader 通知直接使用，不再硬拆
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
                    if symbol_raw in top_llm_set:
                        candidate['second_layer_news_events'] = (
                            fs.get('raw', {}).get('news', {}).get('events', [])
                        )
                    for field in (
                        'neutral_news', 'neutral_announce', 'neutral_community',
                        'neutral_institution', 'neutral_capital',
                        'adjust_news', 'adjust_announce', 'adjust_community',
                        'adjust_institution', 'adjust_capital',
                        'neutral_total', 'score_adjustment_total', 'scoring_semantics',
                    ):
                        candidate[field] = fs.get(field)
                    candidate['five_source_total'] = fs['score_total']
                    candidate['four_source_total'] = fs['score_total']  # 兼容旧字段
                    candidate['five_source_available_count'] = fs['available_count']
                    candidate['four_source_available_count'] = fs['available_count']  # 兼容旧字段

                    # 直接复用统一社区证据池，不重复请求任何社区数据源。
                    community_raw = fs.get('raw', {}).get('community', {}) or {}
                    community_total = float(community_raw.get('count', 0) or 0)
                    if community_total > 0:
                        candidate['community_bull_pct'] = float(community_raw.get('bull', 0) or 0) / community_total
                        candidate['community_bear_pct'] = float(community_raw.get('bear', 0) or 0) / community_total
                        candidate['community_neutral_pct'] = float(community_raw.get('neutral', 0) or 0) / community_total
                        candidate['community_post_count'] = int(round(community_total))

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

                    print(f"   📊 {symbol_raw} 五源: 资讯{fs['score_news']}/公告{fs['score_announce']}/社区{fs['score_community']}/机构{fs['score_institution']}/资金{fs['score_capital']} (总{fs['score_total']}, 覆盖{fs['available_count']}/5)")

                    # 第一层评分占90%，五源深度评分占10%。五源内部逻辑不变。
                    first_score = candidate['first_layer_score']
                    if fs['available_count'] >= 3:
                        five_source_score = fs['score_total']
                        coverage_mode = 'five_source_real'
                    else:
                        five_source_score = int(first_score * 0.8)
                        coverage_mode = f'legacy_discounted (覆盖{fs["available_count"]}/5 <3)'
                    candidate['base_score_legacy'] = first_score
                    candidate['five_source_effective_score'] = five_source_score
                    candidate['combined_base_score'] = combine_layer_scores(
                        first_score, five_source_score
                    )
                    candidate['score'] = candidate['combined_base_score']
                    candidate['scoring_mode'] = f'first90_five10:{coverage_mode}'
                    print(
                        f"   ✅ {symbol_raw} 综合基础分 {candidate['score']} "
                        f"(第一层{first_score}×90% + 五源{five_source_score}×10%)"
                    )

                    # 购买力不足时跳过LLM分析,直接用基础评分
                    if skip_llm:
                        candidate['final_score'] = candidate.get('score', 70)
                        candidate['llm_adjust'] = 0
                        candidate['llm_reason'] = '购买力不足,跳过LLM分析'
                    elif symbol_raw in top_llm_set:
                        # 2026-07-01 east 保留：仅 TopN 跑 LLM，控制token消耗，五源评分已对所有≥70分候选统一计算
                        try:
                            sys.path.insert(0, str(STRATEGY_DIR))
                            from llm_stock_analyzer import analyze_stock

                            if llm_tech is not None:
                                try:
                                    candidate.update(llm_tech.get_llm_snapshot(symbol_raw))
                                except Exception as e:
                                    print(f"   ⚠️ {symbol_raw} LLM技术摘要失败: {e}")

                            market_data = {
                                'symbol': candidate.get('symbol', ''),
                                'company_name': candidate.get('name', ''),
                                'market': 'us',
                                'base_score': candidate.get('score', 70),
                                'price': candidate.get('price', 0),
                                'change_pct': candidate.get('change_pct', 0),
                                'rsi': candidate.get('rsi', 50),
                                'ma20': candidate.get('ma20', 0),
                                'ma50': candidate.get('ma50', 0),
                                'volume_ratio': candidate.get('volume_ratio', 1.0),
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
                                'forward_pe': candidate.get('forward_pe'),
                                'revenue_growth': candidate.get('revenue_growth'),
                                'earnings_growth': candidate.get('earnings_growth'),
                                'profit_margin': candidate.get('profit_margin'),
                                'trailing_eps': candidate.get('trailing_eps'),
                                'sector': candidate.get('sector', ''),
                                'sentiment': candidate.get('sentiment', '中性'),
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
                        # 2026-08-20 east 铁律修正（AAPL事件）: 非TopN候选不再"跳过LLM直接放行"。
                        # 铁律：没过 LLM 就不能下单。Top 20 以外的候选保留评分用于展示/观察，
                        # 但 llm_passed=False，auto-trader 永远不会买它们。
                        candidate['final_score'] = candidate.get('score', 70)
                        candidate['llm_adjust'] = 0
                        candidate['llm_reason'] = f'非Top{TOP_LLM_N}，未过LLM验真，禁止下单'
                        candidate['llm_passed'] = False
                        candidate['llm_status'] = 'skipped_not_top_n'
                else:
                    candidate['final_score'] = (
                        0
                        if candidate.get('score', 0) >= LAYER2_CANDIDATE_MIN_SCORE
                        else candidate.get('score', 0)
                    )
                    candidate['llm_adjust'] = 0
                    if candidate.get('score', 0) < LAYER2_CANDIDATE_MIN_SCORE:
                        candidate['llm_reason'] = ''
                    else:
                        candidate['llm_reason'] = '五源评分未完成，禁止进入交易候选'
                    candidate['llm_passed'] = (
                        candidate.get('score', 0) < LAYER2_CANDIDATE_MIN_SCORE
                    )  # 达到候选线却未完成五源时不允许通过

                # 只保留最终评分>=65的
                if candidate.get('final_score', 0) >= 65:
                    llm_analyzed.append(candidate)
            except Exception as e:
                print(f"   ⚠️ 处理{candidate.get('symbol','UNK')}异常: {e}")

            # === 增量保存：每 20 只 flush 一次，被kill也不会丢太多 ===
            if top_llm_set and (idx + 1) == len(top_llm_set):
                self._flush_opportunities(llm_analyzed, partial=True)
                print(f"   ⚡ Top {len(top_llm_set)} LLM结果已提前发布")
            elif (idx + 1) % 20 == 0:
                self._flush_opportunities(llm_analyzed, partial=True)

        results = llm_analyzed

        # ===== LLM分析完成后,直接触发交易 =====
        high_score_opportunities = [
            c for c in results 
            if c.get('llm_passed', True) and c.get('final_score', 0) >= STRATEGY_POLICY['us']['min_score']
        ]

        # 非交易时段高分信号通知（>=90分）
        now = datetime.now()
        current_time = now.time()
        # 美股交易时段：北京时间21:30-次日4:00，其余为非交易时段
        is_trading_hours = (current_time >= dt_time(21, 30)) or (current_time <= dt_time(4, 0))
        if not is_trading_hours:
            # 非交易时段信号推送已迁移到 auto-trader.py 的 send_opportunity_notification（带评分明细+确认提示），这里不再重复推送，避免双通知。
            print("📭 非交易时段信号通知由 auto-trader 统一发送，scanner 跳过。")

        if high_score_opportunities:
            print(f"\n🚀 发现 {len(high_score_opportunities)} 个高分机会，尝试直接交易...")
            self.execute_trades_directly(high_score_opportunities)

        # 最终保存（partial=False 表示本次扫描全部跑完）
        self._flush_opportunities(llm_analyzed, partial=False)
        print(f"💾 结果已保存")

    def execute_trades_directly(self, opportunities):
        """LLM分析完成后,直接触发交易"""
        try:
            # 导入自动交易模块(文件名是auto-trader.py)
            import importlib.util
            spec = importlib.util.spec_from_file_location("auto_trader", STRATEGY_DIR / "auto-trader.py")
            auto_trader_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(auto_trader_module)
            AutoTrader = auto_trader_module.AutoTrader

            trader = AutoTrader()

            # 连接Futu
            if not trader.connect_futu():
                print("   ❌ 无法连接Futu,跳过交易")
                return

            # 检查交易时间
            if not trader.check_trading_hours('us'):
                print("   ⏸️ 非美股交易时间,跳过")
                return

            # 获取账户信息
            account = trader.get_account_and_positions('us')
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

                futu_symbol = f"US.{symbol}"

                # 检查是否已持仓
                should, reason = trader.should_trade(futu_symbol, account['positions'], account.get('pending_orders', []))
                if not should:
                    print(f"   ⏭️ {symbol}: {reason}")
                    continue

                # 检查技术指标
                tech_signals = trader.check_technical_signals(
                    symbol,
                    market='us',
                    entry_score=score,
                )
                if not tech_signals.get('can_enter', False):
                    print(f"   ⏭️ {symbol}: 技术指标不满足")
                    continue

                order_plan = trader.prepare_buy_order(account, futu_symbol, price, score, market='us')
                if not order_plan.get('can_buy'):
                    print(f"   ⏭️ {symbol}: {order_plan.get('reason', '风控未通过')}")
                    continue

                quantity = order_plan['quantity']

                if quantity > 0:
                    print(
                        f"   💰 {symbol}: 评分仓位{order_plan['base_pct']*100:.1f}% "
                        f"· 市场总仓位上限{order_plan['total_limit_pct']:.0f}% "
                        f"→ 实际金额${order_plan['order_value']:,.2f}, "
                        f"总仓位{order_plan['after_total_pct']:.1f}%/{order_plan['total_limit_pct']:.0f}%"
                    )
                    print(f"\n   🎯 准备买入 {symbol}")
                    print(f"      价格: ${price:.2f}")
                    print(f"      数量: {quantity}股")
                    print(f"      评分: {score}分")

                    # 执行交易 (不再重复LLM分析,因为已经分析过了)
                    entry_reasons = [f"评分{score}分"] + tech_signals.get('reasons', [])
                    success = trader.execute_trade(
                        futu_symbol, 'BUY', quantity, price, 'us',
                        skip_llm=True,  # 跳过重复LLM分析
                        score=score,
                        reasons=entry_reasons,
                        opp=opp,
                    )

                    if success:
                        account['positions'].append({'symbol': futu_symbol})
                        print(f"   ✅ {symbol} 交易成功")
                    else:
                        print(f"   ❌ {symbol} 交易失败")

            # 关闭连接
            if trader.quote_ctx:
                trader.quote_ctx.close()
            if trader.trade_ctx:
                trader.trade_ctx.close()

        except Exception as e:
            print(f"   ❌ 直接交易失败: {e}")
            import traceback
            traceback.print_exc()

    def scan_with_longbridge(self, top_n=50):
        """使用长桥获取数据(备用数据源)"""
        try:
            import requests
        except ImportError:
            print("⚠️  缺少requests库,跳过长桥")
            return []

        if not self.longbridge_token:
            print("⚠️  长桥token未配置,跳过")
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

        # 批量获取(每次最多50只)
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

                                if score >= LAYER2_CANDIDATE_MIN_SCORE:
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
                    print(f"   ⚠️ 长桥API限制,等待后重试...")
                    time.sleep(5)

            except Exception as e:
                print(f"   ⚠️ 批次失败: {str(e)[:50]}")
                continue

            # 批次间延迟
            if i + batch_size < total:
                time.sleep(1)

        print(f"✅ 长桥扫描完成: 找到 {len(results)} 个机会")
        return results



    def print_top_results(self, results, n=10):
        """打印Top N结果"""
        print(f"\n📊 美股Top {n}高评分股票:")
        print("-" * 80)
        print(f"{'代码':<10} {'价格':>10} {'涨幅':>8} {'评分':>6} {'指数':<15}")
        print("-" * 80)

        for r in results[:n]:
            display_score = r.get('final_score', r.get('score', r.get('base_score', 0)))
            print(f"{r['symbol']:<10} ${r['price']:>8.2f} {r['change_pct']:>+7.2f}% {display_score:>5}分 {r['index']:<15}")


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
    scanner = USScanner()  # 不传递scan_limit参数,扫描所有股票
    results = scanner.scan(top_n=50)  # top_n只限制输出结果数量,不限制扫描股票数量
    if results:
        scanner.print_top_results(results, n=15)
