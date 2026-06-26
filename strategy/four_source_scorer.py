#!/home/admin/.openclaw/workspace-stock/futu-venv/bin/python3.14
"""
四源共振真实评分模块 v1.0

2026-06-24 east 新建：彻底替代"硬拆 base_score"的假四源。
四个维度，每个维度有独立的数据源、抓取方法、打分规则，零硬拆。

权重设计:
  美股:  国际资讯 30 + 官方公告 20 + 社区情绪 25 + 机构观点 25 = 100
  港股:  国际资讯 30 + 港股公告 20 + 国内社区 25 + 海外社交 25 = 100

每个维度返回:
  {
    'score': int,           # 0~cap
    'available': bool,      # True=有真实数据；False=无数据
    'evidence': str,        # 通知用一句话证据
    'raw': {...}
  }
"""

import os
import json
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List

API_KEYS_PATH = '/home/admin/.openclaw/workspace-stock/strategy/.api-keys.json'
NEWS_DB_PATH = '/home/admin/.openclaw/workspace-stock/data/news/news.db'


def _load_keys() -> Dict[str, Any]:
    if os.path.exists(API_KEYS_PATH):
        try:
            with open(API_KEYS_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


_KEYS = _load_keys()
FINNHUB_KEY = _KEYS.get('finnhub', {}).get('api_key', '')

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


# --- 维度 1：国际资讯（30 分） -----------------------------
def score_international_news(symbol: str, market: str = 'us', cap: int = 30) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    if market == 'us' and FINNHUB_KEY:
        return _news_finnhub(clean, cap)
    return _news_db(clean, cap, ['Yahoo Finance', 'Finnhub', 'Google News Tech'])


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
            'raw': {'count': len(recent), 'pos': pos, 'neg': neg, 'sentiment': sentiment},
        }
    except Exception as e:
        return _empty(cap, f'Finnhub 失败: {e}')


def _news_db(symbol: str, cap: int, sources: List[str]) -> Dict[str, Any]:
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
            return _empty(cap, 'news.db 24h 无数据')
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
            'raw': {'count': count, **sig},
        }
    except Exception as e:
        return _empty(cap, f'news.db 失败: {e}')


# --- 维度 2：官方公告（20 分） -----------------------------
def score_official_announce(symbol: str, market: str = 'us', cap: int = 20) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    if market == 'us' and FINNHUB_KEY:
        return _announce_finnhub(clean, cap)
    return _news_db(clean, cap, ['SEC EDGAR', '港交所', 'Tushare-公告'])


ALERTS_PATH = '/home/admin/.openclaw/workspace-stock/data/alerts.json'


def _announce_news_event(symbol: str, cap: int) -> Dict[str, Any]:
    """识别 24h 内的财报/重大公告事件。

    数据源优先级：
      1) data/alerts.json —— news_pipeline 已分类的"重大利好/重大利空/新闻"
      2) news.db —— 含 earnings/eps/guidance 等关键词的近24h新闻
    """
    score = 0
    parts: List[str] = []
    raw: Dict[str, Any] = {}

    # === Step 1: alerts.json (news_pipeline 已分类) ===
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
                event_score = int(round(cap * 0.75))   # 满档 (cap=20 -> 15)
                parts.append(f"重大利好/高 ×{len(major_pos)}")
            elif normal_pos:
                event_score = int(round(cap * 0.45))   # cap=20 -> 9
                parts.append(f"重大利好 ×{len(normal_pos)}")
            elif major_neg:
                event_score = -int(round(cap * 0.5))
                parts.append(f"重大利空/高 ×{len(major_neg)}")
            elif normal_news:
                event_score = int(round(cap * 0.15))   # cap=20 -> 3
                parts.append(f"事件新闻 ×{len(normal_news)}")

            score += event_score
            raw['alerts_match'] = {
                'major_pos': len(major_pos), 'major_neg': len(major_neg),
                'normal_pos': len(normal_pos), 'normal_news': len(normal_news),
                'event_score': event_score,
            }
    except Exception as e:
        raw['alerts_err'] = str(e)

    # === Step 2: news.db 兜底 —— 24h 内含财报关键词的新闻 ===
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
            announce_hits = sum(
                _count_keywords(t or '', ANNOUNCE_WORDS) for t, _ in rows
            )
            if announce_hits >= 2:
                avg_sent = sum(float(s) for _, s in rows if s is not None) / max(1, len(rows))
                # 财报关键词命中: 正面情绪附加加分，负面情绪减分
                tone = 1 if avg_sent >= 0.6 else (-1 if avg_sent <= 0.35 else 0)
                if tone > 0:
                    extra = int(round(cap * 0.25))   # cap=20 -> 5
                    score += extra
                    parts.append(f"财报关键词×{announce_hits}(正面)")
                    raw['keyword_event'] = {'hits': announce_hits, 'avg_sent': round(avg_sent, 2), 'extra': extra}
                elif tone < 0:
                    score -= int(round(cap * 0.2))
                    parts.append(f"财报关键词×{announce_hits}(负面)")
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
    raw: Dict[str, Any] = {}

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


