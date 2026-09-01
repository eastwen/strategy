#!/usr/bin/env python3
"""
LLM股票分析模块
- 被港股/美股扫描器调用，对候选股票进行LLM分析
- 被日报/周报调用，生成市场分析、风险提示、操作建议等

换模型只改文件顶部的 4 个常量，其他不用动。
"""

import requests
import os
import json
import re
import html
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher

from runtime_config import NEWS_DB_PATH, load_api_keys

_LLM_CONFIG = load_api_keys().get('llm', {})

# 想加更多备用，直接往 LLM_FALLBACKS 里 append 就行。
LLM_BASE_URL = os.getenv('LLM_BASE_URL') or _LLM_CONFIG.get('base_url') or 'https://note3-prev-api.askdiandian.com/v1'
LLM_API_KEY = os.getenv('LLM_API_KEY') or _LLM_CONFIG.get('api_key', '')
LLM_MODEL = os.getenv('LLM_MODEL') or _LLM_CONFIG.get('model') or 'dots3-note-prev'
LLM_FALLBACKS = [                          # 备用模型（按顺序尝试，越靠前优先级越高）
    "qwen3.7-plus-2026-05-26",
    "qwen3.5-ocr",
    "deepseek-v4-pro-0813",
    "deepseek-v4-flash-0731",
    "qwen3.7-flash-2026-07-15",
    "dots-3-note-preview-free",
    "gemini-3.7-flash-free",
    "coding-kimi-k3-free",
]
# ==========================

# 兼容旧代码：保留 LLM_FALLBACK 作为第一个备用的别名
LLM_FALLBACK = LLM_FALLBACKS[0] if LLM_FALLBACKS else None

# 新闻库路径


def fetch_recent_news(symbol: str, hours: int = 24, limit: int = 8):
    """拉取该股最近 N 小时的新闻标题 + 关键词情绪。

    返回: list[ {title, sentiment, source, hours_ago} ]，最多 limit 条；库不可用或无记录返回 [].
    股票代码带前缀会被去掉 (US.AAPL -> AAPL, HK.00700 -> 00700)。
    """
    if not symbol:
        return []
    raw = symbol.split('.')[-1] if '.' in symbol else symbol
    try:
        conn = sqlite3.connect(NEWS_DB_PATH, timeout=2)
        cur = conn.cursor()
        cur.execute("""
            SELECT n.title, n.sentiment, n.source,
                   ROUND((julianday('now') - julianday(n.timestamp)) * 24, 1) AS hours_ago
            FROM stock_mentions sm
            JOIN news n ON n.id = sm.news_id
            WHERE sm.symbol = ? AND n.timestamp > datetime('now', ?)
            ORDER BY n.timestamp DESC
            LIMIT ?
        """, (raw, f'-{hours} hours', limit))
        rows = cur.fetchall()
        conn.close()
        out = []
        for title, sent, src, ha in rows:
            out.append({
                'title': (title or '')[:120],
                'sentiment': float(sent) if sent is not None else 0.5,
                'source': src or '',
                'hours_ago': ha if ha is not None else 0.0,
            })
        return out
    except Exception:
        return []


def format_news_block(news_items):
    """把新闻列表格式化为 prompt 能读的多行文本，每条带情绪表情 + 距今时间。"""
    if not news_items:
        return '无近期相关新闻'
    lines = []
    for n in news_items:
        s = n.get('sentiment', 0.5)
        emoji = '📈' if s > 0.6 else '📉' if s < 0.4 else '📊'
        ha = n.get('hours_ago', 0.0)
        ha_str = f'{ha:.0f}h前' if ha and ha >= 1 else '刚刚'
        lines.append(f"  {emoji} [{ha_str}] {n['title']}")
    return '\n'.join(lines)


# futu-stock-digest 预处理：只拉取富途新闻并去重；方向由当前 LLM 判断。
FUTU_NEWS_API = 'https://ai-news-search.futunn.com/news_search'


def _clean_futu_title(value):
    return re.sub(r'<[^>]+>', '', html.unescape(str(value or ''))).strip()


def _futu_title_key(value):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', _clean_futu_title(value).lower())


def _futu_titles_similar(left, right):
    a, b = _futu_title_key(left), _futu_title_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < 12:
        return False
    if SequenceMatcher(None, a, b).ratio() >= 0.68:
        return True
    tokens_a = set(re.findall(r'[a-z0-9]+', _clean_futu_title(left).lower()))
    tokens_b = set(re.findall(r'[a-z0-9]+', _clean_futu_title(right).lower()))
    return bool(tokens_a and tokens_b and len(tokens_a & tokens_b) / len(tokens_a | tokens_b) >= 0.60)


def _digest_company_aliases(company_name):
    name = _clean_futu_title(company_name).lower().strip()
    if not name:
        return set()
    aliases = {name}
    trimmed = re.sub(r'\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings)\.?$', '', name).strip()
    if trimmed:
        aliases.add(trimmed)
        first = trimmed.split()[0] if trimmed.split() else ''
        if len(first) >= 4:
            aliases.add(first)
    return aliases


def _futu_highlight_aliases(items, raw_symbol):
    aliases = set()
    ticker = re.escape(raw_symbol)
    pattern = re.compile(r'([\u4e00-\u9fff]{2,10})\s*[（(]?\s*<em>\s*' + ticker + r'\s*</em>', re.I)
    for item in items:
        match = pattern.search(str(item.get('title') or ''))
        if match:
            aliases.add(match.group(1).lower())
    return aliases


def _is_futu_digest_relevant(raw_title, raw_symbol, aliases):
    text = str(raw_title or '')
    if re.search(rf'<em>\s*{re.escape(raw_symbol)}\s*</em>', text, re.I):
        return True
    clean = _clean_futu_title(text).lower()
    for alias in aliases:
        if len(alias) >= 4 and alias in clean:
            return True
        if alias and re.fullmatch(r'[\u4e00-\u9fff]{2,10}', alias) and alias in clean:
            return True
    return len(raw_symbol) > 2


def fetch_futu_digest(symbol: str, market: str = 'us', size: int = 10, company_name: str = ''):
    """Fetch and dedupe Futu news; semantic direction is decided by the current LLM."""
    if not symbol:
        return None
    raw = symbol.split('.')[-1] if '.' in symbol else symbol
    try:
        response = requests.get(FUTU_NEWS_API, params={
            'keyword': raw, 'size': size, 'news_type': 1, 'lang': 'zh-CN', 'sort_type': 2,
        }, headers={'User-Agent': 'futu-stock-digest/0.0.2 (Skill)'}, timeout=8)
        if response.status_code != 200:
            return None
        data = response.json() or {}
        if str(data.get('code', -1)) != '0':
            return None
        items = data.get('data') or []
        aliases = _digest_company_aliases(company_name) | _futu_highlight_aliases(items, raw)
        events, filtered_out = [], 0
        for item in items:
            if not _is_futu_digest_relevant(item.get('title'), raw, aliases):
                filtered_out += 1
                continue
            title = _clean_futu_title(item.get('title'))
            if not title or any(_futu_titles_similar(title, event['title']) for event in events):
                continue
            events.append({'title': title, 'url': str(item.get('url') or '').strip()})
        if not events:
            return None
        return {
            'direction': 'pending_llm',
            'conclusion': f'富途返回{len(items)}条，过滤{filtered_out}条无关结果，合并重复报道后保留{len(events)}个事件，等待当前LLM统一判断方向和影响',
            'signals': [event['title'] for event in events[:max(3, min(size, 10))]],
            'evidence': [event['title'] + (f" ({event['url']})" if event['url'] else '') for event in events[:3]],
            'filtered_out': filtered_out,
            'company_aliases': sorted(aliases),
        }
    except Exception:
        return None


