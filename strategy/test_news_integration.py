#!/usr/bin/env python3
"""Offline regression tests for news persistence and deduplication."""

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from news_pipeline import NewsDatabase


class NewsDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / 'news.db'
        self.database = NewsDatabase(self.db_path)

    def test_duplicate_news_is_not_recounted_and_mentions_are_merged(self):
        timestamp = datetime.now().isoformat()
        first = {
            'source': 'TestSource',
            'title': 'Company wins a major contract',
            'content': 'first',
            'url': 'https://example.test/1',
            'stocks': ['AAPL'],
            'sentiment': 0.8,
            'timestamp': timestamp,
        }
        duplicate = {
            **first,
            'content': 'duplicate copy',
            'stocks': ['AAPL', 'MSFT'],
        }

        with patch(
            'news_pipeline.StableNewsSources.extract_stocks',
            return_value=[],
        ):
            first_saved = self.database.save_news([first])
            duplicate_saved = self.database.save_news([duplicate])

        self.assertEqual(first_saved, 1)
        self.assertEqual(duplicate_saved, 0)

        conn = sqlite3.connect(self.db_path)
        try:
            news_count = conn.execute('SELECT COUNT(*) FROM news').fetchone()[0]
            mentions = conn.execute(
                'SELECT symbol FROM stock_mentions ORDER BY symbol'
            ).fetchall()
            stats = conn.execute(
                'SELECT count FROM sources_stats WHERE source = ?',
                ('TestSource',),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(news_count, 1)
        self.assertEqual(mentions, [('AAPL',), ('MSFT',)])
        self.assertEqual(stats, (1,))

    def test_two_unique_articles_increment_source_stat_twice(self):
        timestamp = datetime.now().isoformat()
        articles = [
            {
                'source': 'TestSource',
                'title': f'Unique title {index}',
                'content': '',
                'url': '',
                'stocks': [],
                'sentiment': 0.5,
                'timestamp': timestamp,
            }
            for index in range(2)
        ]

        with patch(
            'news_pipeline.StableNewsSources.extract_stocks',
            return_value=[],
        ):
            saved = self.database.save_news(articles)

        conn = sqlite3.connect(self.db_path)
        try:
            stats = conn.execute(
                'SELECT count FROM sources_stats WHERE source = ?',
                ('TestSource',),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(saved, 2)
        self.assertEqual(stats, (2,))


if __name__ == '__main__':
    unittest.main()