# --- 维度 3：社区情绪（25 分） -----------------------------
def score_community(symbol: str, market: str = 'us', cap: int = 25) -> Dict[str, Any]:
    clean = _clean_symbol(symbol)
    sources = ['新浪财经', '东方财富', '观察者网', '36氪', '金十数据', 'IT之家']
    primary = _news_db(clean, cap, sources)
    if primary.get('available') or (market or 'us').lower() != 'us':
        return primary
    return _us_public_attention(clean, cap)


def _us_public_attention(symbol: str, cap: int) -> Dict[str, Any]:
    # Fallback for US stocks when explicit community sources are absent.
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
            'raw': {'count': len(rows), **sig},
        }
    except Exception as e:
        return _empty(cap, f'公开讨论失败: {e}')


# --- 维度 4：机构观点（25 分） -----------------------------
def score_institution(symbol: str, market: str = 'us', cap: int = 25) -> Dict[str, Any]:
    market = (market or 'us').lower()
    clean = _clean_symbol(symbol)
    if market == 'us' and FINNHUB_KEY:
        return _institution_finnhub(clean, cap)
    return _news_db(clean, cap, ['Reuters Tech', 'CNBC', 'Wired', 'Ars Technica'])


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
        net = bull - bear  # -1~1

        # 月度变动方向（与上月比）
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

        base = max(0.0, (net + 1) / 2)  # 映射到 0~1
        score = int(round(min(1.0, base + trend_bonus) * cap))
        evidence = f"分析师 {total} 家：强买{strong_buy} 买{buy} 中{hold} 卖{sell+strong_sell}"
        return {
            'score': max(0, min(cap, score)),
            'available': True,
            'evidence': evidence,
            'raw': {
                'strong_buy': strong_buy, 'buy': buy, 'hold': hold,
                'sell': sell, 'strong_sell': strong_sell,
                'bull_ratio': bull, 'bear_ratio': bear, 'trend_bonus': trend_bonus,
            },
        }
    except Exception as e:
        return _empty(cap, f'Finnhub 失败: {e}')


# --- 聚合 ---------------------------------------------------
def score_all(symbol: str, market: str = 'us') -> Dict[str, Any]:
    """同时跑四个维度，返回完整四源评分。

    Returns:
        {
          'symbol': str, 'market': str,
          'score_news': int, 'score_announce': int, 'score_community': int, 'score_institution': int,
          'score_total': int,                                 # 四项相加
          'available_news/announce/community/institution': bool,
          'evidence_news/announce/community/institution': str,
          'available_count': int (0~4),
          'raw': {...}
        }
    """
    news = score_international_news(symbol, market, cap=30)
    ann = score_official_announce(symbol, market, cap=20)
    com = score_community(symbol, market, cap=25)
    inst = score_institution(symbol, market, cap=25)

    total = news['score'] + ann['score'] + com['score'] + inst['score']
    available_count = sum(1 for x in (news, ann, com, inst) if x['available'])

    return {
        'symbol': _clean_symbol(symbol),
        'market': (market or 'us').lower(),
        'score_news': news['score'],
        'score_announce': ann['score'],
        'score_community': com['score'],
        'score_institution': inst['score'],
        'score_total': total,
        'available_news': news['available'],
        'available_announce': ann['available'],
        'available_community': com['available'],
        'available_institution': inst['available'],
        'available_count': available_count,
        'evidence_news': news['evidence'],
        'evidence_announce': ann['evidence'],
        'evidence_community': com['evidence'],
        'evidence_institution': inst['evidence'],
        'raw': {
            'news': news.get('raw', {}),
            'announce': ann.get('raw', {}),
            'community': com.get('raw', {}),
            'institution': inst.get('raw', {}),
        },
        'computed_at': datetime.now().isoformat(),
    }


if __name__ == '__main__':
    import sys as _s
    sym = _s.argv[1] if len(_s.argv) > 1 else 'AAPL'
    mkt = _s.argv[2] if len(_s.argv) > 2 else 'us'
    res = score_all(sym, mkt)
    print(json.dumps(res, ensure_ascii=False, indent=2))