def fetch_multi_source_news_digest(symbol: str, market: str = 'us',
                                   company_name: str = '', size: int = 10):
    """Use the shared news collectors as an LLM-only fallback; ignore their score."""
    if not symbol:
        return None
    try:
        from four_source_scorer import score_international_news

        result = score_international_news(
            symbol=symbol,
            market=market,
            cap=25,
            company_name=company_name,
        )
        raw = result.get('raw', {}) or {}
        events = raw.get('events', []) or []
        titles = []
        evidence = []
        sources = set()
        for event in events:
            title = str(event.get('title') or '').strip()
            if not title:
                continue
            titles.append(title)
            event_sources = event.get('sources', []) or []
            sources.update(str(source) for source in event_sources if source)
            source_text = '/'.join(str(source) for source in event_sources if source)
            evidence.append(f"{title} [{source_text}]" if source_text else title)
            if len(titles) >= size:
                break
        if not titles:
            return None
        return {
            'origin': 'multi_source_fallback',
            'direction': 'pending_llm',
            'conclusion': (
                f"富途主查询无结果；备用资讯池合并去重后保留{len(titles)}个事件，"
                "等待当前LLM统一判断方向和影响"
            ),
            'signals': titles,
            'evidence': evidence[:3],
            'sources': sorted(sources),
        }
    except Exception:
        return None


def format_digest_block(digest):
    if not digest:
        return '无futu新闻摘要'
    direction = digest.get('direction', 'pending_llm')
    lines = [f"方向: {'由当前LLM判断' if direction == 'pending_llm' else direction}", f"摘要: {digest.get('conclusion', '')}"]
    if digest.get('signals'):
        lines.append('关键信号:')
        lines.extend(f"  - {item}" for item in digest['signals'])
    if digest.get('evidence'):
        lines.append('证据链接:')
        lines.extend(f"  - {item}" for item in digest['evidence'][:3])
    return '\n'.join(lines)


def build_second_layer_news_digest(events, limit=10):
    """Build an LLM news block from the exact scored international-news pool."""
    usable = [event for event in (events or []) if isinstance(event, dict) and event.get('title')]
    if not usable:
        return None
    ranked = sorted(
        usable,
        key=lambda event: max(
            float(event.get('positive_strength', 0) or 0),
            float(event.get('negative_strength', 0) or 0),
        ),
        reverse=True,
    )[:limit]
    signals = [_clean_futu_title(event.get('title')) for event in ranked]
    evidence = []
    for event, title in zip(ranked[:3], signals[:3]):
        sources = event.get('sources') or event.get('source') or ''
        source_text = ', '.join(sources) if isinstance(sources, list) else str(sources)
        evidence.append(f"{title}{f'（{source_text}）' if source_text else ''}")
    return {
        'direction': 'pending_llm',
        'conclusion': (
            f'第二层国际资讯已合并去重{len(usable)}个事件，'
            '当前LLM基于同源事件池判断方向和影响'
        ),
        'signals': signals,
        'evidence': evidence,
        'origin': 'second_layer_news',
    }


# ===== 换模型只改这里 =====
# 主模型 + 备用模型链。主模型挂了按顺序往下试，直到有一个返回成功。



