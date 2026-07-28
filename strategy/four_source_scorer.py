#!/usr/bin/env python3
"""
五源共振真实评分模块
2026-06-24 east 新建：彻底替代"硬拆 base_score"的假五源。
2026-07-02 east 更新：所有第一层数据源全部接入作为备用源（Finnhub/AlphaVantage/yfinance/TinkClaw/长桥/富途）
五个维度，每个维度有独立的数据源、抓取方法、打分规则，零硬拆。
权重设计:
  美股:  国际资讯 25 + 官方公告 20 + 社区情绪 25 + 机构观点 20 + 资金异动 10 = 100
  港股:  国际资讯 25 + 港股公告 20 + 国内社区 25 + 机构/海外社交 20 + 资金异动 10 = 100
每个维度返回:
  {
    'score': int,           # 0~cap
    'available': bool,      # True=有真实数据；False=无数据
    'evidence': str,        # 通知用一句话证据
    'raw': {...}
  }
"""

import os
import sys
import json
import re
import html
import sqlite3
import requests
import time
import threading
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from runtime_config import (
    DATA_DIR,
    FUTU_HOST,
    FUTU_PORT,
    NEWS_DB_PATH,
    PYTHON_BIN,
    SKILLS_DIR,
    load_api_keys,
)

# 备用数据源配置
FUTU_NEWS_API = 'https://ai-news-search.futunn.com/news_search'
REQUEST_DELAY = 0.2  # 请求间隔避免429限流
_last_request_time = 0
_rate_limit_lock = threading.Lock()

def _rate_limit():
    """简单限流避免API 429"""
    global _last_request_time
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        _last_request_time = time.time()


_SOURCE_CACHE_LOCK = threading.Lock()
ANNOUNCE_CACHE_SCHEMA = 'v3'

def _cached_source(cache_key: str, ttl_seconds: int, fetcher):
    """Persist slow-changing real source results in the existing news.db."""
    now = time.time()
    try:
        with _SOURCE_CACHE_LOCK:
            conn = sqlite3.connect(NEWS_DB_PATH, timeout=10)
            conn.execute(
                'CREATE TABLE IF NOT EXISTS five_source_cache '
                '(cache_key TEXT PRIMARY KEY, updated_at REAL NOT NULL, payload TEXT NOT NULL)'
            )
            row = conn.execute(
                'SELECT updated_at, payload FROM five_source_cache WHERE cache_key = ?',
                (cache_key,)
            ).fetchone()
            conn.close()
        if row and now - float(row[0]) < ttl_seconds:
            return json.loads(row[1])
    except Exception:
        pass

    result = fetcher()
    if isinstance(result, dict) and result.get('available'):
        try:
            with _SOURCE_CACHE_LOCK:
                conn = sqlite3.connect(NEWS_DB_PATH, timeout=10)
                conn.execute(
                    'INSERT OR REPLACE INTO five_source_cache(cache_key, updated_at, payload) VALUES (?, ?, ?)',
                    (cache_key, now, json.dumps(result, ensure_ascii=False))
                )
                conn.commit()
                conn.close()
        except Exception:
            pass
    return result


def _load_keys() -> Dict[str, Any]:
    return load_api_keys()


_KEYS = _load_keys()
FINNHUB_KEY = _KEYS.get('finnhub', {}).get('api_key', '')
ALPHAVANTAGE_KEY = _KEYS.get('alphavantage', {}).get('api_key', '')
TINKCLAW_KEY = _KEYS.get('tinkclaw', {}).get('api_key', '')
LONGBRIDGE_TOKEN = _KEYS.get('longbridge', {}).get('token', '')

POSITIVE_WORDS = [
    'beat', 'beats', 'surge', 'surges', 'soar', 'soars', 'jump', 'jumps',
    'rally', 'rallies', 'strong', 'record', 'profit', 'gain', 'gains',
    'outperform', 'bull', 'raise', 'raises', 'raised', 'upgrade', 'upgrades',
    'boost', 'boosts', 'growth', 'demand', 'visibility', 'tops', 'above'
]
NEGATIVE_WORDS = [
    'miss', 'misses', 'plunge', 'plunges', 'crash', 'crashes', 'downgrade',
    'downgrades', 'lawsuit', 'investigation', 'warning', 'loss', 'cut',
    'cuts', 'concern', 'risk', 'fall', 'falls', 'bear', 'sue', 'weak'
]
EVENT_TYPE_RULES = (
    {
        'type': 'earnings_surprise', 'strength': 1.0,
        'positive': ('beats estimates', 'beat estimates', 'beats expectations',
                     'beat expectations', '财报超预期', '业绩超预期', '大幅超预期'),
        'negative': ('misses estimates', 'missed estimates', 'misses expectations',
                     'missed expectations', '财报不及预期', '业绩不及预期', '业绩暴雷'),
    },
    {
        'type': 'guidance_change', 'strength': 1.0,
        'positive': ('raises guidance', 'raised guidance', 'guidance raised',
                     'raises outlook', '上调指引', '上调业绩预期'),
        'negative': ('cuts guidance', 'cut guidance', 'guidance cut',
                     'lowers outlook', '下调指引', '下调业绩预期'),
    },
    {
        'type': 'major_contract', 'strength': 1.0,
        'positive': ('wins major contract', 'secures major contract',
                     'awarded major contract', 'major contract awarded',
                     '获得重大订单', '签署重大合同', '重大中标'),
        'negative': ('loses major contract', 'major contract cancelled',
                     '重大订单取消', '重大合同终止'),
    },
    {
        'type': 'regulatory_decision', 'strength': 1.0,
        'positive': ('fda approves', 'regulatory approval', 'approved by regulators',
                     '获监管批准', '获得批准', '批准上市', '采购许可', '解除限制'),
        'negative': ('fda rejects', 'approval denied', 'regulatory rejection',
                     '监管拒绝', '未获批准', '禁止销售'),
    },
    {
        'type': 'severe_risk', 'strength': 1.0,
        'positive': ('resumes trading after suspension', '解除退市风险', '恢复交易'),
        'negative': ('accounting fraud', 'files for bankruptcy', 'major recall',
                     'forced delisting', '重大召回', '财务造假', '申请破产',
                     '强制退市', '重大违约'),
    },
    {
        'type': 'record_results', 'strength': 0.75,
        'positive': ('record revenue', 'record profit', 'record earnings',
                     '创纪录营收', '创纪录利润', '盈利创纪录'),
        'negative': ('record loss', '创纪录亏损', '亏损创纪录'),
    },
    {
        'type': 'corporate_transaction', 'strength': 0.75,
        'positive': ('enters acquisition agreement', 'signs acquisition agreement',
                     'enters merger agreement', 'signs merger agreement',
                     'merger approved', 'completes acquisition', 'strategic acquisition',
                     '签署并购协议', '完成收购', '完成合并'),
        'negative': ('terminates acquisition', 'merger terminated',
                     'merger agreement terminated', 'deal collapsed',
                     '终止收购', '并购终止', '交易告吹'),
    },
    {
        'type': 'material_risk', 'strength': 0.75,
        'positive': (),
        'negative': ('trading suspension', 'bankruptcy warning', 'delisting notice',
                     'major sanction', '暂停交易', '破产警告', '退市通知', '重大制裁'),
    },
    {
        'type': 'analyst_rating', 'strength': 0.45,
        'positive': ('rating upgraded', 'upgrades stock', 'upgraded stock',
                     'upgrades to buy', 'upgraded to buy', 'upgraded from sell',
                     'upgrades from sell', 'raises rating', 'maintains buy rating',
                     'reiterates buy rating', 'initiates with buy rating', 'rated buy',
                     '上调评级', '买入评级', '增持评级'),
        'negative': ('rating downgraded', 'downgrades stock', 'downgraded stock',
                     'downgrades to sell', 'downgraded to sell', 'downgraded from buy',
                     'downgrades from buy', 'cuts rating', 'maintains sell rating',
                     'reiterates sell rating', 'initiates with sell rating', 'rated sell',
                     'sell call',
                     '下调评级', '卖出评级', '减持评级'),
    },
    {
        'type': 'contract_order', 'strength': 0.45,
        'positive': ('wins contract', 'secures contract', 'awarded contract',
                     'signs contract', 'receives order', 'receives new order',
                     'signs partnership agreement',
                     'enters partnership', '中标', '获得订单', '签署订单', '签署合作'),
        'negative': ('contract cancelled', 'contract terminated', 'order cancelled',
                     'partnership terminated', 'loses contract',
                     '订单取消', '合同终止', '失去合同'),
    },
    {
        'type': 'capital_return', 'strength': 0.45,
        'positive': ('share buyback', 'stock buyback', 'repurchase program',
                     '回购股份', '股份回购', '提高股息', '增加分红'),
        'negative': ('suspends buyback', 'cuts dividend', 'suspends dividend',
                     '暂停回购', '削减股息', '暂停分红'),
    },
    {
        'type': 'legal_investigation', 'strength': 0.45,
        'positive': ('lawsuit dismissed', 'investigation closed', '诉讼驳回', '调查结束'),
        'negative': ('lawsuit filed', 'under investigation', 'regulatory probe',
                     'class action', '遭到诉讼', '接受调查', '监管调查', '集体诉讼'),
    },
    {
        'type': 'product_operation', 'strength': 0.45,
        'positive': ('launches product', 'launches new', 'market share gains',
                     'strong demand', 'breakthrough', '发布新产品', '市场份额提升',
                     '需求强劲', '突破性进展', '恢复销售'),
        'negative': ('product delay', 'launch delayed', 'production halt',
                     'weak demand', 'supply disruption',
                     '产品延期', '停产', '需求疲软', '供应中断'),
    },
    {
        'type': 'analyst_target', 'strength': 0.25,
        'positive': ('raises price target', 'price target raised', '上调目标价'),
        'negative': ('cuts price target', 'lowers price target', 'price target cut',
                     '下调目标价'),
    },
    {
        'type': 'business_outlook', 'strength': 0.25,
        'positive': ('expects growth', 'growth expected', 'may benefit',
                     '预计增长', '有望增长', '可能受益'),
        'negative': ('expects decline', 'decline expected', 'growth slowdown',
                     '预计下滑', '增长放缓', '可能受损'),
    },
)

