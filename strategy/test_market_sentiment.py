#!/usr/bin/env python3
"""Offline regression tests for US market sentiment scoring."""

import unittest

from us_market_sentiment import USMarketSentiment


class USMarketSentimentTest(unittest.TestCase):
    def test_weighted_sentiment_score(self):
        monitor = USMarketSentiment()

        def fake_indexes():
            monitor.spx = 5000.0
            monitor.spx_change = 1.5
            monitor.ndx = {'price': 18000.0, 'change_pct': 1.2}
            monitor.dji = {'price': 40000.0, 'change_pct': 0.8}

        monitor.get_market_indexes = fake_indexes
        monitor.get_vix = lambda: 15.0
        monitor.get_fear_greed = lambda: 80.0
        monitor.get_put_call_ratio = lambda: 0.7

        result = monitor.get_market_sentiment()

        self.assertEqual(result['sentiment_score'], 74)
        self.assertEqual(result['sentiment_label'], '偏乐观')
        self.assertEqual(result['vix_score'], 70)
        self.assertEqual(result['fg_score'], 85)
        self.assertEqual(result['pcr_score'], 70)
        self.assertEqual(result['spx_score'], 70)

    def test_available_components_are_reweighted(self):
        monitor = USMarketSentiment()
        monitor.get_market_indexes = lambda: None
        monitor.get_vix = lambda: 30.0
        monitor.get_fear_greed = lambda: None
        monitor.get_put_call_ratio = lambda: None

        result = monitor.get_market_sentiment()

        self.assertEqual(result['sentiment_score'], 15)
        self.assertEqual(result['sentiment_label'], '恐慌')
        self.assertIsNone(result['fear_greed'])
        self.assertIsNone(result['option_ratio'])


if __name__ == '__main__':
    unittest.main()