class LLMClient:
    """LLM通用客户端 - 所有LLM调用统一走这里"""

    def __init__(self):
        self.base_url        = LLM_BASE_URL
        self.model           = LLM_MODEL
        self.fallback_models = list(LLM_FALLBACKS)
        self.fallback_model  = self.fallback_models[0] if self.fallback_models else None  # 兼容旧字段
        self.api_key         = LLM_API_KEY

        if not self.api_key or self.api_key.startswith("sk-xxx"):
            print("⚠️ LLM API Key 未配置，请修改文件顶部 LLM_API_KEY")

    @staticmethod
    def _answer_from_reasoning(reasoning):
        """Prefer the last complete JSON value before falling back to the last line."""
        text = (reasoning or '').strip()
        if not text:
            return ''
        decoder = json.JSONDecoder()
        answers = []
        for start, char in enumerate(text):
            if char not in '[{':
                continue
            try:
                value, length = decoder.raw_decode(text[start:])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, (dict, list)):
                answers.append((start + length, text[start:start + length].strip()))
        if answers:
            return max(answers, key=lambda item: item[0])[1]
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[-1].strip() if lines else ''

    def _try_one(self, use_model, prompt, max_tokens, temperature):
        """调用单个模型一次。成功返回 (True, content)，失败返回 (False, 错误描述)。

        2026-06-25 east 修复：
        - deepseek-v4-pro 等推理模型会把回答放在 reasoning_content，正式 content 为空；
          推理模型默认 max_tokens 被 reasoning 吃光时 content 会空串。
        - 现在：拿不到 content 时回退到 reasoning_content 的最后一行；并强制把推理模型的
          max_tokens 抬到 800 以上，保证 content 有预算输出。
        """
        model_name = (use_model or '').lower()
        is_reasoning = (
            'deepseek' in model_name
            or 'reasoner' in model_name
            or 'dots3-note-prev' in model_name
            or 'dots-3-note-preview' in model_name
            or bool(re.search(r'(^|[-_/])r1($|[-_/])', model_name))
        )
        if is_reasoning and max_tokens < 800:
            max_tokens = 800
        try:
            payload = {
                'model': use_model,
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': max_tokens,
                'temperature': temperature,
            }
            # Structured stock verification needs a direct JSON response.
            # Qwen 3.x models on DashScope otherwise default to deep thinking,
            # which can consume the response budget before content is emitted.
            if 'dashscope.aliyuncs.com' in self.base_url and use_model.lower().startswith('qwen3'):
                payload['enable_thinking'] = False

            request_kwargs = {
                'headers': {
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                'timeout': 90,
            }
            resp = requests.post(
                f'{self.base_url}/chat/completions', json=payload, **request_kwargs
            )
            # DashScope model capabilities differ across Qwen 3.x models.
            # Retry once without this optional flag when a model rejects it.
            if (
                resp.status_code == 400
                and 'enable_thinking' in payload
                and 'enable_thinking' in resp.text
            ):
                payload.pop('enable_thinking', None)
                resp = requests.post(
                    f'{self.base_url}/chat/completions', json=payload, **request_kwargs
                )
            if resp.status_code == 200:
                msg = resp.json()['choices'][0]['message']
                content = (msg.get('content') or '').strip()
                if not content:
                    reasoning = (msg.get('reasoning_content') or '').strip()
                    content = self._answer_from_reasoning(reasoning)
                if not content:
                    return False, 'content/reasoning 均为空'
                # Some providers return quota/rate-limit errors as HTTP 200 text.
                # Treat those as failures so the next model can be tried.
                lower_content = content.lower()
                error_markers = (
                    'quota', 'rate limit', 'too many requests', 'recharge',
                    'prevent abuse', '额度', '限流', '请求过于频繁',
                )
                if any(marker in lower_content for marker in error_markers):
                    return False, f'provider error: {content[:160]}'
                return True, content
            return False, f"HTTP {resp.status_code} - {resp.text[:100]}"
        except Exception as e:
            return False, f"异常: {e}"

    def call(self, prompt, max_tokens=500, temperature=0.3, model=None):
        """通用LLM调用，主模型失败按 LLM_FALLBACKS 顺序自动降级

        Args:
            prompt: 提示词
            max_tokens: 最大token数
            temperature: 温度
            model: 指定模型；指定后不再 fallback
        Returns:
            str: LLM回复内容，全部失败返回None
        """
        if not self.api_key or self.api_key.startswith("sk-xxx"):
            return None

        # 指定单一模型：只试这一个，不降级
        if model:
            ok, result = self._try_one(model, prompt, max_tokens, temperature)
            if ok:
                return result
            print(f"⚠️ LLM调用失败 [{model}]: {result}")
            return None

        # 主模型 + 备用链，按顺序尝试
        candidates = [self.model] + [m for m in self.fallback_models if m and m != self.model]
        for idx, use_model in enumerate(candidates):
            ok, result = self._try_one(use_model, prompt, max_tokens, temperature)
            if ok:
                if idx > 0:
                    print(f"✅ 降级到备用模型成功: {use_model}")
                return result
            if idx < len(candidates) - 1:
                next_model = candidates[idx + 1]
                print(f"⚠️ {use_model} 失败({result})，尝试备用 {next_model}")
            else:
                print(f"⚠️ LLM全部模型调用失败，最后一次 [{use_model}]: {result}")
        return None

    # ===== 日报/周报用的LLM功能 =====

    def get_market_prediction(self, market, vix_val, index_data, sentiment_full=None):
        """使用LLM生成未来3日市场预判

        Args:
            market: 'hk' 或 'us'
            vix_val: VIX/VHSI数值（向后兼容）
            index_data: 指数数据dict {name: {price, change_pct}}
            sentiment_full: 2026-06-18 east 修复——多源综合情绪评分字典
                            港股: {sentiment_score, vhsi, capital_flow, bull_bear_ratio, ...}
                            美股: {sentiment_score, vix, fear_greed, option_ratio, spx_change, ...}
        Returns:
            list[dict]: 预测结果 [{day, sentiment, probability, trend}]，失败返回None
        """
        market_name = '港股' if market == 'hk' else '美股'

        index_context = ''
        for name, data in index_data.items():
            chg = data.get('change_pct', 0)
            try: chg = float(chg)
            except: chg = 0
            index_context += f"- {name}: {float(data.get('price', 0)):,.2f} ({chg:+.2f}%)\n"

        # 2026-06-18 east 修复：多源情绪上下文（取代单一 VIX/VHSI）
        sentiment_block = f"- 恐慌波动指数: {vix_val:.1f}\n"
        sentiment_block += f"- 波动状态: {'恐慌' if vix_val > 25 else '正常' if vix_val > 20 else '平静'}\n"
        if sentiment_full:
            score = sentiment_full.get('sentiment_score', 50)
            label = sentiment_full.get('sentiment_label', 'N/A')
            sentiment_block += f"- 多源综合情绪评分: {score:.0f}/100 ({label})\n"
            if market == 'hk':
                cf = sentiment_full.get('capital_flow')
                if cf is not None:
                    sentiment_block += f"- 恒指权重股资金净流: {cf:+.2f}亿港元 ({sentiment_full.get('flow_sentiment', 'N/A')})\n"
                wr = sentiment_full.get('bull_bear_ratio')
                if wr is not None:
                    sentiment_block += f"- 牛熊证多空成交额比: {wr:.3f} ({sentiment_full.get('warrant_sentiment', 'N/A')})\n"
            else:
                fg = sentiment_full.get('fear_greed')
                if fg is not None:
                    sentiment_block += f"- CNN恐慌贪婪指数: {fg:.1f} ({sentiment_full.get('fg_sentiment', 'N/A')})\n"
                pcr = sentiment_full.get('option_ratio')
                if pcr is not None:
                    sentiment_block += f"- 期权 Put/Call 比例: {pcr:.3f} ({sentiment_full.get('pcr_sentiment', 'N/A')})\n"
                spx_chg = sentiment_full.get('spx_change')
                if spx_chg is not None:
                    sentiment_block += f"- S&P 500 当日涨跌: {spx_chg:+.2f}%\n"

        prompt = f"""你是专业的{market_name}市场分析师。请根据以下实时多源数据预测未来3个交易日的市场走势。

当前市场指数：
{index_context}
当前多源情绪信号：
{sentiment_block}
请结合多源信号给出未来3个交易日的预测（不要只看波动率！），格式如下：
T+1日|情绪预判|概率|市场走势
T+2日|情绪预判|概率|市场走势
T+3日|情绪预判|概率|市场走势

每行一个交易日，用|分隔。情绪预判用：乐观/中性偏多/中性/中性偏空/悲观。概率用百分比。市场走势用简短描述（不超过10字）。
注意：如果多源信号出现背离（如 VIX 低但 Put/Call 高 / 资金流大幅流出 / CNN 恐惧），请侧重价格与资金走向。

直接回复3行预测，不要其他内容。"""

        content = self.call(prompt, max_tokens=200, temperature=0.5)
        if content:
            return self._parse_prediction(content)
        return None

    def _parse_prediction(self, content):
        """解析LLM返回的预测内容"""
        predictions = []
        for line in content.strip().split('\n'):
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 4:
                    predictions.append({
                        'day': parts[0].strip(),
                        'sentiment': parts[1].strip(),
                        'probability': parts[2].strip(),
                        'trend': parts[3].strip()
                    })
        return predictions if predictions else None

    def get_market_analysis(self, market, index_data, vix_val, sentiment_full=None):
        """使用LLM解读市场走势

        Args:
            market: 'hk' 或 'us'
            index_data: 指数数据dict {name: {price, change_pct}}
            vix_val: VIX/VHSI数值（向后兼容）
            sentiment_full: 2026-06-18 east 修复——多源综合情绪评分字典
        Returns:
            str: 市场分析文本，失败返回None
        """
        market_name = '港股' if market == 'hk' else '美股'

        index_lines = ''
        for name, data in index_data.items():
            price = float(data.get('price', 0))
            chg = data.get('change_pct', 0)
            try: chg = float(chg)
            except: chg = 0
            index_lines += f"- {name}: {price:,.2f} ({chg:+.2f}%)\n"

        # 2026-06-18 east 修复：多源情绪上下文
        sentiment_lines = f"- 恐慌波动指数: {vix_val:.1f}\n"
        if sentiment_full:
            score = sentiment_full.get('sentiment_score', 50)
            label = sentiment_full.get('sentiment_label', 'N/A')
            sentiment_lines += f"- 多源综合情绪: {score:.0f}/100 ({label})\n"
            if market == 'hk':
                cf = sentiment_full.get('capital_flow')
                if cf is not None:
                    sentiment_lines += f"- 权重股资金净流: {cf:+.2f}亿 ({sentiment_full.get('flow_sentiment', 'N/A')})\n"
                wr = sentiment_full.get('bull_bear_ratio')
                if wr is not None:
                    sentiment_lines += f"- 牛熊证多空比: {wr:.3f} ({sentiment_full.get('warrant_sentiment', 'N/A')})\n"
            else:
                fg = sentiment_full.get('fear_greed')
                if fg is not None:
                    sentiment_lines += f"- CNN恐慌贪婪: {fg:.1f} ({sentiment_full.get('fg_sentiment', 'N/A')})\n"
                pcr = sentiment_full.get('option_ratio')
                if pcr is not None:
                    sentiment_lines += f"- 期权 P/C: {pcr:.3f} ({sentiment_full.get('pcr_sentiment', 'N/A')})\n"

        prompt = f"""你是专业的{market_name}市场分析师。请根据以下实时多源数据解读今日市场走势。

今日{market_name}指数表现：
{index_lines}
今日多源情绪信号：
{sentiment_lines}
请用2-3句话解读今日{market_name}市场走势，要点：
1. 整体趋势判断（上涨/下跌/震荡）+ 多源信号是否一致
2. 板块或风格特征（如有）
3. 对短期（1-3日）的展望

如果多源信号出现背离（VIX 低但 P/C 高 / 资金流出 / 恐惧），请明确指出。

直接回复分析内容，不要加标题。"""

        return self.call(prompt, max_tokens=300, temperature=0.4)

    def _format_enriched_positions(self, positions, max_n=8):
        """把 enrich 过的持仓渲染为 prompt 能读的多行文本
        兼容老格式（只有 symbol+pnl_pct）与新格式（含新闻/情绪/技术）。
        """
        if not positions:
            return '  无持仓'
        lines = []
        for p in positions[:max_n]:
            sym = p.get('symbol', '')
            pnl = p.get('pnl_pct', 0)
            head = f"  - {sym}: 浮盈{pnl:+.2f}%"
            extras = []
            d = p.get('days_held')
            if d is not None:
                extras.append(f"持有{d}天")
            rsi = p.get('rsi')
            if rsi is not None:
                try:
                    extras.append(f"RSI{float(rsi):.0f}")
                except Exception:
                    pass
            atr = p.get('atr')
            if atr is not None:
                try:
                    extras.append(f"ATR{float(atr):.2f}")
                except Exception:
                    pass
            ns = p.get('news_sentiment_24h')
            cnt = p.get('news_count_24h', 0)
            if cnt and cnt > 0 and ns is not None:
                emoji = '📈' if ns > 0.6 else '📉' if ns < 0.4 else '📊'
                extras.append(f"24h情绪 {emoji}{ns:.2f}({cnt}条)")
            if extras:
                head += ", " + ", ".join(extras)
            lines.append(head)
            top_news = p.get('top_news') or []
            shown = 0
            for n in top_news:
                s = n.get('sentiment', 0.5)
                if s > 0.6 or s < 0.4:
                    em = '📈' if s > 0.6 else '📉'
                    title = (n.get('title') or '')[:80]
                    lines.append(f"      {em} {title}")
                    shown += 1
                    if shown >= 2:
                        break
        return '\n'.join(lines)

    def get_risk_assessment(self, market_data):
        """使用LLM生成动态风险分析

        Args:
            market_data: dict 包含 pos_pct, cash_pct, vix, vhsi, total_asset, positions, initial
        Returns:
            str: 风险分析文本，失败返回None
        """
        pos_pct    = market_data.get('pos_pct', 0)
        cash_pct   = market_data.get('cash_pct', 0)
        vix        = market_data.get('vix')   # 可选，不传则不写进prompt
        vhsi       = market_data.get('vhsi')  # 可选，不传则不写进prompt
        total_asset = market_data.get('total_asset', 0)
        positions  = market_data.get('positions', [])
        initial    = market_data.get('initial', 2000000)
        pnl_pct    = (total_asset - initial) / initial * 100 if initial > 0 else 0

        pos_list = self._format_enriched_positions(positions, max_n=8)

        vol_lines = []
        if vix is not None:
            vol_lines.append(f"- 美股VIX: {float(vix):.1f}")
        if vhsi is not None:
            vol_lines.append(f"- 港股VHSI: {float(vhsi):.1f}")
        vol_section = ("\n".join(vol_lines) + "\n") if vol_lines else ""

        prompt = f"""你是专业的风险管理分析师。请根据以下实时数据给出风险分析，重点关注“个股新闻利空”和“技术面走坏”的仓位。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细（含新闻情绪/技术指标）:
{pos_list}
{vol_section}
请给出2-3条风险提示，优先提及：
- 某只持仓股 24h 情绪 ≤ 0.4（利空股）或出现明显负面新闻标题
- 某只持仓 RSI 过高/过低 或 价格偏离 MA 走坏
- 集中度/系统性/流动性三大风险

每条格式：风险等级|风险类型|具体描述|建议动作
- 风险等级用：🔴高/🟠中/🟡低
- 风险类型用：系统性/个股事件/集中度/流动性
- 描述必须提到具体股票代码或指标数据，不要空话
- 动作不超过15字

一行一条，直接回复，不要其他内容。"""

        return self.call(prompt, max_tokens=400, temperature=0.3)

    def get_action_recommendations(self, market_data):
        """使用LLM生成针对性操作建议

        Args:
            market_data: dict 包含 pos_pct, cash_pct, vix, vhsi, total_asset, positions, initial
        Returns:
            str: 操作建议文本，失败返回None
        """
        pos_pct    = market_data.get('pos_pct', 0)
        cash_pct   = market_data.get('cash_pct', 0)
        vix        = market_data.get('vix', 20)
        vhsi       = market_data.get('vhsi', 25)
        total_asset = market_data.get('total_asset', 0)
        positions  = market_data.get('positions', [])
        initial    = market_data.get('initial', 2000000)
        pnl_pct    = (total_asset - initial) / initial * 100 if initial > 0 else 0

        pos_list = self._format_enriched_positions(positions, max_n=8)

        prompt = f"""你是专业的交易策略顾问。请根据以下实时数据给出针对性操作建议，必须结合具体持仓股的新闻情绪和技术状况，有名有姓地说。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细（含新闻情绪/技术指标）:
{pos_list}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请给出3条操作建议，优先覆盖：
- 针对出现利空新闻或技术走坏的持仓股给"减仓/收紧止损"建议
- 针对情绪>0.6且技术面健康的持仓股给"持有/滑升止盈"建议
- 总仓位/现金调度，或某股超限制的调仓动作

每条格式：建议类型|具体建议
- 建议类型用：仓位管理/止损止盈/开仓机会/风险规避
- 具体建议必须提及股票代码或明确价格/比例，不超过25字

一行一条，直接回复，不要其他内容。"""

        return self.call(prompt, max_tokens=400, temperature=0.3)


    def get_combined_assessment(self, market_data):
        """一次调用同时生成"风险评估"和"操作建议"，让两块逻辑在 thinking 模型一次思考中保持一致。

        Returns:
            dict: {'risk_text': str, 'action_text': str}；失败返回两个都 None。
        """
        pos_pct    = market_data.get('pos_pct', 0)
        cash_pct   = market_data.get('cash_pct', 0)
        vix        = market_data.get('vix', 20)
        vhsi       = market_data.get('vhsi', 25)
        total_asset = market_data.get('total_asset', 0)
        positions  = market_data.get('positions', [])
        initial    = market_data.get('initial', 2000000)
        pnl_pct    = (total_asset - initial) / initial * 100 if initial > 0 else 0

        pos_list = self._format_enriched_positions(positions, max_n=8)

        prompt = f"""你是专业的风险管理与交易策略顾问。请基于下面的实时数据同时输出"风险评估"和"操作建议"，两部分必须逻辑一致——如果某股在 RISK 部分被识别为利空，ACTION 中不能给他"持有/加仓"建议；所有描述必须有名有姓提到具体股票代码或指标数据。

当前账户数据：
- 总资产: ${total_asset:,.0f}（累计{pnl_pct:+.2f}%）
- 持仓占比: {pos_pct:.1f}%，现金占比: {cash_pct:.1f}%
- 持仓明细（含新闻情绪/技术指标）:
{pos_list}
- 美股VIX: {vix:.1f}
- 港股VHSI: {vhsi:.1f}

请严格按下面两段格式输出，不要任何多余文字：

###RISK###
风险等级|风险类型|具体描述|建议动作
风险等级|风险类型|具体描述|建议动作
（3~4条，优先报警：24h情绪≤0.4的持仓股 / 出现负面新闻标题的股 / RSI过高过低或价格偏离MA / 集中度/流动性风险。风险等级用🔴高/🟠中/🟡低；风险类型用 系统性/个股事件/集中度/流动性；动作≤15字）

###ACTION###
建议类型|具体建议
建议类型|具体建议
建议类型|具体建议
（3~4条，优先覆盖：针对 RISK 中点名的利空股给"减仓/收紧止损"；对情绪>0.6且技术面健康的股给"持有/滑升止盈"；总仓位/现金调度。建议类型用 仓位管理/止损止盈/开仓机会/风险规避；具体建议必须提股票代码或明确价格/比例，≤25字）
"""

        content = self.call(prompt, max_tokens=700, temperature=0.3)
        if not content:
            return {'risk_text': None, 'action_text': None}

        risk_text, action_text = self._split_combined(content)
        return {'risk_text': risk_text, 'action_text': action_text}

    @staticmethod
    def _split_combined(content):
        """从 ###RISK### / ###ACTION### 标签里切两段；标签缺失则整段当 risk。"""
        if not content:
            return None, None
        # 标准化
        text = content.replace('\r\n', '\n').strip()
        risk = action = None
        # 优先用 marker 切
        if '###ACTION###' in text:
            head, action = text.rsplit('###ACTION###', 1)
            if '###RISK###' in head:
                risk = head.split('###RISK###', 1)[1]
            else:
                risk = head
        elif '###RISK###' in text:
            risk = text.split('###RISK###', 1)[1]
        else:
            # 没标签，全当 risk 让上层 fallback
            risk = text
        risk = (risk or '').strip()
        action = (action or '').strip()
        return risk, action



class LLMStockAnalyzer:
    """LLM股票分析器 - 扫描器用"""

    def __init__(self):
        self.client = LLMClient()

    def analyze(self, symbol, market_data):
        """分析股票

        Args:
            symbol: 股票代码 (如 US.AAPL, HK.00700)
            market_data: dict 包含:
                - base_score: 基础评分
                - price: 当前价格
                - change_pct: 涨跌幅
                - rsi: RSI值
                - ma20, ma50: 均线
                - volume_ratio: 成交量比率
                - atr: ATR
                - sentiment: 新闻情绪
                - market: 市场类型 (us/hk)
                - score_news, score_announce, score_community, score_institution, score_capital: 五源拆分（可选）
                - evidence_announce, evidence_community, evidence_institution, evidence_capital: 非新闻维度真实证据（可选）
                - capital_direction: 资金异动方向 '净流入'/'净流出'/'分歧'（可选）
                - community_bull_pct, community_bear_pct, community_post_count: 社区多空百分比（可选）
                - macd, macd_signal, macd_state, ma20_slope_pct: 趋势结构（可选）
                - return_5d_pct, return_20d_pct, distance_20d_high_pct, intraday_drawdown_pct: 近期价格结构（可选）
                - trailing_pe, forward_pe, pb_ratio, revenue_growth, earnings_growth, profit_margin: 轻量基本面（可选）

        Returns:
            dict: 包含 final_score, score_adjust, llm_reason
        """
        if not self.client.api_key or self.client.api_key.startswith("sk-xxx"):
            return self._fallback(market_data, "无API Key")

        market_data = dict(market_data)  # 避免修改调用方原始 dict

        # 优先复用第二层实际评分过的国际资讯事件，确保评分和 LLM 同源。
        digest = build_second_layer_news_digest(market_data.get('second_layer_news_events'))
        if digest:
            market_data['futu_digest'] = digest
        else:
            market = market_data.get('market', 'us')
            digest = fetch_futu_digest(
                symbol, market, company_name=market_data.get('company_name') or market_data.get('name', '')
            )
            if not digest:
                digest = fetch_multi_source_news_digest(
                    symbol,
                    market,
                    company_name=market_data.get('company_name') or market_data.get('name', ''),
                )
            if digest:
                market_data['futu_digest'] = digest
            else:
                # 所有实时资讯源均无数据时，最后退回 news.db 原始新闻。
                market_data['recent_news'] = fetch_recent_news(symbol, hours=24, limit=8)

        prompt = self._build_prompt(symbol, market_data)
        content = self.client.call(prompt, max_tokens=800, temperature=0.3)
        parsed = self._parse(content, market_data, fallback=False) if content else None
        if parsed:
            return parsed

        retry_prompt = prompt + '\n上次输出无法解析。只返回JSON对象；reason仍须包含催化、技术或资金确认及主要风险。'
        retry_content = self.client.call(retry_prompt, max_tokens=400, temperature=0.0)
        parsed = self._parse(retry_content, market_data, fallback=False) if retry_content else None
        if parsed:
            parsed['llm_retried'] = True
            return parsed
        return self._fallback(market_data, "LLM重试后仍无法解析，禁止交易")

    def _build_prompt(self, symbol, data):
        market = data.get('market', 'us')
        market_name = '美股' if market == 'us' else '港股'

        # 优先使用富途新闻事件池，没有时退回原始新闻。
        digest = data.get('futu_digest')
        if digest:
            news_block = format_digest_block(digest)
            news_count = len(digest.get('signals', []))
            if digest.get('origin') == 'second_layer_news':
                news_section_title = '第二层国际资讯事件池（与评分同源，由本次LLM分析方向与影响）'
            elif digest.get('origin') == 'multi_source_fallback':
                news_section_title = '多源备用新闻事件池（仅供LLM验真，不参与基础评分）'
            else:
                news_section_title = '富途新闻事件池（由本次LLM分析方向与影响）'
        else:
            recent_news = data.get('recent_news') or []
            news_block = format_news_block(recent_news)
            news_count = len(recent_news)
            news_section_title = f"最近24h相关新闻 ({news_count}条)"

        # 五源拆分（老调用方不传也不报错）
        sn = data.get('score_news', 0)
        sa = data.get('score_announce', 0)
        sc = data.get('score_community', 0)
        si = data.get('score_institution', 0)
        sk = data.get('score_capital', 0)
        neutral_scores = {
            'news': data.get('neutral_news', 12.5),
            'announce': data.get('neutral_announce', 10.0),
            'community': data.get('neutral_community', 12.5),
            'institution': data.get('neutral_institution', 10.0),
            'capital': data.get('neutral_capital', 5.0),
        }
        adjustments = {
            'news': data.get('adjust_news'),
            'announce': data.get('adjust_announce'),
            'community': data.get('adjust_community'),
            'institution': data.get('adjust_institution'),
            'capital': data.get('adjust_capital'),
        }
        availability = {
            'news': data.get('available_news', False),
            'announce': data.get('available_announce', False),
            'community': data.get('available_community', False),
            'institution': data.get('available_institution', False),
            'capital': data.get('available_capital', False),
        }
        cap_dir = data.get('capital_direction', '')
        bull_pct = data.get('community_bull_pct', 0)
        bear_pct = data.get('community_bear_pct', 0)
        post_count = data.get('community_post_count', 0)

        def compact_evidence(value, limit=300):
            text = ' '.join(str(value or '').split())
            return text[:limit] if text else '未覆盖'

        def format_metric(value, digits=2, suffix=''):
            if value is None or value == '' or value == 'N/A':
                return '未覆盖'
            try:
                number = float(value)
                if number != number:
                    return '未覆盖'
                return f"{number:.{digits}f}{suffix}"
            except (TypeError, ValueError):
                return '未覆盖'

        def format_bool(value):
            if value is True:
                return '是'
            if value is False:
                return '否'
            return '未覆盖'

        def format_large(value):
            if value is None or value == '' or value == 'N/A':
                return '未覆盖'
            try:
                number = float(value)
                if number != number:
                    return '未覆盖'
                if abs(number) >= 1_000_000_000:
                    return f"{number / 1_000_000_000:.2f}B"
                if abs(number) >= 1_000_000:
                    return f"{number / 1_000_000:.2f}M"
                return f"{number:,.0f}"
            except (TypeError, ValueError):
                return '未覆盖'

        evidence_news = compact_evidence(data.get('evidence_news'))
        evidence_announce = compact_evidence(data.get('evidence_announce'))
        evidence_community = compact_evidence(data.get('evidence_community'))
        evidence_institution = compact_evidence(data.get('evidence_institution'))
        evidence_capital = compact_evidence(data.get('evidence_capital'))

        def source_score(key, label, score, cap):
            if not availability[key]:
                return f"{label}未覆盖"
            neutral = float(neutral_scores[key])
            adjustment = adjustments[key]
            if adjustment is None:
                adjustment = float(score) - neutral
            return f"{label}{score}/{cap}（中性{neutral:g}，较中性{float(adjustment):+.1f}）"

        five_source_line = (
            f"基础评分: {data.get('base_score', 70)}分；五源约50分为中性\n"
            + " | ".join((
                source_score('news', '资讯', sn, 25),
                source_score('announce', '公告', sa, 20),
                source_score('community', '社区', sc, 25),
                source_score('institution', '机构', si, 20),
                source_score('capital', '资金', sk, 10),
            ))
        )
        cap_line = f"资金异动: {cap_dir or 'N/A'}"
        if post_count and (bull_pct or bear_pct):
            cap_line += (
                f" | 社区多空: 看涨{bull_pct:.0%} / 看跌{bear_pct:.0%} ({post_count}条)"
            )

        if market == 'hk':
            score_context = (
                f"港股综合基础评分: {data.get('base_score', 70)}分"
                "（本次LLM仅在-10到+10范围验真调整）\n"
                + five_source_line
            )
            market_context = (
                "港股市场环境:\n"
                f"- 综合情绪: {format_metric(data.get('hk_sentiment_score'), 1)}/100"
                f" | VHSI: {format_metric(data.get('vhsi'), 2)} {data.get('vhsi_sentiment') or ''}\n"
                f"- 港股通资金流: {format_metric(data.get('hk_capital_flow'), 2, '亿港元')}"
                f" {data.get('hk_flow_sentiment') or ''}"
                f" | 牛熊证比例: {format_metric(data.get('bull_bear_ratio'), 2)}"
                f" {data.get('warrant_sentiment') or ''}\n"
                f"- 指数归属: {data.get('index_membership') or '未覆盖'}"
                f" | 行情源: {data.get('quote_source') or '未覆盖'}"
                f" | 市场新闻情绪均值: {format_metric(data.get('market_news_sentiment'), 2)}"
            )
            source_context = (
                "港股五源真实证据:\n"
                f"- 国际资讯: {evidence_news if availability['news'] else '资讯未覆盖'}\n"
                f"- 官方公告: {evidence_announce if availability['announce'] else '公告未覆盖'}\n"
                f"- 社区情绪: {evidence_community if availability['community'] else '社区未覆盖'}\n"
                f"- 机构观点: {evidence_institution if availability['institution'] else '机构未覆盖'}\n"
                f"- 资金异动: {evidence_capital if availability['capital'] else '资金未覆盖'}"
            )
            evaluation_basis = (
                '港股综合基础评分 + 技术面 + 轻量基本面 + '
                '港股市场环境 + 五源真实证据 + 上述新闻事件'
            )
        else:
            score_context = five_source_line
            market_context = cap_line + f"\n新闻情绪均值: {data.get('sentiment', 'N/A')}"
            source_context = (
                "五源真实证据:\n"
                f"- 国际资讯: {evidence_news if availability['news'] else '资讯未覆盖'}\n"
                f"- 官方公告: {evidence_announce if availability['announce'] else '公告未覆盖'}\n"
                f"- 社区情绪: {evidence_community if availability['community'] else '社区未覆盖'}\n"
                f"- 机构观点: {evidence_institution if availability['institution'] else '机构未覆盖'}\n"
                f"- 资金异动: {evidence_capital if availability['capital'] else '资金未覆盖'}"
            )
            evaluation_basis = '技术面 + 轻量基本面 + 五源评分 + 上述新闻事件'

        return f"""你是专业的{market_name}股票分析师。

股票: {symbol}
市场: {market_name}
当前价格: ${data.get('price', 'N/A')}
涨跌幅: {data.get('change_pct', 0):+.2f}%
RSI: {data.get('rsi', 'N/A')}
MA20/MA50: {data.get('ma20', 'N/A')}/{data.get('ma50', 'N/A')}
成交量比率: {data.get('volume_ratio', 'N/A')}x
ATR: {data.get('atr', 'N/A')}

技术结构:
- MACD: {data.get('macd_state') or '未覆盖'}（MACD {format_metric(data.get('macd'), 4)} / Signal {format_metric(data.get('macd_signal'), 4)}）
- MA20近5日斜率: {format_metric(data.get('ma20_slope_pct'), 2, '%')} | 价格高于MA20: {format_bool(data.get('price_above_ma20'))} | 高于MA50: {format_bool(data.get('price_above_ma50'))}
- 最近5日/20日涨跌: {format_metric(data.get('return_5d_pct'), 2, '%')} / {format_metric(data.get('return_20d_pct'), 2, '%')}
- 距20日高点: {format_metric(data.get('distance_20d_high_pct'), 2, '%')} | 当日高点回撤: {format_metric(data.get('intraday_drawdown_pct'), 2, '%')}

轻量基本面:
- 行业: {data.get('sector') or '未覆盖'} | 市值: {format_large(data.get('market_cap'))}
- PE(TTM/Forward): {format_metric(data.get('trailing_pe'))} / {format_metric(data.get('forward_pe'))} | PB: {format_metric(data.get('pb_ratio'))}
- EPS: {format_metric(data.get('trailing_eps'))} | 营收增长: {format_metric(data.get('revenue_growth'), 2, '%')} | 盈利增长: {format_metric(data.get('earnings_growth'), 2, '%')}
- 利润率: {format_metric(data.get('profit_margin'), 2, '%')} | 营收: {format_large(data.get('revenue'))} | 净利润: {format_large(data.get('net_profit'))}

{score_context}
{market_context}

{source_context}

{news_section_title}:
{news_block}

请结合{evaluation_basis}综合判断；未覆盖字段必须忽略，不得补写或推测。给出：
1. 评分调整（-10到+10），按以下场景对号入座：

   🔴 减分场景（-3 到 -8）：
   - 涨幅已大但无新催化剂（已被透支）
   - 技术面无明显突破信号，横盘整理
   - 消息面利好已被市场充分定价
   - 成交量萎缩，动能减弱
   - 资金净流出 + 社区看跌占比高（>50%）
   - 当日涨幅明显且由单一消息事件驱动（如财报、并购、政策），需判断该利好是否已被市场充分定价、后续是否还有上涨空间；若判断利好已透支，给-3到-5分
   - 重大利空（诉讼/调查/召回/调低评级）请加大负分（-9 到 -10）

   🟢 加分场景（+3 到 +8）：
   - 财报超预期且市场反应不足
   - 机构集中上调目标价
   - 新业务/新订单/新政策直接受益
   - 技术突破配合成交量放大
   - 资金净流入 + 社区看涨占比高（>60%）
   - 重大利好（超预期/回购/中标/获批）请加大正分（+9 到 +10）

   ⚪ 中性场景（0 到 ±2）：已涨过但仍在竞争市场、技术面中立、无明显驱动事件

2. 一句话验真理由（60-180字，且与打分方向一致）：
   - 必须包含核心新闻催化或利空；
   - 必须结合至少一项技术面或资金面证据确认或否定新闻影响；
   - 必须指出一个基于输入数据的主要风险或不确定性；
   - 只使用输入中明确提供的事实，不得编造公告、评级、资金或技术信号；
   - 新闻中出现的盘前、盘后、收盘、交易日等时段必须原样保留；不得把盘前/盘后涨跌改写为盘中回落，也不得把不同交易日串成同一日内走势；
   - 不要只复述新闻标题，不要使用“前景良好”“值得关注”等空泛结论。
   - 富途新闻事件池只提供原始事件；不要沿用标题关键词数量作为结论，必须自行判断事件方向、真实性与影响。

⚠️ 判分原则：如果理由中出现”无突破/无明显/横盘/已被透支/动能减弱/涨过”等关键词，必须给负分；不要出现”理由偏弱但调整为正分”的矛盾情况。

格式：只返回一个JSON对象，不要Markdown代码块，不要额外文字。
例如：{{"adjust":8,"reason":"Vera CPU与H200许可构成明确催化，成交量放大及资金净流入确认上涨动能，但利好可能已部分计价，需防范冲高回落"}}
或：{{"adjust":-10,"reason":"SEC调查与评级下调形成明确利空，价格跌破MA20且资金持续流出确认弱势，短期仍有进一步下探风险"}}
adjust必须是-10到+10之间的整数。

直接回复："""

    def _parse(self, content, data, fallback=True):
        base_score = data.get('base_score', 70)
        text = (content or '').strip()
        try:
            cleaned = text.strip(chr(96)).strip()
            if cleaned.lower().startswith('json'):
                cleaned = cleaned[4:].strip()
            payload = None
            try:
                payload = json.loads(cleaned)
            except Exception:
                json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if json_match:
                    payload = json.loads(json_match.group())

            if isinstance(payload, dict) and 'adjust' in payload:
                adjust = int(round(float(payload.get('adjust', 0))))
                reason = str(payload.get('reason', '') or '').strip()
            else:
                normalized = cleaned.replace('，', ',')
                line_match = re.search(
                    r'调整分\s*[:：]\s*([-+]?\d+)\s*(?:\|\s*理由\s*[:：]\s*)?(.*)',
                    normalized,
                    re.DOTALL,
                )
                if line_match:
                    adjust = int(line_match.group(1))
                    reason = line_match.group(2).strip()
                    parts = None
                    adjust_match = True
                else:
                    parts = normalized.split(',', 1)
                    adjust_match = re.fullmatch(r'\s*([-+]?\d+)\s*', parts[0])
                if not adjust_match:
                    raise ValueError('missing adjustment')
                if parts is not None:
                    adjust = int(adjust_match.group(1))
                    reason = parts[1].strip() if len(parts) > 1 else ''

            if not -10 <= adjust <= 10:
                raise ValueError('adjustment out of range')
            final = max(0, min(100, base_score + adjust))
            detailed_reason = reason[:180] if reason else 'LLM分析'
            return {
                'symbol': data.get('symbol', 'UNKNOWN'),
                'base_score': base_score,
                'score_adjust': adjust,
                'llm_reason': f'{adjust:+d}分；{detailed_reason}',
                'final_score': final,
                'timestamp': datetime.now().isoformat(),
                'passed': True,
                'llm_status': 'parsed',
            }
        except Exception:
            if not fallback:
                return None
            return self._fallback(data, f"解析失败:{text[:20]}")

    def _fallback(self, data, reason):
        base = data.get('base_score', 70)
        return {
            'symbol': data.get('symbol', 'UNKNOWN'),
            'base_score': base,
            'score_adjust': 0,
            'llm_reason': reason,
            'final_score': base,
            'timestamp': datetime.now().isoformat(),
            'passed': False,
            'llm_status': 'failed',
        }


class LLMExitAnalyzer:
    """卖出/平仓 LLM 复盘分析器。

    输入：开仓快照 + 当前持仓快照 + 触发原因 + 技术指标快照 + 市场情绪。
    输出：动态的卖出原因（用人话讲清楚为什么亏/为什么赚 + 教训），
         作为飞书通知的"原因:"字段。
    """

    def __init__(self):
        self.client = LLMClient()

    def analyze(self, symbol, exit_data):
        """分析卖出原因

        Args:
            symbol: 股票代码
            exit_data: dict，期望字段：
                - market: us|hk
                - side: 'BUY'|'SELL'
                - stop_type: take_profit|max_loss_stop|tightened_atr_stop|...
                - entry_price, exit_price, pnl_pct
                - entry_time, exit_time, holding_days
                - entry_score, entry_reasons (开仓时的评分/理由)
                - rsi, ma20, ma50, atr, volume_ratio, macd_death_cross
                - vix, cnn_fg, sentiment, market_change_pct (市场环境)
                - raw_reason: 系统给出的原始标签('止盈'/'止损全平'/...)
        Returns:
            dict: { 'verdict': 一句话结论, 'detail': 多行复盘, 'lesson': 经验教训, 'llm_reason': 组合后供通知直接用 }
        """
        if not self.client.api_key or self.client.api_key.startswith("sk-xxx"):
            return self._exit_fallback(exit_data, "无API Key")

        prompt = self._build_exit_prompt(symbol, exit_data)
        content = self.client.call(prompt, max_tokens=800, temperature=0.3)
        if not content:
            return self._exit_fallback(exit_data, "LLM调用失败")
        return self._parse_exit(content, exit_data)

    def _build_exit_prompt(self, symbol, d):
        market_name = '美股' if d.get('market', 'us') == 'us' else '港股'
        stop_type_label = {
            'take_profit': '止盈',
            'max_loss_stop': '止损全平',
            'tightened_atr_stop': '收紧ATR止损',
            'staged_reduction': '分级减仓',
            'major_negative': '重大利空',
        }.get(d.get('stop_type', ''), d.get('raw_reason', '平仓'))

        # 2026-06-24 east 修复:
        #   - 区分入场上下文是否可用，缺失时明确告诉 LLM 不要臆测
        #   - 技术指标统一标注为「卖出时点」，避免被描述为入场量能
        entry_reasons_list = [r for r in (d.get('entry_reasons', []) or []) if r]
        entry_score = int(d.get('entry_score', 0) or 0)
        entry_ctx_ok = bool(d.get('entry_context_available')) or bool(entry_reasons_list) or entry_score > 0
        entry_reasons_text = '\n  '.join(entry_reasons_list) if entry_reasons_list else '(未记录，该持仓可能为外部同步或早期建仓老仓位)'
        entry_score_text = f"{entry_score} 分" if entry_score > 0 else '(未记录)'
        pnl_pct = d.get('pnl_pct', 0)
        is_profit = pnl_pct >= 0

        if entry_ctx_ok:
            entry_rule = '可在复盘中结合"入场评分/入场理由"判断入场是否合理。'
        else:
            entry_rule = ('⚠️ 本次未记录入场评分与入场理由（可能为外部同步/手工建仓老仓位）。'
                          '严禁臆测"入场量能偏弱/入场信号不足"等未知信息，'
                          '复盘只能基于卖出时点的技术快照、市场环境与系统止损规则。')

        def _show(v, suffix=''):
            return f"{v}{suffix}" if v is not None else 'N/A'
        rsi = d.get('exit_rsi', d.get('rsi'))
        ma20 = d.get('exit_ma20', d.get('ma20'))
        ma50 = d.get('exit_ma50', d.get('ma50'))
        atr = d.get('exit_atr', d.get('atr'))
        vol_ratio = d.get('exit_volume_ratio', d.get('volume_ratio'))
        macd_dc = d.get('exit_macd_death_cross', d.get('macd_death_cross'))
        vol_text = f"{vol_ratio}x" if vol_ratio is not None else 'N/A'

        return f"""你是一名严谨的{market_name}量化交易复盘师。请基于以下持仓数据，针对本次{stop_type_label}给出复盘分析。

标的: {symbol}（{market_name}）
触发动作: {stop_type_label}（系统原始原因: {d.get('raw_reason','')}）

== 持仓档案 ==
入场价: ${d.get('entry_price', 0):.2f}
卖出价: ${d.get('exit_price', 0):.2f}
盈亏: {pnl_pct:+.2f}%
持有天数: {d.get('holding_days', 0)} 天
入场评分: {entry_score_text}
入场理由:
  {entry_reasons_text}

== 入场上下文说明 ==
{entry_rule}

== 卖出时点技术快照（注意：下面指标是卖出时点，不是入场时点） ==
RSI: {_show(rsi)}
MA20/MA50: {_show(ma20)}/{_show(ma50)}
ATR: {_show(atr)}
成交量比率: {vol_text}
MACD死叉: {_show(macd_dc)}

== 市场环境快照 ==
VIX: {d.get('vix', 'N/A')}
CNN恐慌贪婪: {d.get('cnn_fg', 'N/A')}
大盘当日涨跌: {d.get('market_change_pct', 'N/A')}%
新闻情绪: {d.get('sentiment', 'N/A')}

复盘硬约束：
1. 只能基于上面明确给出的数据。出现 "N/A" 或 "(未记录)" 的字段，严禁猜测。
2. 上面技术指标是卖出时点的，不能被描述为"入场时量能"或"入场时MA"。
3. 若"入场上下文说明"提示记录缺失，请明确写出"入场上下文不可考"，不要虚构入场原因。
4. 禁止使用以下套话除非数据明确支持："入场量能偏弱""缺乏有效支撑""严格执行纪律""量价共振""日内短线敞口"。

请用中文输出严格 JSON 对象，仅含三个键，键名固定为："结论"、"复盘"、"教训"。
每个键的值是短字符串：
- "结论": {'本次盈利的核心驱动' if is_profit else '本次亏损的核心原因'}（一句话，需引用具体数字或规则）
- "复盘": 结合卖出时点指标与市场环境给出原因分析（2句以内）
- "教训": 下次类似情况建议怎么改进策略（1句话，针对可验证的规则）

严格只输出 JSON，不要 ```json 代码块标记，不要任何多余文字或换行评注。示例：
{{"结论": "...", "复盘": "...", "教训": "..."}}"""

    def _parse_exit(self, content, d):
        text = content.strip()
        verdict = detail = lesson = ''
        # 去掉可能的 markdown 代码块围栏 ```json ... ``` / ``` ... ```
        cleaned = re.sub(r'^[`\s]*json?[`\s]*', '', text, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'```$', '', cleaned).strip()
        try:
            # 优先尝试 LLM 输出为 JSON 对象（{"结论":..., "复盘":..., "教训":...}）
            payload = json.loads(cleaned)
            if isinstance(payload, dict):
                verdict = str(payload.get('结论') or payload.get('verdict') or payload.get('conclusion') or '').strip()
                detail = str(payload.get('复盘') or payload.get('detail') or payload.get('analysis') or '').strip()
                lesson = str(payload.get('教训') or payload.get('lesson') or '').strip()
        except Exception:
            # JSON 不完整（可能被截断），用正则尽量抽取三个字段
            def _field(key):
                m = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', cleaned)
                return m.group(1).strip() if m else ''
            verdict = _field('结论') or _field('verdict') or _field('conclusion')
            detail = _field('复盘') or _field('detail') or _field('analysis')
            lesson = _field('教训') or _field('lesson')

        if not verdict and not detail and not lesson:
            # JSON 解析失败，退回按行前缀解析
            try:
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith('【结论】'):
                        verdict = line.replace('【结论】', '').strip()
                    elif line.startswith('【复盘】'):
                        detail = line.replace('【复盘】', '').strip()
                    elif line.startswith('【教训】'):
                        lesson = line.replace('【教训】', '').strip()
            except Exception:
                pass

        if not verdict and not detail and not lesson:
            # 解析失败，原文兜底
            verdict = text[:120]

        combined = self._format_combined(d, verdict, detail, lesson)
        return {
            'verdict': verdict,
            'detail': detail,
            'lesson': lesson,
            'llm_reason': combined,
            'timestamp': datetime.now().isoformat(),
        }

    def _format_combined(self, d, verdict, detail, lesson):
        """组合成飞书通知里"原因:"字段直接展示的文字。"""
        raw = d.get('raw_reason', '平仓')
        parts = [f"🤖 {raw}"]
        if verdict:
            parts.append(f"📌 {verdict}")
        if detail:
            parts.append(f"🔍 {detail}")
        if lesson:
            parts.append(f"💡 {lesson}")
        return '\n'.join(parts)

    def _exit_fallback(self, d, reason):
        raw = d.get('raw_reason', '平仓')
        pnl = d.get('pnl_pct', 0)
        combined = f"🤖 {raw}\n📌 LLM复盘暂不可用（{reason}），盈亏 {pnl:+.2f}%"
        return {
            'verdict': '',
            'detail': '',
            'lesson': '',
            'llm_reason': combined,
            'timestamp': datetime.now().isoformat(),
        }


# ===== 便捷函数 =====

def analyze_stock(symbol, market_data):
    """便捷函数：分析单只股票（扫描器用）"""
    analyzer = LLMStockAnalyzer()
    result = analyzer.analyze(symbol, market_data)

    print(f"\n📊 LLM分析 - {symbol}")
    print(f"   基础评分: {result['base_score']}")
    print(f"   LLM调整: {result['score_adjust']:+d}")
    print(f"   最终评分: {result['final_score']}")
    print(f"   理由: {result['llm_reason']}")

    return result


def analyze_exit(symbol, exit_data):
    """便捷函数：分析卖出原因（auto-trader 卖出通知用）"""
    analyzer = LLMExitAnalyzer()
    result = analyzer.analyze(symbol, exit_data)
    print(f"\n🤖 LLM卖出复盘 - {symbol}")
    print(f"   结论: {result.get('verdict', '')}")
    print(f"   复盘: {result.get('detail', '')}")
    print(f"   教训: {result.get('lesson', '')}")
    return result


def get_llm_client():
    """便捷函数：获取LLMClient实例（日报/周报用）"""
    return LLMClient()


if __name__ == '__main__':
    client = LLMClient()

    print("="*50)
    print("🧪 测试通用LLM调用...")
    result = client.call('1+1=? 只回答数字', max_tokens=10, temperature=0.1)
    print(f"结果: {result}")

    print("="*50)
    print("🧪 测试股票分析...")
    test_us = {
        'symbol': 'AAPL',
        'market': 'us',
        'base_score': 75,
        'price': 175.50,
        'change_pct': 2.5,
        'rsi': 55,
        'ma20': 170,
        'ma50': 168,
        'volume_ratio': 1.8,
        'atr': 3.5,
        'sentiment': '正面'
    }
    result_us = analyze_stock('US.AAPL', test_us)
    print(f"最终评分: {result_us['final_score']}")
    print("="*50)