EVENT_TYPE_LABELS = {
    'earnings_surprise': '财报偏差', 'guidance_change': '业绩指引',
    'major_contract': '重大订单', 'regulatory_decision': '监管决定',
    'severe_risk': '严重风险', 'record_results': '创纪录业绩',
    'corporate_transaction': '并购交易', 'material_risk': '重大风险',
    'analyst_rating': '机构评级', 'contract_order': '订单合作',
    'capital_return': '回购分红', 'legal_investigation': '诉讼调查',
    'product_operation': '产品经营', 'analyst_target': '目标价',
    'business_outlook': '经营预期', 'major_alert': '重大告警',
    'sentiment_fallback': '情绪兜底', 'structured_event': '结构化事件',
    'insider_transaction': '内部人交易', 'clarification': '澄清事件',
    'neutral': '中性事件',
}

RUMOR_TERMS = (
    'rumor', 'rumoured', 'reportedly', 'sources say', 'could ',
    'in talks', 'considering', '传闻', '据悉', '消息称', '可能', '或将', '洽谈', '考虑',
)
ANNOUNCE_WORDS = [
    'earnings', 'results', 'revenue', 'eps', 'guidance', 'forecast',
    'quarter', 'q1', 'q2', 'q3', 'q4', 'fiscal', 'outlook'
]


def _clean_symbol(symbol: str) -> str:
    sym = (symbol or '').upper()
    for prefix in ('US.', 'HK.'):
        if sym.startswith(prefix):
            sym = sym[len(prefix):]
            break
    return sym.split('.')[0]


def _clean_title(value: str) -> str:
    """Remove feed highlight markup before dedupe, matching, and display."""
    return re.sub(r'<[^>]+>', '', html.unescape(str(value or ''))).strip()


def _company_aliases(company_name: str) -> List[str]:
    """Build conservative aliases from the scanner's real company name."""
    clean_name = _clean_title(company_name).strip()
    if not clean_name:
        return []

    aliases = {clean_name.lower()}
    ascii_name = re.sub(r'[^a-z0-9]+', ' ', clean_name.lower()).strip()
    suffixes = {
        'inc', 'incorporated', 'corp', 'corporation', 'co', 'company', 'ltd',
        'limited', 'plc', 'holdings', 'holding', 'group', 'class', 'adr',
    }
    words = ascii_name.split()
    while words and (words[-1] in suffixes or words[-1] in {'a', 'b'}):
        words.pop()
    if words:
        aliases.add(' '.join(words))
        if len(words[0]) >= 4:
            aliases.add(words[0])

    chinese_name = re.sub(
        r'(股份有限公司|有限公司|控股集团|控股|集团|-?[A-Z]+)$',
        '',
        clean_name,
        flags=re.IGNORECASE,
    ).strip()
    if chinese_name and chinese_name != clean_name and len(chinese_name) >= 2:
        aliases.add(chinese_name.lower())
    return sorted(alias for alias in aliases if len(alias) >= 2)


def _is_company_relevant(text: str, symbol: str, company_name: str = '',
                         extra_aliases: Optional[List[str]] = None) -> bool:
    """Require a ticker or company-name match when an API returns a broad feed."""
    clean_text = _clean_title(text).lower()
    clean_symbol = _clean_symbol(symbol).lower()
    if len(clean_symbol) >= 3 and re.search(
        rf'(?<![a-z0-9]){re.escape(clean_symbol)}(?![a-z0-9])', clean_text
    ):
        return True
    if len(clean_symbol) < 3 and re.search(
        rf'(?<![a-z0-9]){re.escape(clean_symbol)}(?:\.[a-z])?(?![a-z0-9])',
        clean_text,
    ):
        return True
    aliases = set(_company_aliases(company_name))
    aliases.update(_clean_title(alias).lower() for alias in (extra_aliases or []))
    for alias in sorted(alias for alias in aliases if len(alias) >= 2):
        if re.search(r'[a-z0-9]', alias):
            compact_alias = re.sub(r'[^a-z0-9]', '', alias)
            if len(compact_alias) < 4:
                continue
            if re.search(rf'(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])', clean_text):
                return True
        elif alias in clean_text:
            return True
    return False


def _futu_query_aliases(items: List[Dict[str, Any]], symbol: str,
                        company_name: str = '') -> List[str]:
    """Derive translated company names adjacent to Futu's highlighted ticker."""
    aliases = set(_company_aliases(company_name))
    ticker = re.compile(
        rf'<em>\s*{re.escape(_clean_symbol(symbol))}\s*</em>',
        re.IGNORECASE,
    )
    for item in items:
        raw_title = str(item.get('title') or '')
        for match in ticker.finditer(raw_title):
            before = re.sub(r'[（(]\s*$', '', raw_title[:match.start()])
            segment = re.split(r'[，,。；;：:、!?！？|]', before)[-1]
            segment = _clean_title(segment).strip(' -–—')
            if re.fullmatch(r'[\u4e00-\u9fff]{2,10}', segment):
                aliases.add(segment.lower())
    return sorted(alias for alias in aliases if len(alias) >= 2)


def _is_futu_query_relevant(raw_title: str, symbol: str,
                            company_name: str, aliases: List[str]) -> bool:
    clean_symbol = _clean_symbol(symbol)
    if re.search(
        rf'<em>\s*{re.escape(clean_symbol)}\s*</em>',
        str(raw_title or ''),
        re.IGNORECASE,
    ):
        return True
    if _is_company_relevant(raw_title, clean_symbol, company_name, aliases):
        return True
    # Longer tickers are distinctive enough for Futu's own search ranking; strict
    # filtering is reserved for one- and two-character symbols such as C, F, T, MU.
    return len(clean_symbol) > 2


def _empty(cap: int, reason: str) -> Dict[str, Any]:
    return {
        'score': 0,
        'available': False,
        'evidence': f'未覆盖（{reason}）',
        'neutral_score': cap / 2,
        'score_adjustment': None,
        'raw': {'reason': reason},
    }


def _count_keywords(text: str, words: List[str]) -> int:
    text = (text or '').lower()
    return sum(1 for w in words if w in text)


def _half_up(value: float) -> int:
    return int(float(value) + 0.5)


