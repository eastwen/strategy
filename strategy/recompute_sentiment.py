#!/usr/bin/env python3
"""
回填历史新闻 sentiment - 用新版词典重新打分
2026-06-16 创建

用法:
  python3 recompute_sentiment.py --dry-run    # 试运行，只统计变化
  python3 recompute_sentiment.py              # 实际写入
"""
import sys
import sqlite3
import argparse
from collections import Counter

sys.path.insert(0, '/home/admin/.openclaw/workspace-stock/strategy')
from news_pipeline import StableNewsSources

DB_PATH = '/home/admin/.openclaw/workspace-stock/data/news/news.db'


def label(s):
    if s is None:
        return 'NULL'
    if s > 0.6:
        return 'bullish'
    if s < 0.4:
        return 'bearish'
    return 'neutral'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只统计变化，不写入')
    ap.add_argument('--batch', type=int, default=1000, help='提交批次大小')
    args = ap.parse_args()

    src = StableNewsSources()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, title, content, sentiment FROM news")
    rows = cur.fetchall()
    total = len(rows)
    print(f"📊 总条数: {total}")

    transitions = Counter()  # (old_label, new_label)
    delta_dist = Counter()
    updates = []
    same = 0
    changed = 0

    for nid, title, content, old_sent in rows:
        # 标题为主，内容为辅，与原管道一致（原代码就只用标题打分）
        text = title or ''
        new_sent = src.analyze_sentiment(text)

        old_l = label(old_sent)
        new_l = label(new_sent)
        transitions[(old_l, new_l)] += 1

        if old_sent is None or abs((old_sent or 0.5) - new_sent) > 0.001:
            changed += 1
            delta_dist[round(new_sent - (old_sent or 0.5), 1)] += 1
            updates.append((new_sent, nid))
        else:
            same += 1

    print(f"\n✏️  需要更新: {changed}")
    print(f"✅ 保持不变: {same}")

    print("\n📈 标签转移矩阵 (旧 → 新):")
    print(f"{'旧':<10}{'新':<10}{'数量':>8}")
    for (o, n), c in sorted(transitions.items(), key=lambda x: -x[1]):
        marker = '  ⭐' if o != n else ''
        print(f"{o:<10}{n:<10}{c:>8}{marker}")

    # 重点关注：旧 neutral → 新 bullish/bearish
    flip = sum(c for (o, n), c in transitions.items()
               if o == 'neutral' and n != 'neutral')
    print(f"\n🎯 旧中性 → 新有方向: {flip} 条 (这是新词典抓到的隐藏信号)")

    if args.dry_run:
        print("\n🧪 dry-run 模式，未写入数据库")
        conn.close()
        return

    print(f"\n💾 开始写入 {changed} 条更新...")
    n = 0
    for new_sent, nid in updates:
        cur.execute("UPDATE news SET sentiment=? WHERE id=?", (new_sent, nid))
        n += 1
        if n % args.batch == 0:
            conn.commit()
            print(f"   已提交 {n}/{changed}")
    conn.commit()
    print(f"✅ 完成！共更新 {n} 条")
    conn.close()


if __name__ == '__main__':
    main()
