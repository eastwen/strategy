#!/usr/bin/env python3
"""
五源共振真实评分模块 v1.4
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
import sqlite3
import requests
import time
import threading
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Dict, Any, List

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


def _empty(cap: int, reason: str) -> Dict[str, Any]:
    return {
        'score': 0,
        'available': False,
        'evidence': f'未覆盖（{reason}）',
        'raw': {'reason': reason},
    }


def _count_keywords(text: str, words: List[str]) -> int:
    text = (text or '').lower()
    return sum(1 for w in words if w in text)


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


def _best_wins(candidates: List[Dict[str, Any]], cap: int, dim: str) -> Dict[str, Any]:
    """多源 best-wins：收集所有可用源结果，去重后取分数最高者。

    取代旧逻辑的「第一个可用源就 return」，避免首源（如 Finnhub）保守打分
    直接压低整维分数；同时去掉证据完全重复的多余源。
    """
    if not candidates:
        return _empty(cap, f'{dim}无可用源')
    seen_ev = set()
    uniq = []
    for c in candidates:
        ev = c.get('evidence', '')
        if ev in seen_ev:
            continue
        seen_ev.add(ev)
        uniq.append(c)
    return max(uniq, key=lambda r: r.get('score', 0))


def _average_available_sources(candidates: List[Dict[str, Any]], cap: int, dim: str, dedupe: bool = False) -> Dict[str, Any]:
    """将可用源等权平均；公告/机构可按归一化证据去重。"""
    usable = [c for c in candidates if c.get('available')]
    if not usable:
        return _empty(cap, f'{dim}无可用源')
    removed = 0
    if dedupe:
        seen = set()
        unique = []
        for candidate in usable:
            key = _norm_title(candidate.get('evidence', ''))
            if key and key in seen:
                removed += 1
                continue
            if key:
                seen.add(key)
            unique.append(candidate)
        usable = unique
    score = int(round(sum(float(c.get('score', 0) or 0) for c in usable) / len(usable)))
    source_rows = []
    for candidate in usable:
        raw = candidate.get('raw', {}) or {}
        source_rows.append({'source': raw.get('source', 'unknown'), 'score': candidate.get('score', 0)})
    suffix = f'，去重{removed}源' if dedupe else ''
    return {
        'score': max(0, min(cap, score)),
        'available': True,
        'evidence': f'多源平均{dim} {len(usable)}源{suffix}: ' + ' / '.join(str(r['score']) for r in source_rows),
        'raw': {'source': 'multi_source_average', 'source_scores': source_rows, 'duplicates_removed': removed},
    }


def _grouped_institution_average(candidates: List[Dict[str, Any]], cap: int) -> Dict[str, Any]:
    """先合并同类分析师共识，再与独立机构源做组间等权平均。"""
    groups: Dict[str, List[float]] = {}
    labels = {
        'finnhub_recommendation': '分析师共识',
        'yfinance': '分析师共识',
        'futu_research': '富途研报',
        'tinkclaw': 'TinkClaw',
        'news_db': '研报新闻',
    }
    for candidate in candidates:
        if not candidate.get('available'):
            continue
        source = (candidate.get('raw', {}) or {}).get('source', 'unknown')
        group = labels.get(source, source)
        groups.setdefault(group, []).append(float(candidate.get('score', 0) or 0))
    if not groups:
        return _empty(cap, '机构观点无可用源')
    group_scores = {group: sum(scores) / len(scores) for group, scores in groups.items()}
    score = int(round(sum(group_scores.values()) / len(group_scores)))
    detail = ' / '.join(f'{group}:{value:.1f}' for group, value in group_scores.items())
    return {
        'score': max(0, min(cap, score)),
        'available': True,
        'evidence': f'分组平均机构观点 {len(group_scores)}组: {detail}',
        'raw': {'source': 'grouped_institution_average', 'group_scores': group_scores},
    }


def _aggregate_deduped_news(candidates: List[Dict[str, Any]], cap: int) -> Dict[str, Any]:
    """全源新闻按标题精确/相似匹配去重后计算综合分。"""
    events: List[Dict[str, Any]] = []
    source_names = []
    for candidate in candidates:
        raw = candidate.get('raw', {}) or {}
        source = raw.get('source', 'unknown')
        source_names.append(source)
        for article in raw.get('articles', []) or []:
            title = (article.get('title') or '').strip()
            if not _norm_title(title):
                continue
            event = next((item for item in events if _titles_similar(title, item['title'])), None)
            if event is None:
                event = {'title': title, 'sentiments': []}
                events.append(event)
            try:
                event['sentiments'].append(float(article.get('sentiment', 0.5)))
            except Exception:
                event['sentiments'].append(0.5)
    if not events:
        return _empty(cap, '国际资讯无可去重新闻')
    rows = []
    duplicate_count = 0
    for event in events:
        duplicate_count += max(0, len(event['sentiments']) - 1)
        rows.append((event['title'], sum(event['sentiments']) / len(event['sentiments'])))
    signal = _headline_signal(rows)
    count = len(rows)
    score = int(round(
        min(1.0, count / 10) * 0.45 * cap +
        signal['keyword_sent'] * 0.35 * cap +
        signal['avg_sent'] * 0.20 * cap
    ))
    return {
        'score': max(0, min(cap, score)),
        'available': True,
        'evidence': f"多源去重资讯 24h {count} 条（去重{duplicate_count}条），情绪 {signal['avg_sent']:.2f}，多:空={signal['pos']}:{signal['neg']}",
        'raw': {'source': 'deduped_composite', 'sources': sorted(set(source_names)),
                'count': count, 'duplicates_removed': duplicate_count, **signal},
    }


# --- 通用数据源备用函数 --------------------------------
def _news_futu(symbol: str, cap: int, news_type: int = 1, hours: int = 24) -> Dict[str, Any]:
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
        positives = ['surge', 'rally', 'beat', 'upgrade', 'soar', 'jump', 'breakthrough',
                     'strong', 'record', 'profit', 'gain', 'outperform', 'bull', 'rise', 'higher', 'growth',
                     '涨', '涨超', '大涨', '暴涨', '利好', '突破', '获批', '回购', '加仓', '上调', '买入', '强劲', '增长', '盈利', '中标', '反弹']
        negatives = ['plunge', 'crash', 'miss', 'downgrade', 'lawsuit', 'investigation',
                     'warning', 'loss', 'cut', 'concern', 'risk', 'fall', 'bear', 'sue', 'drop', 'lower',
                     '跌', '跌超', '大跌', '暴跌', '利空', '破位', '调查', '诉讼', '召回', '下调', '卖出', '警告', '下滑', '违约', '退市', '制裁']
        pos = neg = announce_hits = 0
        for n in recent:
            t = (n.get('title', '') or '').lower()
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
            'raw': {'source': 'futu', 'count': len(recent), 'pos': pos, 'neg': neg, 'announce_hits': announce_hits, 'sentiment': sentiment, 'articles': [{'title': n.get('title', ''), 'sentiment': 0.5} for n in recent]},
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


def _announce_futu(symbol: str, cap: int) -> Dict[str, Any]:
    """使用富途API + alerts.json事件。尝试 news_type=2 (公告)，若无则用 news_type=1 + ANNOUNCE 关键词过滤。"""
    # 第一优先：news_type=2 公告
    futu_news = _news_futu(symbol, cap, news_type=2, hours=168)
    score = 0
    parts = []
    if futu_news.get('available'):
        score += int(futu_news['score'] * 0.6)
        parts.append(futu_news['evidence'])
    else:
        # 第二优先：news_type=1 新闻中检测公告关键词
        general = _news_futu(symbol, cap, news_type=1, hours=168)
        if general.get('available') and general.get('raw', {}).get('count', 0) > 0:
            try:
                raw = general['raw']
                announce_hits = raw.get('announce_hits', 0)
                if announce_hits >= 1:
                    score = int(round(cap * 0.4))
                    parts.append(f"新闻含财报关键词×{announce_hits}")
            except Exception:
                pass
    news_event = _announce_news_event(symbol, cap)
    if news_event.get('available'):
        score += news_event.get('score', 0)
        parts.append(news_event.get('evidence', ''))
    if not parts:
        return _empty(cap, '富途公告+事件无数据')
    return {
        'score': max(0, min(cap, score)),
        'available': True,
        'evidence': ' / '.join(p for p in parts if p),
        'raw': {
            'source': 'futu',
            'futu': futu_news.get('raw', {}),
            'news_event': news_event.get('raw', {}),
        },
    }


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


# --- 维度 1：国际资讯（30 分）---
def score_international_news(symbol: str, market: str = 'us', cap: int = 30) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    # 全量多源：所有已配置源均请求，标题去重后计算综合分。
    candidates = []
    if FINNHUB_KEY:
        try:
            r = _news_finnhub(clean, cap)
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    for fn in (
        lambda: _news_futu(clean, cap, news_type=1),
    ):
        try:
            r = fn()
            if r.get('available'):
                candidates.append(r)
        except Exception:
            continue
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


def _news_finnhub(symbol: str, cap: int) -> Dict[str, Any]:
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
            'raw': {'source': 'finnhub', 'count': len(recent), 'pos': pos, 'neg': neg, 'sentiment': sentiment, 'articles': [{'title': n.get('headline', ''), 'sentiment': 0.5} for n in recent]},
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


# --- 维度 2：官方公告（20 分）---
def score_official_announce(symbol: str, market: str = 'us', cap: int = 20) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    # 全量多源：每个已配置源均执行，重复证据去重后等权平均。
    candidates = []
    if FINNHUB_KEY:
        try:
            r = _cached_source(f'announce:finnhub:{market}:{clean}:{cap}', 4 * 3600, lambda: _announce_finnhub(clean, cap))
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _announce_futu(clean, cap)
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    if ALPHAVANTAGE_KEY:
        try:
            r = _cached_source(f'announce:alphavantage:{market}:{clean}:{cap}', 4 * 3600, lambda: _announce_alphavantage(clean, cap))
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
    return _average_available_sources(candidates, cap, '官方公告', dedupe=True)


ALERTS_PATH = DATA_DIR / 'alerts.json'


def _announce_news_event(symbol: str, cap: int) -> Dict[str, Any]:
    """识别 24h 内的财报/重大公告事件。"""
    score = 0
    parts: List[str] = []
    raw: Dict[str, Any] = {}
    try:
        if os.path.exists(ALERTS_PATH):
            with open(ALERTS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            alerts = data.get('alerts', []) or []
            hit = [a for a in alerts if (a.get('symbol') or '').upper() == symbol.upper()]
            major_pos = [a for a in hit if a.get('alert_type') == '重大利好' and a.get('importance') == '高']
            major_neg = [a for a in hit if a.get('alert_type') == '重大利空' and a.get('importance') == '高']
            normal_pos = [a for a in hit if a.get('alert_type') == '重大利好' and a.get('importance') != '高']
            normal_news = [a for a in hit if a.get('alert_type') == '新闻']
            event_score = 0
            if major_pos:
                event_score = int(round(cap * 0.75))
                parts.append(f"重大利好/高 ×{len(major_pos)}")
            elif normal_pos:
                event_score = int(round(cap * 0.45))
                parts.append(f"重大利好 ×{len(normal_pos)}")
            elif major_neg:
                event_score = -int(round(cap * 0.5))
                parts.append(f"重大利空/高 ×{len(major_neg)}")
            elif normal_news:
                event_score = int(round(cap * 0.15))
                parts.append(f"事件新闻 ×{len(normal_news)}")
            score += event_score
            raw['alerts_match'] = {
                'major_pos': len(major_pos), 'major_neg': len(major_neg),
                'normal_pos': len(normal_pos), 'normal_news': len(normal_news),
                'event_score': event_score,
            }
    except Exception as e:
        raw['alerts_err'] = str(e)
    try:
        conn = sqlite3.connect(NEWS_DB_PATH)
        rows = conn.execute(
            '''SELECT title, sentiment FROM news
               JOIN stock_mentions ON news.id = stock_mentions.news_id
               WHERE stock_mentions.symbol = ?
               AND news.timestamp > datetime("now", "-24 hours")''',
            (symbol,)
        ).fetchall()
        conn.close()
        if rows:
            rows = _dedupe_rows(rows)
            announce_hits = sum(
                _count_keywords(t or '', ANNOUNCE_WORDS) for t, _ in rows
            )
            if announce_hits >= 2:
                avg_sent = sum(float(s) for _, s in rows if s is not None) / max(1, len(rows))
                if avg_sent <= 0.35:
                    extra = -int(round(cap * 0.2))
                    score += extra
                    parts.append(f"财报关键词×{announce_hits}(负面)")
                    raw['keyword_event'] = {'hits': announce_hits, 'avg_sent': round(avg_sent, 2), 'extra': extra}
                elif announce_hits >= 8 and avg_sent >= 0.5:
                    extra = int(round(cap * 0.35))
                    score += extra
                    parts.append(f"财报关键词×{announce_hits}(业绩事件)")
                    raw['keyword_event'] = {'hits': announce_hits, 'avg_sent': round(avg_sent, 2), 'extra': extra}
                elif avg_sent >= 0.6:
                    extra = int(round(cap * 0.25))
                    score += extra
                    parts.append(f"财报关键词×{announce_hits}(正面)")
                    raw['keyword_event'] = {'hits': announce_hits, 'avg_sent': round(avg_sent, 2), 'extra': extra}
                elif avg_sent >= 0.48:
                    extra = int(round(cap * 0.15))
                    score += extra
                    parts.append(f"财报关键词×{announce_hits}(中性偏正)")
                    raw['keyword_event'] = {'hits': announce_hits, 'avg_sent': round(avg_sent, 2), 'extra': extra}
                else:
                    raw['keyword_event'] = {'hits': announce_hits, 'avg_sent': round(avg_sent, 2), 'extra': 0}
    except Exception as e:
        raw['keyword_event_err'] = str(e)
    if not parts:
        return _empty(cap, 'alerts/news 24h 无事件')
    return {
        'score': max(-cap, min(cap, score)),
        'available': True,
        'evidence': ' · '.join(parts),
        'raw': raw,
    }


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
    news_event = _announce_news_event(symbol, cap)
    if news_event.get('available'):
        score += news_event['score']
        parts.append(news_event['evidence'])
        raw['news_event'] = news_event.get('raw', {})
    if not parts:
        return _empty(cap, '无财报/内部人数据')
    return {
        'score': max(0, min(cap, score)),
        'available': True,
        'evidence': ' / '.join(parts),
        'raw': raw,
    }


# --- 维度 3：社区情绪（25 分）---
def score_community(symbol: str, market: str = 'us', cap: int = 25) -> Dict[str, Any]:
    clean = _clean_symbol(symbol)
    sources = ['新浪财经', '东方财富', '观察者网', '36氪', '金十数据', 'IT之家']

    # 社区保留各平台独立讨论，不做跨平台去重；所有源都尝试并等权平均。
    candidates = [
        _news_db(clean, cap, sources),
        _community_futu_comment(clean, cap),
        _community_longbridge(clean, cap),
    ]
    if (market or 'us').lower() == 'us':
        candidates.append(_us_public_attention(clean, cap))
    return _average_available_sources(candidates, cap, '社区情绪', dedupe=False)


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
            'raw': {'source': 'us_public_attention', 'count': len(rows), **sig},
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
            'raw': {'source': 'futu_research', 'count': len(recent), 'pos': pos, 'neg': neg, 'direction': direction},
        }
    except Exception as e:
        return _empty(cap, f'富途研报失败: {e}')


# --- 维度 4：机构观点（25 分）---
def score_institution(symbol: str, market: str = 'us', cap: int = 25) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    # 全量多源：每个已配置源均执行，重复证据去重后等权平均。
    candidates = []
    if FINNHUB_KEY:
        try:
            r = _cached_source(f'institution:finnhub:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_finnhub(clean, cap))
            if r.get('available'):
                candidates.append(r)
        except Exception:
            pass
    try:
        r = _cached_source(f'institution:yfinance:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_yfinance(clean, cap))
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    try:
        r = _cached_source(f'institution:futu:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_futu_research(clean, cap))
        if r.get('available'):
            candidates.append(r)
    except Exception:
        pass
    if TINKCLAW_KEY:
        try:
            r = _cached_source(f'institution:tinkclaw:{market}:{clean}:{cap}', 4 * 3600, lambda: _institution_tinkclaw(clean, cap))
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
    return _grouped_institution_average(candidates, cap)


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
        super_inflow_ratio = max(0.0, min(1.0, super_net_flow / total_abs_flow)) if total_abs_flow > 0 else 0.0

        consecutive_main_outflow_days = 0
        for row in reversed(flow_rows):
            if float(row.get('main_in_flow', 0) or 0) < 0:
                consecutive_main_outflow_days += 1
            else:
                break

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
        short_adjustment = 0.0
        if abs(short_delta_pp) >= 0.20:
            short_adjustment = min(2.0, abs(short_delta_pp) / 0.50 * 2.0)
            if short_delta_pp > 0:
                short_adjustment *= -1

        score = (
            5.0
            + min(3.0, super_inflow_ratio * 3.0)
            - min(3.0, consecutive_main_outflow_days * 0.5)
            + short_adjustment
        )
        score = int(round(max(0.0, min(float(cap), score))))

        flow_direction = '净流入' if super_net_flow > 0 else '净流出' if super_net_flow < 0 else '持平'
        short_text = '卖空数据不足'
        if short_latest is not None:
            short_text = f"卖空{short_latest:.2f}% ({short_delta_pp:+.2f}pp)"
        evidence = (
            f"富途连续资金: 特大单{flow_direction}{super_net_flow:,.0f}"
            f"(占比{super_inflow_ratio:.1%})，主力连续净流出{consecutive_main_outflow_days}日，{short_text}"
        )
        result = {
            'score': score,
            'available': True,
            'evidence': evidence,
            'raw': {
                'source': 'futu_capital_flow_short_interest',
                'days': len(flow_rows),
                'super_net_flow': super_net_flow,
                'total_abs_flow': total_abs_flow,
                'super_inflow_ratio': round(super_inflow_ratio, 6),
                'consecutive_main_outflow_days': consecutive_main_outflow_days,
                'short_latest_pct': short_latest,
                'short_previous_pct': short_previous,
                'short_delta_pp': round(short_delta_pp, 4),
                'short_adjustment': round(short_adjustment, 4),
            },
        }
        with _CAPITAL_METRICS_LOCK:
            _CAPITAL_METRICS_CACHE[cache_key] = {'timestamp': now, 'result': result}
        return result
    except Exception as e:
        return _empty(cap, f'富途连续资金数据失败: {e}')


# --- 聚合 ---
def score_all(symbol: str, market: str = 'us') -> Dict[str, Any]:
    news = score_international_news(symbol, market, cap=25)
    ann = score_official_announce(symbol, market, cap=20)
    com = score_community(symbol, market, cap=25)
    inst = score_institution(symbol, market, cap=20)
    cap_a = score_capital_anomaly(symbol, market, cap=10)
    total = news['score'] + ann['score'] + com['score'] + inst['score'] + cap_a['score']
    available_count = sum(1 for x in (news, ann, com, inst, cap_a) if x['available'])
    return {
        'symbol': _clean_symbol(symbol),
        'market': (market or 'us').lower(),
        'score_news': news['score'],
        'score_announce': ann['score'],
        'score_community': com['score'],
        'score_institution': inst['score'],
        'score_capital': cap_a['score'],
        'score_total': total,
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
    res = score_all(sym, mkt)
    print(json.dumps(res, ensure_ascii=False, indent=2))