def _dimension_result(score: float, cap: int, evidence: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    neutral = cap / 2
    final_score = max(0, min(cap, _half_up(score)))
    adjustment = round(final_score - neutral, 1)
    payload = dict(raw or {})
    payload['neutral_score'] = neutral
    payload['score_adjustment'] = adjustment
    return {
        'score': final_score,
        'available': True,
        'evidence': evidence,
        'neutral_score': neutral,
        'score_adjustment': adjustment,
        'raw': payload,
    }


def _matches_event_phrase(text: str, phrase: str) -> bool:
    if re.fullmatch(r'[a-z0-9 ]+', phrase):
        pattern = re.escape(phrase).replace(r'\ ', r'\s+')
        return bool(re.search(rf'(?<![a-z0-9]){pattern}(?![a-z0-9])', text))
    return phrase in text


def _event_certainty_multiplier(text: str) -> float:
    return 0.4 if any(term in text for term in RUMOR_TERMS) else 1.0


def _ratio_event_strength(ratio: float) -> float:
    magnitude = abs(float(ratio))
    if magnitude >= 0.15:
        return 1.0
    if magnitude >= 0.08:
        return 0.75
    if magnitude >= 0.03:
        return 0.45
    if magnitude >= 0.01:
        return 0.25
    return 0.0


def _event_strength(title: str, sentiment: Any = 0.5,
                    alert_type: str = '', importance: str = '') -> Dict[str, Any]:
    """Classify one event by type; keyword frequency never increases strength."""
    text_value = _clean_title(title).lower()
    pos_strength = 0.0
    neg_strength = 0.0
    pos_type = 'neutral'
    neg_type = 'neutral'

    for rule in EVENT_TYPE_RULES:
        strength = float(rule['strength'])
        if any(_matches_event_phrase(text_value, phrase) for phrase in rule['positive']):
            if strength > pos_strength:
                pos_strength = strength
                pos_type = str(rule['type'])
        if any(_matches_event_phrase(text_value, phrase) for phrase in rule['negative']):
            if strength > neg_strength:
                neg_strength = strength
                neg_type = str(rule['type'])

    clarification = bool(
        re.search(
            r"\b(denies|denied|dismisses|rejects)\b.{0,40}"
            r"\b(bankruptcy|fraud|delisting|default|sell call)\b",
            text_value,
        )
        or re.search(r'(否认|澄清).{0,30}(破产|造假|退市|违约|停产|利空传闻)', text_value)
        or re.search(r"\b(don't|do not)\b.{0,30}\b(sell|downgrade)\b", text_value)
    )
    if clarification:
        neg_strength = 0.0
        neg_type = 'neutral'
        pos_strength = max(pos_strength, 0.25)
        pos_type = 'clarification'

    # A clarification is a confirmed response to a rumor, not another rumor.
    certainty = 1.0 if clarification else _event_certainty_multiplier(text_value)
    if certainty < 1.0:
        pos_strength *= certainty
        neg_strength *= certainty

    if alert_type == '重大利好':
        pos_strength = max(pos_strength, 1.0 if importance == '高' else 0.75)
        pos_type = 'major_alert'
    elif alert_type == '重大利空':
        neg_strength = max(neg_strength, 1.0 if importance == '高' else 0.75)
        neg_type = 'major_alert'

    if pos_strength == 0 and neg_strength == 0:
        try:
            sent = max(0.0, min(1.0, float(sentiment)))
            if sent > 0.55:
                pos_strength = min(0.25, (sent - 0.5) * 0.5)
                pos_type = 'sentiment_fallback'
            elif sent < 0.45:
                neg_strength = min(0.25, (0.5 - sent) * 0.5)
                neg_type = 'sentiment_fallback'
        except (TypeError, ValueError):
            pass

    return {
        'positive_strength': round(pos_strength, 4),
        'negative_strength': round(neg_strength, 4),
        'positive_event_type': pos_type,
        'negative_event_type': neg_type,
        'certainty_multiplier': certainty,
    }


def _headline_signal(rows: List[tuple]) -> Dict[str, Any]:
    pos = neg = announce = 0
    sentiments = []
    for title, sent in rows:
        title = title or ''
        pos += _count_keywords(title, POSITIVE_WORDS)
        neg += _count_keywords(title, NEGATIVE_WORDS)
        announce += _count_keywords(title, ANNOUNCE_WORDS)
        try:
            sentiments.append(float(sent))
        except Exception:
            pass
    avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0.5
    total = pos + neg
    keyword_sent = pos / total if total else avg_sent
    return {
        'pos': pos,
        'neg': neg,
        'announce_hits': announce,
        'avg_sent': avg_sent,
        'keyword_sent': keyword_sent,
    }


def _norm_title(t: str) -> str:
    """归一化标题用于跨源去重：去空白/标点/小写（保留中英文字符）。"""
    t = (t or '').lower()
    t = re.sub(r'[^a-z0-9一-鿿]+', '', t)
    return t


def _titles_similar(left: str, right: str) -> bool:
    """标题归一化后做保守的相似度匹配，避免改写标题重复计入。"""
    a, b = _norm_title(left), _norm_title(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < 18:
        return False
    if SequenceMatcher(None, a, b).ratio() >= 0.88:
        return True
    tokens_a = {token.rstrip('s') for token in re.findall(r'[a-z0-9]+', left.lower()) if len(token) > 2}
    tokens_b = {token.rstrip('s') for token in re.findall(r'[a-z0-9]+', right.lower()) if len(token) > 2}
    if tokens_a and tokens_b and len(tokens_a & tokens_b) / len(tokens_a | tokens_b) >= 0.60:
        return True
    grams_a = {a[i:i + 3] for i in range(len(a) - 2)}
    grams_b = {b[i:i + 3] for i in range(len(b) - 2)}
    return bool(grams_a and grams_b and len(grams_a & grams_b) / len(grams_a | grams_b) >= 0.72)


def _dedupe_rows(rows: List[tuple]) -> List[tuple]:
    """按归一化标题去重，保留首次出现（避免同一新闻被多源/多 feed 重复计入）。"""
    seen = set()
    out = []
    for r in rows:
        key = _norm_title(r[0] if r else '')
        if key:
            if key in seen:
                continue
            seen.add(key)
        out.append(r)
    return out


def _merge_event_records(records: List[Dict[str, Any]]) -> tuple:
    """Merge equivalent records before scoring; sources never become score weights."""
    events: List[Dict[str, Any]] = []
    duplicate_count = 0
    for record in records:
        title = str(record.get('title') or '').strip()
        if not _norm_title(title):
            continue
        strengths = _event_strength(
            title,
            record.get('sentiment', 0.5),
            record.get('alert_type', ''),
            record.get('importance', ''),
        )
        positive = max(
            strengths['positive_strength'],
            float(record.get('positive_strength', 0) or 0),
        )
        negative = max(
            strengths['negative_strength'],
            float(record.get('negative_strength', 0) or 0),
        )
        positive_type = strengths['positive_event_type']
        negative_type = strengths['negative_event_type']
        if float(record.get('positive_strength', 0) or 0) > strengths['positive_strength']:
            positive_type = str(record.get('positive_event_type') or 'structured_event')
        if float(record.get('negative_strength', 0) or 0) > strengths['negative_strength']:
            negative_type = str(record.get('negative_event_type') or 'structured_event')
        source = str(record.get('source') or 'unknown')
        event = next((item for item in events if _titles_similar(title, item['title'])), None)
        if event is None:
            events.append({
                'title': title,
                'positive_strength': min(1.0, positive),
                'negative_strength': min(1.0, negative),
                'positive_event_type': positive_type,
                'negative_event_type': negative_type,
                'sources': {source},
            })
            continue
        duplicate_count += 1
        if positive > event['positive_strength']:
            event['positive_strength'] = min(1.0, positive)
            event['positive_event_type'] = positive_type
        if negative > event['negative_strength']:
            event['negative_strength'] = min(1.0, negative)
            event['negative_event_type'] = negative_type
        event['sources'].add(source)
    return events, duplicate_count


def _combine_event_direction(events: List[Dict[str, Any]], strength_key: str,
                             type_key: str) -> tuple:
    """Combine every de-duplicated event; event count alone never creates strength."""
    ranked = []
    for event in events:
        strength = max(0.0, min(1.0, float(event.get(strength_key, 0) or 0)))
        event_type = str(event.get(type_key) or 'neutral')
        if strength <= 0 or event_type == 'neutral':
            continue
        ranked.append((event_type, strength))

    ranked.sort(key=lambda item: item[1], reverse=True)
    combined = sum(strength * (0.5 ** index) for index, (_, strength) in enumerate(ranked))
    return min(1.0, combined), ranked


def _score_event_records(records: List[Dict[str, Any]], cap: int,
                         dimension: str, prefix: str,
                         combine_all_events: bool = False) -> Dict[str, Any]:
    """Score one merged event pool once, independent of source availability/count."""
    events, duplicate_count = _merge_event_records(records)
    if not events:
        return _empty(cap, f'{dimension}无可用真实事件')

    strongest_positive = max(events, key=lambda item: item['positive_strength'])
    strongest_negative = max(events, key=lambda item: item['negative_strength'])
    if combine_all_events:
        positive_strength, positive_event_types = _combine_event_direction(
            events, 'positive_strength', 'positive_event_type'
        )
        negative_strength, negative_event_types = _combine_event_direction(
            events, 'negative_strength', 'negative_event_type'
        )
    else:
        positive_strength = strongest_positive['positive_strength']
        negative_strength = strongest_negative['negative_strength']
        positive_event_types = []
        negative_event_types = []
    neutral = cap / 2
    raw_score = neutral + (positive_strength - negative_strength) * neutral
    final_score = max(0, min(cap, _half_up(raw_score)))
    adjustment = final_score - neutral

    # 飞书只展示覆盖与去重情况；事件强度、标题和分数偏移仍保留在 raw，
    # 供评分、LLM 与排查使用，避免通知正文变成内部计算日志。
    evidence = f"{prefix} {len(events)} 项（去重{duplicate_count}项，数量不计分）"

    serializable_events = [
        {
            'title': event['title'],
            'positive_strength': event['positive_strength'],
            'negative_strength': event['negative_strength'],
            'positive_event_type': event['positive_event_type'],
            'negative_event_type': event['negative_event_type'],
            'sources': sorted(event['sources']),
        }
        for event in events
    ]
    return _dimension_result(
        raw_score,
        cap,
        evidence,
        {
            'source': 'merged_event_pool',
            'dimension': dimension,
            'event_count': len(events),
            'duplicates_removed': duplicate_count,
            'sources': sorted({source for event in events for source in event['sources']}),
            'strongest_positive': serializable_events[events.index(strongest_positive)],
            'strongest_negative': serializable_events[events.index(strongest_negative)],
            'positive_event_types': positive_event_types,
            'negative_event_types': negative_event_types,
            'events': serializable_events,
        },
    )


def _aggregate_deduped_news(candidates: List[Dict[str, Any]], cap: int) -> Dict[str, Any]:
    """Merge all available source articles, dedupe events, then score once."""
    records: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.get('available'):
            continue
        raw = candidate.get('raw', {}) or {}
        source = raw.get('source', 'unknown')
        for article in raw.get('articles', []) or []:
            records.append({
                'title': article.get('title', ''),
                'sentiment': article.get('sentiment', 0.5),
                'source': article.get('source') or source,
            })
    return _score_event_records(
        records, cap, '国际资讯', '合并去重资讯 24h', combine_all_events=True
    )


# --- 通用数据源备用函数 --------------------------------
def _news_futu(symbol: str, cap: int, news_type: int = 1, hours: int = 24,
               company_name: str = '') -> Dict[str, Any]:
    """使用富途新闻API作为备用数据源"""
    try:
        _rate_limit()
        r = requests.get(
            FUTU_NEWS_API,
            params={
                'keyword': symbol,
                'size': 20,
                'news_type': news_type,
                'lang': 'zh-CN',
                'sort_type': '2'
            },
            headers={'User-Agent': 'openclaw-stock-scorer/1.0'},
            timeout=8,
        )
        if r.status_code != 200:
            return _empty(cap, f'Futu News HTTP {r.status_code}')
        data = r.json() or {}
        if data.get('code') != 0:
            return _empty(cap, f'Futu News error')
        news_list = data.get('data', []) or []
        cutoff_ts = (datetime.now() - timedelta(hours=hours)).timestamp()
        recent = []
        for n in news_list:
            try:
                ts = int(n.get('publish_time', 0))
                if ts >= cutoff_ts:
                    recent.append(n)
            except Exception:
                continue
        if not recent:
            return _empty(cap, f'富途{hours}h无新闻')
        highlighted_aliases = _futu_query_aliases(recent, symbol, company_name)
        recent = [
            item for item in recent
            if _is_futu_query_relevant(
                item.get('title', ''), symbol, company_name, highlighted_aliases
            )
        ]
        if not recent:
            return _empty(cap, f'富途{hours}h无标的相关事件')
        positives = ['surge', 'rally', 'beat', 'upgrade', 'soar', 'jump', 'breakthrough',
                     'strong', 'record', 'profit', 'gain', 'outperform', 'bull', 'rise', 'higher', 'growth',
                     '涨', '涨超', '大涨', '暴涨', '利好', '突破', '获批', '回购', '加仓', '上调', '买入', '强劲', '增长', '盈利', '中标', '反弹']
        negatives = ['plunge', 'crash', 'miss', 'downgrade', 'lawsuit', 'investigation',
                     'warning', 'loss', 'cut', 'concern', 'risk', 'fall', 'bear', 'sue', 'drop', 'lower',
                     '跌', '跌超', '大跌', '暴跌', '利空', '破位', '调查', '诉讼', '召回', '下调', '卖出', '警告', '下滑', '违约', '退市', '制裁']
        pos = neg = announce_hits = 0
        for n in recent:
            t = _clean_title(n.get('title', '')).lower()
            pos += sum(1 for w in positives if w in t)
            neg += sum(1 for w in negatives if w in t)
            announce_hits += sum(1 for w in ANNOUNCE_WORDS if w in t)
        total = pos + neg
        sentiment = pos / total if total else 0.5
        score = int(round(min(1.0, len(recent) / 10) * 0.6 * cap + sentiment * 0.4 * cap))
        if len(recent) >= 50 and pos > neg:
            score += int(round(cap * 0.08))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f"富途{hours}h {len(recent)} 条，多:空={pos}:{neg}",
            'raw': {'source': 'futu', 'count': len(recent), 'pos': pos, 'neg': neg, 'announce_hits': announce_hits, 'sentiment': sentiment, 'query_aliases': highlighted_aliases, 'articles': [{'title': _clean_title(n.get('title', '')), 'sentiment': 0.5} for n in recent]},
        }
    except Exception as e:
        return _empty(cap, f'富途新闻失败: {e}')


def _news_alphavantage(symbol: str, cap: int) -> Dict[str, Any]:
    """AlphaVantage 新闻作为第三备用源"""
    if not ALPHAVANTAGE_KEY:
        return _empty(cap, 'AlphaVantage key 未配置')
    try:
        _rate_limit()
        r = requests.get(
            'https://www.alphavantage.co/query',
            params={
                'function': 'NEWS_SENTIMENT',
                'tickers': symbol,
                'limit': 50,
                'apikey': ALPHAVANTAGE_KEY
            },
            timeout=10,
        )
        if r.status_code != 200:
            return _empty(cap, f'AlphaVantage News HTTP {r.status_code}')
        data = r.json() or {}
        feeds = data.get('feed', []) or []
        cutoff = (datetime.now() - timedelta(hours=24)).timestamp()
        recent = [f for f in feeds if int(f.get('time_published', 0)[:12]) >= int(datetime.fromtimestamp(cutoff).strftime('%Y%m%dT%H%M'))]
        if not recent:
            return _empty(cap, 'AlphaVantage 24h 无新闻')
        pos = sum(1 for f in recent if float(f.get('overall_sentiment_score', 0)) > 0.55)
        neg = sum(1 for f in recent if float(f.get('overall_sentiment_score', 0)) < 0.45)
        total = len(recent)
        sentiment = pos / total if total else 0.5
        score = int(round(min(1.0, total / 15) * 0.6 * cap + sentiment * 0.4 * cap))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f'AlphaVantage 24h {total} 条，多:空={pos}:{neg}',
            'raw': {'source': 'alphavantage', 'count': total, 'pos': pos, 'neg': neg, 'articles': [{'title': f.get('title', ''), 'sentiment': max(0.0, min(1.0, float(f.get('overall_sentiment_score', 0.0) or 0.0) + 0.5))} for f in recent]},
        }
    except Exception as e:
        return _empty(cap, f'AlphaVantage 失败: {e}')


def _announce_futu(symbol: str, cap: int, company_name: str = '') -> Dict[str, Any]:
    """Collect Futu announcement evidence; source count never becomes points."""
    records: List[Dict[str, Any]] = []
    futu_news = _news_futu(
        symbol, cap, news_type=2, hours=168, company_name=company_name
    )
    if futu_news.get('available'):
        for article in (futu_news.get('raw', {}) or {}).get('articles', []) or []:
            title = article.get('title', '')
            if re.search(r'\bETF\b|基金|做多|做空', title, re.IGNORECASE):
                continue
            records.append({
                'title': title,
                'sentiment': article.get('sentiment', 0.5),
                'source': 'futu_announcement',
            })

    return _score_event_records(records, cap, '富途公告', '富途公告事件')


def _announce_alphavantage(symbol: str, cap: int) -> Dict[str, Any]:
    """AlphaVantage earnings/calendar作为官方公告第三备用源"""
    if not ALPHAVANTAGE_KEY:
        return _empty(cap, 'AlphaVantage key 未配置')
    try:
        _rate_limit()
        r = requests.get(
            'https://www.alphavantage.co/query',
            params={
                'function': 'EARNINGS',
                'symbol': symbol,
                'apikey': ALPHAVANTAGE_KEY
            },
            timeout=10,
        )
        if r.status_code != 200:
            return _empty(cap, f'AlphaVantage Earnings HTTP {r.status_code}')
        data = r.json() or {}
        earnings = data.get('earnings') or data.get('quarterlyEarnings', [])
        if not earnings:
            return _empty(cap, 'AlphaVantage 无财报数据')
        latest = earnings[0]
        reported_eps = float(latest.get('reportedEPS', 0))
        estimate_eps = float(latest.get('estimatedEPS', reported_eps))
        beat = reported_eps > estimate_eps
        score = int(round(cap * (0.75 if beat else 0.35)))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f'AlphaVantage 财报: reported {reported_eps:.2f}, estimate {estimate_eps:.2f}, {"beat" if beat else "in-line"}',
            'raw': {'source': 'alphavantage', 'reported_eps': reported_eps, 'estimate_eps': estimate_eps, 'beat': beat},
        }
    except Exception as e:
        return _empty(cap, f'AlphaVantage 财报失败: {e}')


def _institution_yfinance(symbol: str, cap: int) -> Dict[str, Any]:
    """使用yfinance分析师评级作为备用数据源"""
    try:
        import yfinance as yf
        _rate_limit()
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info:
            return _empty(cap, 'yfinance 无数据')
        rec = info.get('recommendationKey', '').lower()
        total = info.get('numberOfAnalysts', 0)
        if not total or not rec or int(total) == 0:
            return _empty(cap, 'yfinance 无分析师评级')
        total_int = int(total)
        bull_pct = {'strong_buy': 0.85, 'buy': 0.65, 'hold': 0.4, 'sell': 0.15, 'strong_sell': 0.05}.get(rec, 0.5)
        score = int(round(bull_pct * cap))
        evidence = f"分析师 {total_int} 家，评级 {rec} (yfinance)"
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': evidence,
            'raw': {'source': 'yfinance', 'rec': rec, 'total': total_int},
        }
    except Exception as e:
        return _empty(cap, f'yfinance 失败: {e}')


def _institution_tinkclaw(symbol: str, cap: int) -> Dict[str, Any]:
    """TinkClaw AI推荐作为机构观点第三备用源"""
    if not TINKCLAW_KEY:
        return _empty(cap, 'TinkClaw key 未配置')
    try:
        _rate_limit()
        r = requests.post(
            'https://tinkclaw.com/api/v1/signal',
            headers={'Authorization': f'Bearer {TINKCLAW_KEY}', 'Content-Type': 'application/json'},
            json={'symbol': symbol, 'asset_type': 'stock'},
            timeout=15,
        )
        if r.status_code != 200:
            return _empty(cap, f'TinkClaw HTTP {r.status_code}')
        data = r.json() or {}
        signal_dir = data.get('signal', {}).get('direction', 'HOLD')
        confidence = float(data.get('signal', {}).get('confidence', 50))
        confidence_norm = max(0.0, min(1.0, confidence / 100.0))
        if signal_dir == 'BUY':
            score = int(round(confidence_norm * cap))
        elif signal_dir == 'HOLD':
            score = int(round(cap * 0.5))
        else:
            score = int(round(cap * (1.0 - confidence_norm) * 0.3))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f'TinkClaw AI 信号: {signal_dir}, 置信度 {confidence:.0f}%',
            'raw': {'source': 'tinkclaw', 'direction': signal_dir, 'confidence': confidence},
        }
    except Exception as e:
        return _empty(cap, f'TinkClaw 失败: {e}')


def _community_longbridge(symbol: str, cap: int) -> Dict[str, Any]:
    """长桥资讯作为社区情绪备用源"""
    if not LONGBRIDGE_TOKEN:
        return _empty(cap, 'Longbridge key 未配置')
    try:
        _rate_limit()
        r = requests.get(
            'https://api.longbridgeapp.com/v1/news',
            headers={'Authorization': f'Bearer {LONGBRIDGE_TOKEN}'},
            params={'symbol': symbol, 'limit': 20},
            timeout=8,
        )
        if r.status_code != 200:
            return _empty(cap, f'Longbridge HTTP {r.status_code}')
        data = r.json() or {}
        items = (data.get('data') or {}).get('items', []) or []
        recent = [i for i in items if int(i.get('time', 0)) >= int((datetime.now() - timedelta(hours=24)).timestamp())]
        if not recent:
            return _empty(cap, 'Longbridge 24h 无资讯')
        total = len(recent)
        score = int(round(min(1.0, total / 15) * cap * 0.7))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f'Longbridge 24h {total} 条资讯',
            'raw': {'source': 'longbridge', 'count': total},
        }
    except Exception:
        return _empty(cap, 'Longbridge 资讯失败')


FUTU_FEED_API = 'https://ai-news-search.futunn.com/stock_feed'

_FUTU_COMMUNITY_POS = ['涨', '突破', '利好', '看好', '牛', 'bullish', 'surge', 'rally', 'beat', 'strong', '买', '加仓', '抄底', '反弹', '上涨']
_FUTU_COMMUNITY_NEG = ['跌', '破位', '利空', '看空', '熊', 'bearish', 'plunge', 'crash', 'miss', 'lawsuit', 'warning', '割', '减仓', '止损', '下跌', '暴跌']


def _community_futu_comment(symbol: str, cap: int) -> Dict[str, Any]:
    """富途社区讨论情绪（futu-comment-sentiment skill 的 HTTP 接口）。

    调 https://ai-news-search.futunn.com/stock_feed 拿 24h 社区帖，
    过滤低质内容后按 bullish/bearish/neutral 分类，映射到 0~cap 分。
    """
    try:
        _rate_limit()
        r = requests.get(
            FUTU_FEED_API,
            params={'keyword': symbol, 'size': 30},
            headers={'User-Agent': 'futu-comment-sentiment/0.0.2 (Skill)'},
            timeout=8,
        )
        if r.status_code != 200:
            return _empty(cap, f'富途社区 HTTP {r.status_code}')
        data = r.json() or {}
        if str(data.get('code', '')) != '0':
            return _empty(cap, f"富途社区 code={data.get('code')}")
        items = data.get('data') or []
        if not items:
            return _empty(cap, '富途社区无讨论')

        cutoff = (datetime.now() - timedelta(hours=24)).timestamp()
        recent = []
        for it in items:
            try:
                pt = it.get('publish_time')
                if pt is None:
                    continue
                ts = float(pt) / 1000 if float(pt) > 1e12 else float(pt)
                if ts >= cutoff:
                    recent.append(it)
            except (TypeError, ValueError):
                continue
        if not recent:
            return _empty(cap, '富途社区 24h 无讨论')

        # 低质过滤：去纯 emoji/口号/空帖
        filler = {'买', '卖', 'to the moon', 'moon', 'hodl', '👍', '🔥', '💎', '🚀'}
        kept = []
        for it in recent:
            text = ((it.get('title') or '') + ' ' + (it.get('desc') or '')).strip()
            if len(text) < 8:
                continue
            if text.lower() in filler:
                continue
            kept.append(text)
        if not kept:
            return _empty(cap, '富途社区过滤后无有效帖')

        bull = bear = neut = 0
        for text in kept:
            low = text.lower()
            p = sum(1 for w in _FUTU_COMMUNITY_POS if w.lower() in low)
            n = sum(1 for w in _FUTU_COMMUNITY_NEG if w.lower() in low)
            if p > n:
                bull += 1
            elif n > p:
                bear += 1
            else:
                neut += 1

        total = len(kept)
        bull_pct = bull / total
        bear_pct = bear / total
        neut_pct = neut / total

        # 映射：社区讨论偏“弱信号”。中性高讨论不应被当成 0 分，
        # 只有明显看空才压低，明显看多才加分。
        buzz = min(1.0, total / 20)
        sentiment_score = bull_pct - bear_pct  # -1 ~ 1
        score = int(round((0.45 + buzz * 0.15 + sentiment_score * 0.30) * cap))
        score = max(0, min(cap, score))

        return {
            'score': score,
            'available': True,
            'evidence': f"富途社区 24h {total} 帖，多{bull_pct:.0%}/空{bear_pct:.0%}/中性{neut_pct:.0%}",
            'raw': {
                'source': 'futu_comment',
                'count': total,
                'bull': bull,
                'bear': bear,
                'neutral': neut,
                'bull_pct': round(bull_pct, 3),
                'bear_pct': round(bear_pct, 3),
            },
        }
    except Exception as e:
        return _empty(cap, f'富途社区失败: {e}')


# --- 维度 1：国际资讯（25 分）---
def score_international_news(symbol: str, market: str = 'us', cap: int = 30,
                             company_name: str = '') -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    # 全量多源：所有已配置源均请求，标题去重后计算综合分。
    candidates = []
    futu_aliases: List[str] = []
    try:
        r = _news_futu(clean, cap, news_type=1, company_name=company_name)
        if r.get('available'):
            candidates.append(r)
            futu_aliases = (r.get('raw', {}) or {}).get('query_aliases', []) or []
    except Exception:
        pass
    if FINNHUB_KEY:
        try:
            r = _news_finnhub(clean, cap, company_name, futu_aliases)
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    if ALPHAVANTAGE_KEY:
        try:
            r = _news_alphavantage(clean, cap)
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _news_db(clean, cap, ['Yahoo Finance', 'Finnhub', 'Google News Tech', 'Futunn', 'AlphaVantage'])
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    return _aggregate_deduped_news(candidates, cap)


def _news_finnhub(symbol: str, cap: int, company_name: str = '',
                  extra_aliases: Optional[List[str]] = None) -> Dict[str, Any]:
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    try:
        r = requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={'symbol': symbol, 'from': yesterday.isoformat(),
                    'to': today.isoformat(), 'token': FINNHUB_KEY},
            timeout=8,
        )
        if r.status_code != 200:
            return _empty(cap, f'Finnhub HTTP {r.status_code}')
        news_list = r.json() or []
        cutoff = (datetime.now() - timedelta(hours=24)).timestamp()
        recent = [n for n in news_list if n.get('datetime', 0) >= cutoff]
        recent = [
            n for n in recent
            if _is_company_relevant(
                f"{n.get('headline', '')} {n.get('summary', '')}",
                symbol,
                company_name,
                extra_aliases,
            )
        ]
        if not recent:
            return _empty(cap, '24h 无公司新闻')
        positives = ['surge', 'rally', 'beat', 'upgrade', 'soar', 'jump', 'breakthrough',
                     'strong', 'record', 'profit', 'gain', 'outperform', 'bull']
        negatives = ['plunge', 'crash', 'miss', 'downgrade', 'lawsuit', 'investigation',
                     'warning', 'loss', 'cut', 'concern', 'risk', 'fall', 'bear', 'sue']
        pos = neg = 0
        for n in recent:
            t = (n.get('headline', '') or '').lower()
            pos += sum(1 for w in positives if w in t)
            neg += sum(1 for w in negatives if w in t)
        total = pos + neg
        sentiment = pos / total if total else 0.5
        score = int(round(min(1.0, len(recent) / 10) * 0.6 * cap + sentiment * 0.4 * cap))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f"Finnhub 24h {len(recent)} 条，多:空={pos}:{neg}",
            'raw': {'source': 'finnhub', 'count': len(recent), 'pos': pos, 'neg': neg, 'sentiment': sentiment, 'articles': [{'title': _clean_title(n.get('headline', '')), 'sentiment': 0.5} for n in recent]},
        }
    except Exception as e:
        return _empty(cap, f'Finnhub 失败: {e}')


def _news_db(symbol: str, cap: int, sources: List[str]) -> Dict[str, Any]:
    try:
        clean = _clean_symbol(symbol)
        conn = sqlite3.connect(NEWS_DB_PATH)
        ph = ','.join('?' * len(sources))
        exact_symbols = (clean, f'US.{clean}', f'HK.{clean}')
        if len(clean) >= 3:
            raw_rows = conn.execute(
                f'''SELECT title, sentiment, symbol
                    FROM news
                    WHERE (UPPER(symbol) IN (?, ?, ?) OR UPPER(title) LIKE ?)
                    AND source IN ({ph})
                    AND timestamp > datetime("now", "-24 hours")''',
                (*exact_symbols, f'%{clean}%', *sources)
            ).fetchall()
        else:
            raw_rows = conn.execute(
                f'''SELECT title, sentiment, symbol
                    FROM news
                    WHERE UPPER(symbol) IN (?, ?, ?)
                    AND source IN ({ph})
                    AND timestamp > datetime("now", "-24 hours")''',
                (*exact_symbols, *sources)
            ).fetchall()
        conn.close()

        # Never substring-match short tickers such as F/AI/ON/IT.
        # Longer tickers must appear as a standalone token in the title.
        title_pattern = re.compile(
            rf'(?<![A-Z0-9]){re.escape(clean)}(?![A-Z0-9])', re.IGNORECASE
        ) if len(clean) >= 3 else None
        rows = []
        for title, sentiment, row_symbol in raw_rows:
            exact_match = _clean_symbol(row_symbol or '') == clean
            title_match = bool(title_pattern and title_pattern.search(title or ''))
            if exact_match or title_match:
                rows.append((title, sentiment))
        if not rows:
            return _empty(cap, 'news.db 24h 无数据')
        rows = _dedupe_rows(rows)
        count = len(rows)
        sig = _headline_signal(rows)
        count_factor = min(1.0, count / 8)
        score = int(round(
            count_factor * 0.35 * cap +
            sig['keyword_sent'] * 0.45 * cap +
            sig['avg_sent'] * 0.20 * cap
        ))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f"news.db 24h {count} 条，情绪 {sig['avg_sent']:.2f}，多:空={sig['pos']}:{sig['neg']}",
            'raw': {'source': 'news_db', 'count': count, **sig, 'articles': [{'title': title, 'sentiment': sentiment} for title, sentiment in rows]},
        }
    except Exception as e:
        return _empty(cap, f'news.db 失败: {e}')


def _append_nested_event_records(value: Any, default_source: str,
                                 records: List[Dict[str, Any]]) -> None:
    if isinstance(value, dict):
        source = str(value.get('source') or default_source)
        for key in ('articles', 'events'):
            for item in value.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                record = dict(item)
                event_sources = record.get('sources') or []
                record['source'] = (
                    record.get('source')
                    or ','.join(str(item) for item in event_sources if item)
                    or source
                )
                records.append(record)
        for key, nested in value.items():
            if key not in ('articles', 'events'):
                _append_nested_event_records(nested, source, records)
    elif isinstance(value, list):
        for item in value:
            _append_nested_event_records(item, default_source, records)


def _aggregate_official_evidence(candidates: List[Dict[str, Any]], cap: int) -> Dict[str, Any]:
    """Merge real announcements/structured filings, dedupe, then score once."""
    records: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.get('available'):
            continue
        raw = candidate.get('raw', {}) or {}
        source = str(raw.get('source') or 'unknown')
        _append_nested_event_records(raw, source, records)

        if source == 'alphavantage':
            try:
                reported = float(raw.get('reported_eps'))
                estimate = float(raw.get('estimate_eps'))
                surprise = (reported - estimate) / max(abs(estimate), 0.01)
                record = {
                    'title': f'EPS reported {reported:.4f} vs estimate {estimate:.4f}',
                    'sentiment': 0.5,
                    'source': source,
                }
                if abs(surprise) >= 0.01:
                    strength = _ratio_event_strength(surprise)
                    key = 'positive_strength' if surprise > 0 else 'negative_strength'
                    record[key] = strength
                    record[
                        'positive_event_type' if surprise > 0 else 'negative_event_type'
                    ] = 'earnings_surprise'
                records.append(record)
            except (TypeError, ValueError):
                pass

        if source == 'finnhub_announcement':
            earnings = raw.get('earnings') or {}
            if earnings.get('date'):
                records.append({
                    'title': f"财报日程 {earnings['date']}",
                    'sentiment': 0.5,
                    'source': source,
                })
            insider = raw.get('insider') or {}
            try:
                net_change = float(insider.get('net_change'))
                if net_change:
                    records.append({
                        'title': f"30d insider net {'buy' if net_change > 0 else 'sell'}",
                        'sentiment': 0.5,
                        'source': source,
                        'positive_strength': 0.45 if net_change > 0 else 0,
                        'negative_strength': 0.45 if net_change < 0 else 0,
                        'positive_event_type': 'insider_transaction',
                        'negative_event_type': 'insider_transaction',
                    })
            except (TypeError, ValueError):
                pass

    return _score_event_records(
        records, cap, '官方公告', '合并去重公告', combine_all_events=True
    )
# --- 维度 2：官方公告（20 分）---
def score_official_announce(symbol: str, market: str = 'us', cap: int = 20,
                            company_name: str = '') -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    # Every source contributes raw evidence only. Missing sources never enter a score denominator.
    candidates = []
    if FINNHUB_KEY:
        try:
            r = _cached_source(
                f'announce:{ANNOUNCE_CACHE_SCHEMA}:finnhub:{market}:{clean}:{cap}',
                4 * 3600,
                lambda: _announce_finnhub(clean, cap),
            )
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _announce_futu(clean, cap, company_name)
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    if ALPHAVANTAGE_KEY:
        try:
            r = _cached_source(
                f'announce:{ANNOUNCE_CACHE_SCHEMA}:alphavantage:{market}:{clean}:{cap}',
                4 * 3600,
                lambda: _announce_alphavantage(clean, cap),
            )
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _news_db(clean, cap, ['SEC EDGAR', '港交所', 'Tushare-公告', 'Futunn-公告', 'AlphaVantage-财报'])
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    return _aggregate_official_evidence(candidates, cap)


def _announce_finnhub(symbol: str, cap: int) -> Dict[str, Any]:
    score = 0
    parts: List[str] = []
    raw: Dict[str, Any] = {'source': 'finnhub_announcement'}
    try:
        today = datetime.now().date()
        end = today + timedelta(days=14)
        r = requests.get(
            'https://finnhub.io/api/v1/calendar/earnings',
            params={'from': today.isoformat(), 'to': end.isoformat(),
                    'symbol': symbol, 'token': FINNHUB_KEY},
            timeout=8,
        )
        if r.status_code == 200:
            cal = (r.json() or {}).get('earningsCalendar', []) or []
            if cal:
                ev = cal[0]
                try:
                    days_until = (datetime.fromisoformat(ev['date']).date() - today).days
                    proximity = max(0, (14 - days_until) / 14)
                    score += int(round(proximity * cap * 0.5))
                    parts.append(f"{days_until}天后财报")
                    raw['earnings'] = {'date': ev['date'], 'days_until': days_until}
                except Exception:
                    pass
    except Exception as e:
        raw['earnings_err'] = str(e)
    try:
        r = requests.get(
            'https://finnhub.io/api/v1/stock/insider-transactions',
            params={'symbol': symbol, 'token': FINNHUB_KEY},
            timeout=8,
        )
        if r.status_code == 200:
            txs = (r.json() or {}).get('data', []) or []
            cutoff = (datetime.now() - timedelta(days=30)).date().isoformat()
            recent = [t for t in txs if (t.get('transactionDate') or '') >= cutoff]
            net = sum(int(t.get('change', 0) or 0) for t in recent)
            if recent:
                if net > 0:
                    score += int(round(cap * 0.5))
                    parts.append(f"30d内部净买入{net:,}股")
                elif net < 0:
                    parts.append(f"30d内部净卖出{-net:,}股")
                else:
                    score += int(round(cap * 0.25))
                    parts.append("30d内部交易持平")
                raw['insider'] = {'net_change': net, 'tx_count': len(recent)}
    except Exception as e:
        raw['insider_err'] = str(e)
    if not parts:
        return _empty(cap, '无财报/内部人数据')
    return {
        'score': max(0, min(cap, score)),
        'available': True,
        'evidence': ' / '.join(parts),
        'raw': raw,
    }


def _aggregate_community_evidence(candidates: List[Dict[str, Any]], cap: int) -> Dict[str, Any]:
    """Merge platform discussions once; volume is heat, never a source weight."""
    bull = 0.0
    bear = 0.0
    neutral_count = 0.0
    sources = []

    for candidate in candidates:
        if not candidate.get('available'):
            continue
        raw = candidate.get('raw', {}) or {}
        source = str(raw.get('source') or 'unknown')
        sources.append(source)

        if source == 'futu_comment':
            bull += float(raw.get('bull', 0) or 0)
            bear += float(raw.get('bear', 0) or 0)
            neutral_count += float(raw.get('neutral', 0) or 0)
            continue

        articles = raw.get('articles', []) or []
        if articles:
            for article in articles:
                strengths = _event_strength(
                    article.get('title', ''),
                    article.get('sentiment', 0.5),
                )
                if strengths['positive_strength'] > strengths['negative_strength']:
                    bull += 1
                elif strengths['negative_strength'] > strengths['positive_strength']:
                    bear += 1
                else:
                    neutral_count += 1
            continue

        count = float(raw.get('count', 0) or 0)
        pos = float(raw.get('pos', 0) or 0)
        neg = float(raw.get('neg', 0) or 0)
        directional = pos + neg
        if count > 0 and directional > 0:
            bull += count * pos / directional
            bear += count * neg / directional
        else:
            neutral_count += count

    total = bull + bear + neutral_count
    if total <= 0:
        return _empty(cap, '社区情绪无可用真实讨论')

    heat = min(1.0, total / 20)
    direction = (bull - bear) / total
    raw_score = (0.40 + 0.20 * heat + 0.40 * direction) * cap
    evidence = (
        f"合并社区讨论 {total:.0f} 条（{len(set(sources))}源，不按源平均），"
        f"多{bull / total:.0%}/空{bear / total:.0%}/中性{neutral_count / total:.0%}"
    )
    return _dimension_result(
        raw_score,
        cap,
        evidence,
        {
            'source': 'merged_community_pool',
            'sources': sorted(set(sources)),
            'count': round(total, 2),
            'bull': round(bull, 2),
            'bear': round(bear, 2),
            'neutral': round(neutral_count, 2),
            'heat': round(heat, 4),
            'direction': round(direction, 4),
        },
    )
# --- 维度 3：社区情绪（25 分）---
def score_community(symbol: str, market: str = 'us', cap: int = 25) -> Dict[str, Any]:
    clean = _clean_symbol(symbol)
    sources = ['新浪财经', '东方财富', '观察者网', '36氪', '金十数据', 'IT之家']

    # Keep independent platform activity, but merge records before one unified score.
    candidates = [
        _news_db(clean, cap, sources),
        _community_futu_comment(clean, cap),
        _community_longbridge(clean, cap),
    ]
    if (market or 'us').lower() == 'us':
        candidates.append(_us_public_attention(clean, cap))
    return _aggregate_community_evidence(candidates, cap)


def _us_public_attention(symbol: str, cap: int) -> Dict[str, Any]:
    sources = ['Yahoo Finance', 'Google News Tech', 'Finnhub']
    try:
        conn = sqlite3.connect(NEWS_DB_PATH)
        ph = ','.join('?' * len(sources))
        rows = conn.execute(
            f'''SELECT title, sentiment
                FROM news
                WHERE (symbol = ? OR title LIKE ?)
                AND source IN ({ph})
                AND timestamp > datetime("now", "-24 hours")''',
            (symbol, f'%{symbol}%', *sources)
        ).fetchall()
        conn.close()
        if not rows:
            return _empty(cap, '美股公开讨论无数据')
        rows = _dedupe_rows(rows)
        sig = _headline_signal(rows)
        buzz = min(1.0, len(rows) / 20)
        score = int(round(
            buzz * 0.45 * cap +
            sig['keyword_sent'] * 0.35 * cap +
            sig['avg_sent'] * 0.20 * cap
        ))
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': f"美股公开讨论 24h {len(rows)} 条，情绪 {sig['avg_sent']:.2f}，多:空={sig['pos']}:{sig['neg']}",
            'raw': {
                'source': 'us_public_attention',
                'count': len(rows),
                **sig,
                'articles': [{'title': title, 'sentiment': sentiment} for title, sentiment in rows],
            },
        }
    except Exception as e:
        return _empty(cap, f'公开讨论失败: {e}')


_FUTU_RESEARCH_RATING_POS = ['买入', '增持', '跑赢', '优于大盘', '强烈推荐', '上调', '维持买入', '加仓', '推荐', 'outperform', 'overweight', 'buy', 'strong buy', 'upgrade']
_FUTU_RESEARCH_RATING_NEG = ['卖出', '减持', '跑输', '劣于大盘', '下调', '维持卖出', '减仓', '回避', 'underperform', 'underweight', 'sell', 'downgrade']


def _institution_futu_research(symbol: str, cap: int, hours: int = 168) -> Dict[str, Any]:
    """富途研报作为机构观点源（news_type=3）。168h 窗口，按评级关键词打分。"""
    try:
        _rate_limit()
        r = requests.get(
            FUTU_NEWS_API,
            params={'keyword': symbol, 'size': 30, 'news_type': 3, 'lang': 'zh-CN', 'sort_type': '2'},
            headers={'User-Agent': 'openclaw-stock-scorer/1.0'},
            timeout=8,
        )
        if r.status_code != 200:
            return _empty(cap, f'富途研报 HTTP {r.status_code}')
        data = r.json() or {}
        if data.get('code') != 0:
            return _empty(cap, '富途研报 error')
        news_list = data.get('data', []) or []
        cutoff_ts = (datetime.now() - timedelta(hours=hours)).timestamp()
        recent = []
        for n in news_list:
            try:
                ts = int(n.get('publish_time', 0))
                if ts >= cutoff_ts:
                    recent.append(n)
            except Exception:
                continue
        if not recent:
            return _empty(cap, f'富途研报{hours}h无数据')
        pos = neg = 0
        for n in recent:
            t = (n.get('title', '') or '').lower()
            pos += sum(1 for w in _FUTU_RESEARCH_RATING_POS if w.lower() in t)
            neg += sum(1 for w in _FUTU_RESEARCH_RATING_NEG if w.lower() in t)
        total = pos + neg
        if total == 0:
            score = int(round(cap * 0.4))
            direction = '中性'
        else:
            pos_ratio = pos / total
            if pos_ratio >= 0.6:
                score = int(round(cap * 0.8))
                direction = '看多'
            elif pos_ratio <= 0.4:
                score = int(round(cap * 0.2))
                direction = '看空'
            else:
                score = int(round(cap * 0.5))
                direction = '分歧'
        evidence = f"富途研报{hours}h {len(recent)} 篇，多{pos}/空{neg}，{direction}"
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': evidence,
            'raw': {
                'source': 'futu_research',
                'count': len(recent),
                'pos': pos,
                'neg': neg,
                'direction': direction,
                'articles': [{'title': n.get('title', ''), 'sentiment': 0.5} for n in recent],
            },
        }
    except Exception as e:
        return _empty(cap, f'富途研报失败: {e}')


def _aggregate_institution_evidence(candidates: List[Dict[str, Any]], cap: int) -> Dict[str, Any]:
    """Merge analyst votes/research records once; duplicate APIs are not extra votes."""
    sources = []
    finnhub_consensus = None
    yfinance_consensus = None
    research_records: List[Dict[str, Any]] = []
    tinkclaw_signals = []

    for candidate in candidates:
        if not candidate.get('available'):
            continue
        raw = candidate.get('raw', {}) or {}
        source = str(raw.get('source') or 'unknown')
        sources.append(source)
        if source == 'finnhub_recommendation':
            finnhub_consensus = raw
            continue
        if source == 'yfinance':
            yfinance_consensus = raw
            continue
        if source == 'tinkclaw':
            tinkclaw_signals.append(raw)
            continue
        for article in raw.get('articles', []) or []:
            title = article.get('title', '')
            text_value = title.lower()
            pos_hits = sum(1 for word in _FUTU_RESEARCH_RATING_POS if word.lower() in text_value)
            neg_hits = sum(1 for word in _FUTU_RESEARCH_RATING_NEG if word.lower() in text_value)
            record = {
                'title': title,
                'sentiment': article.get('sentiment', 0.5),
                'source': source,
            }
            if pos_hits > neg_hits:
                record['positive_strength'] = min(1.0, 0.60 + 0.10 * (pos_hits - 1))
            elif neg_hits > pos_hits:
                record['negative_strength'] = min(1.0, 0.60 + 0.10 * (neg_hits - 1))
            research_records.append(record)

    bull = 0.0
    bear = 0.0
    neutral_count = 0.0
    consensus_source = ''
    if finnhub_consensus:
        bull += float(finnhub_consensus.get('strong_buy', 0) or 0)
        bull += float(finnhub_consensus.get('buy', 0) or 0)
        bear += float(finnhub_consensus.get('sell', 0) or 0)
        bear += float(finnhub_consensus.get('strong_sell', 0) or 0)
        neutral_count += float(finnhub_consensus.get('hold', 0) or 0)
        consensus_source = 'finnhub'
    elif yfinance_consensus:
        total = float(yfinance_consensus.get('total', 0) or 0)
        rec = str(yfinance_consensus.get('rec') or '').lower()
        weights = {
            'strong_buy': (0.90, 0.00, 0.10),
            'buy': (0.75, 0.00, 0.25),
            'hold': (0.10, 0.10, 0.80),
            'sell': (0.00, 0.75, 0.25),
            'strong_sell': (0.00, 0.90, 0.10),
        }.get(rec, (0.0, 0.0, 1.0))
        bull += total * weights[0]
        bear += total * weights[1]
        neutral_count += total * weights[2]
        consensus_source = 'yfinance'

    research_events, duplicate_count = _merge_event_records(research_records)
    for event in research_events:
        positive = event['positive_strength']
        negative = event['negative_strength']
        bull += positive
        bear += negative
        neutral_count += max(0.0, 1.0 - positive - negative)

    for signal in tinkclaw_signals:
        confidence = max(0.0, min(1.0, float(signal.get('confidence', 50) or 50) / 100))
        direction = str(signal.get('direction') or 'HOLD').upper()
        if direction == 'BUY':
            bull += confidence
            neutral_count += 1 - confidence
        elif direction == 'SELL':
            bear += confidence
            neutral_count += 1 - confidence
        else:
            neutral_count += 1

    total = bull + bear + neutral_count
    if total <= 0:
        return _empty(cap, '机构观点无可用真实意见')

    direction = (bull - bear) / total
    raw_score = (0.5 + 0.5 * direction) * cap
    evidence = (
        f"合并机构观点 {total:.0f} 份（{len(set(sources))}源、去重{duplicate_count}项，"
        f"不按源平均），多{bull / total:.0%}/空{bear / total:.0%}"
    )
    return _dimension_result(
        raw_score,
        cap,
        evidence,
        {
            'source': 'merged_institution_pool',
            'sources': sorted(set(sources)),
            'consensus_source': consensus_source,
            'yfinance_consensus_ignored_as_duplicate': bool(
                finnhub_consensus and yfinance_consensus
            ),
            'duplicates_removed': duplicate_count,
            'bull_weight': round(bull, 4),
            'bear_weight': round(bear, 4),
            'neutral_weight': round(neutral_count, 4),
            'direction': round(direction, 4),
            'research_events': [
                {
                    'title': event['title'],
                    'positive_strength': event['positive_strength'],
                    'negative_strength': event['negative_strength'],
                    'sources': sorted(event['sources']),
                }
                for event in research_events
            ],
        },
    )
# --- 维度 4：机构观点（20 分）---
def score_institution(symbol: str, market: str = 'us', cap: int = 25) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    # Fetch every configured source, then merge raw opinions before one score.
    candidates = []
    if FINNHUB_KEY:
        try:
            r = _cached_source(f'institution:v2:finnhub:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_finnhub(clean, cap))
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _cached_source(f'institution:v2:yfinance:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_yfinance(clean, cap))
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    try:
        r = _cached_source(f'institution:v2:futu:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_futu_research(clean, cap))
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    if TINKCLAW_KEY:
        try:
            r = _cached_source(f'institution:v2:tinkclaw:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_tinkclaw(clean, cap))
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _news_db(clean, cap, ['Reuters Tech', 'CNBC', 'Wired', 'Ars Technica', 'Futunn研报', 'TinkClaw'])
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    return _aggregate_institution_evidence(candidates, cap)


def _institution_finnhub(symbol: str, cap: int) -> Dict[str, Any]:
    try:
        r = requests.get(
            'https://finnhub.io/api/v1/stock/recommendation',
            params={'symbol': symbol, 'token': FINNHUB_KEY},
            timeout=8,
        )
        if r.status_code != 200:
            return _empty(cap, f'Finnhub HTTP {r.status_code}')
        recs = r.json() or []
        if not recs:
            return _empty(cap, '无分析师评级')
        latest = recs[0]
        strong_buy = int(latest.get('strongBuy', 0) or 0)
        buy = int(latest.get('buy', 0) or 0)
        hold = int(latest.get('hold', 0) or 0)
        sell = int(latest.get('sell', 0) or 0)
        strong_sell = int(latest.get('strongSell', 0) or 0)
        total = strong_buy + buy + hold + sell + strong_sell
        if total == 0:
            return _empty(cap, '分析师评级为空')
        bull = (strong_buy + buy) / total
        bear = (sell + strong_sell) / total
        net = bull - bear
        trend_bonus = 0
        if len(recs) >= 2:
            prev = recs[1]
            prev_bull = (int(prev.get('strongBuy', 0)) + int(prev.get('buy', 0))) / max(
                1, sum(int(prev.get(k, 0) or 0) for k in ['strongBuy','buy','hold','sell','strongSell'])
            )
            if bull > prev_bull + 0.05:
                trend_bonus = 0.1
            elif bull < prev_bull - 0.05:
                trend_bonus = -0.1
        base = max(0.0, (net + 1) / 2)
        score = int(round(min(1.0, base + trend_bonus) * cap))
        evidence = f"分析师 {total} 家：强买{strong_buy} 买{buy} 中{hold} 卖{sell+strong_sell}"
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': evidence,
            'raw': {
                'source': 'finnhub_recommendation', 'strong_buy': strong_buy, 'buy': buy, 'hold': hold,
                'sell': sell, 'strong_sell': strong_sell,
                'bull_ratio': bull, 'bear_ratio': bear, 'trend_bonus': trend_bonus,
            },
        }
    except Exception as e:
        return _empty(cap, f'Finnhub 失败: {e}')


import subprocess

FUTU_CAPITAL_SCRIPT = str(SKILLS_DIR / 'futu-capital-anomaly/scripts/handle_capital_anomaly.py')
FUTU_PYTHON = str(PYTHON_BIN)

_CAPITAL_POS_KEYWORDS = ['净流入', '加速进场', '主力资金持续净流入', '买入', '加仓', '看多']
_CAPITAL_NEG_KEYWORDS = ['净流出', '加速离场', '主力资金持续净流出', '卖出', '减仓', '看空', '卖空异动', '卖空数量上升']


_CAPITAL_METRICS_CACHE: Dict[str, Dict[str, Any]] = {}
_CAPITAL_METRICS_CACHE_TTL = 15 * 60
_CAPITAL_METRICS_LOCK = threading.Lock()


def _score_capital_metrics(super_flow_ratio: float, main_streak_days: int,
                           short_delta_pp: float, cap: int = 10) -> Dict[str, float]:
    """Return symmetric flow/streak/short adjustments around a neutral midpoint."""
    scale = cap / 10
    signed_ratio = max(-1.0, min(1.0, float(super_flow_ratio)))
    flow_adjustment = signed_ratio * 3.0 * scale
    streak_adjustment = 0.0
    if main_streak_days:
        streak_adjustment = (
            1 if main_streak_days > 0 else -1
        ) * min(3.0 * scale, abs(main_streak_days) * 0.5 * scale)

    short_adjustment = 0.0
    if abs(short_delta_pp) >= 0.20:
        short_adjustment = min(2.0 * scale, abs(short_delta_pp) / 0.50 * 2.0 * scale)
        if short_delta_pp > 0:
            short_adjustment *= -1

    raw_score = cap / 2 + flow_adjustment + streak_adjustment + short_adjustment
    return {
        'score': max(0, min(cap, _half_up(raw_score))),
        'flow_adjustment': round(flow_adjustment, 4),
        'streak_adjustment': round(streak_adjustment, 4),
        'short_adjustment': round(short_adjustment, 4),
    }
def score_capital_anomaly(symbol: str, market: str = 'us', cap: int = 10) -> Dict[str, Any]:
    """Use real Futu flow and short-interest metrics for a continuous 0-cap score."""
    clean = _clean_symbol(symbol)
    market = (market or 'us').lower()
    code = f"{'HK.' if market == 'hk' else 'US.'}{clean}"
    cache_key = f"{code}:{cap}"
    now = time.time()
    with _CAPITAL_METRICS_LOCK:
        cached = _CAPITAL_METRICS_CACHE.get(cache_key)
        if cached and now - cached.get('timestamp', 0) < _CAPITAL_METRICS_CACHE_TTL:
            return cached['result']

    try:
        from futu import OpenQuoteContext, RET_OK, PeriodType
        quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
        try:
            start_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            flow_ret, flow_data = quote_ctx.get_capital_flow(
                code, period_type=PeriodType.DAY, start=start_date, end=end_date
            )
            short_ret, us_short, hk_short = quote_ctx.get_short_interest(code, num=10)
        finally:
            quote_ctx.close()

        flow_rows = flow_data.to_dict('records') if flow_ret == RET_OK and hasattr(flow_data, 'to_dict') else []
        if not flow_rows:
            return _empty(cap, '富途每日资金流无数据')

        flow_rows.sort(key=lambda row: str(row.get('capital_flow_item_time', '')))
        total_abs_flow = sum(abs(float(row.get('in_flow', 0) or 0)) for row in flow_rows)
        super_net_flow = sum(float(row.get('super_in_flow', 0) or 0) for row in flow_rows)
        super_flow_ratio = (
            max(-1.0, min(1.0, super_net_flow / total_abs_flow))
            if total_abs_flow > 0 else 0.0
        )

        main_streak_days = 0
        streak_sign = 0
        for row in reversed(flow_rows):
            main_flow = float(row.get('main_in_flow', 0) or 0)
            current_sign = 1 if main_flow > 0 else -1 if main_flow < 0 else 0
            if current_sign == 0:
                break
            if streak_sign == 0:
                streak_sign = current_sign
            elif current_sign != streak_sign:
                break
            main_streak_days += current_sign

        short_rows = []
        if short_ret == RET_OK:
            short_df = hk_short if market == 'hk' else us_short
            if hasattr(short_df, 'to_dict'):
                short_rows = short_df.to_dict('records')
        short_rows.sort(key=lambda row: float(row.get('timestamp', 0) or 0), reverse=True)

        short_latest = short_previous = None
        if len(short_rows) >= 2:
            field = 'aggregated_short_ratio' if market == 'hk' else 'short_percent'
            try:
                short_latest = float(short_rows[0].get(field))
                short_previous = float(short_rows[1].get(field))
            except (TypeError, ValueError):
                short_latest = short_previous = None

        short_delta_pp = (short_latest - short_previous) if short_latest is not None and short_previous is not None else 0.0
        metrics = _score_capital_metrics(
            super_flow_ratio,
            main_streak_days,
            short_delta_pp,
            cap,
        )

        flow_direction = '净流入' if super_net_flow > 0 else '净流出' if super_net_flow < 0 else '持平'
        streak_direction = '净流入' if main_streak_days > 0 else '净流出' if main_streak_days < 0 else '持平'
        short_text = '卖空数据不足'
        if short_latest is not None:
            short_text = f"卖空{short_latest:.2f}% ({short_delta_pp:+.2f}pp)"
        evidence = (
            f"富途连续资金: 特大单{flow_direction}{super_net_flow:,.0f}"
            f"(占比{super_flow_ratio:+.1%})，主力连续{streak_direction}"
            f"{abs(main_streak_days)}日，{short_text}"
        )
        component_adjustments = (
            metrics['flow_adjustment'],
            metrics['streak_adjustment'],
            metrics['short_adjustment'],
        )
        result = _dimension_result(
            metrics['score'],
            cap,
            evidence,
            {
                'source': 'futu_capital_flow_short_interest',
                'days': len(flow_rows),
                'direction': flow_direction,
                'content': evidence,
                'pos_hits': sum(1 for value in component_adjustments if value > 0),
                'neg_hits': sum(1 for value in component_adjustments if value < 0),
                'super_net_flow': super_net_flow,
                'total_abs_flow': total_abs_flow,
                'super_flow_ratio': round(super_flow_ratio, 6),
                'super_inflow_ratio': round(max(0.0, super_flow_ratio), 6),
                'main_streak_days': main_streak_days,
                'consecutive_main_inflow_days': max(0, main_streak_days),
                'consecutive_main_outflow_days': max(0, -main_streak_days),
                'short_latest_pct': short_latest,
                'short_previous_pct': short_previous,
                'short_delta_pp': round(short_delta_pp, 4),
                'flow_adjustment': metrics['flow_adjustment'],
                'streak_adjustment': metrics['streak_adjustment'],
                'short_adjustment': metrics['short_adjustment'],
            },
        )
        with _CAPITAL_METRICS_LOCK:
            _CAPITAL_METRICS_CACHE[cache_key] = {'timestamp': now, 'result': result}
        return result
    except Exception as e:
        return _empty(cap, f'富途连续资金数据失败: {e}')


# --- 聚合 ---
def score_all(symbol: str, market: str = 'us', company_name: str = '') -> Dict[str, Any]:
    news = score_international_news(symbol, market, cap=25, company_name=company_name)
    ann = score_official_announce(symbol, market, cap=20, company_name=company_name)
    com = score_community(symbol, market, cap=25)
    inst = score_institution(symbol, market, cap=20)
    cap_a = score_capital_anomaly(symbol, market, cap=10)
    total = news['score'] + ann['score'] + com['score'] + inst['score'] + cap_a['score']
    available_count = sum(1 for x in (news, ann, com, inst, cap_a) if x['available'])
    return {
        'symbol': _clean_symbol(symbol),
        'company_name': company_name,
        'market': (market or 'us').lower(),
        'score_news': news['score'],
        'score_announce': ann['score'],
        'score_community': com['score'],
        'score_institution': inst['score'],
        'score_capital': cap_a['score'],
        'score_total': total,
        'neutral_news': news.get('neutral_score', 12.5),
        'neutral_announce': ann.get('neutral_score', 10.0),
        'neutral_community': com.get('neutral_score', 12.5),
        'neutral_institution': inst.get('neutral_score', 10.0),
        'neutral_capital': cap_a.get('neutral_score', 5.0),
        'adjust_news': news.get('score_adjustment'),
        'adjust_announce': ann.get('score_adjustment'),
        'adjust_community': com.get('score_adjustment'),
        'adjust_institution': inst.get('score_adjustment'),
        'adjust_capital': cap_a.get('score_adjustment'),
        'neutral_total': 50.0,
        'covered_neutral_total': sum(
            item.get('neutral_score', 0) for item in (news, ann, com, inst, cap_a)
            if item.get('available')
        ),
        'score_adjustment_total': total - 50.0 if available_count == 5 else None,
        'scoring_semantics': 'merged_evidence_neutral_midpoint_v2',
        'available_news': news['available'],
        'available_announce': ann['available'],
        'available_community': com['available'],
        'available_institution': inst['available'],
        'available_capital': cap_a['available'],
        'available_count': available_count,
        'evidence_news': news['evidence'],
        'evidence_announce': ann['evidence'],
        'evidence_community': com['evidence'],
        'evidence_institution': inst['evidence'],
        'evidence_capital': cap_a['evidence'],
        'raw': {
            'news': news.get('raw', {}),
            'announce': ann.get('raw', {}),
            'community': com.get('raw', {}),
            'institution': inst.get('raw', {}),
            'capital': cap_a.get('raw', {}),
        },
        'computed_at': datetime.now().isoformat(),
    }


if __name__ == '__main__':
    import sys as _s
    sym = _s.argv[1] if len(_s.argv) > 1 else 'AAPL'
    mkt = _s.argv[2] if len(_s.argv) > 2 else 'us'
    name = _s.argv[3] if len(_s.argv) > 3 else ''
    res = score_all(sym, mkt, name)
    print(json.dumps(res, ensure_ascii=False, indent=2))
