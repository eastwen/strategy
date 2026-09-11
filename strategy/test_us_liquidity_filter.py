#!/usr/bin/env python3
"""Offline regression tests for the US first-layer liquidity gate."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    'us_scanner_liquidity_under_test',
    ROOT / 'us-scanner.py',
)
SCANNER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER_MODULE)
USScanner = SCANNER_MODULE.USScanner


class USLiquidityFilterTest(unittest.TestCase):
    def test_zero_volume_sessions_are_counted_and_block_sparse_stock(self):
        closes = [4.0] * 20
        volumes = [0] * 7 + [9_000] * 12 + [7_270_000]

        metrics = USScanner._liquidity_metrics(closes, volumes, 'test')

        self.assertEqual(metrics['sessions'], 20)
        self.assertEqual(metrics['active_sessions'], 13)
        self.assertGreater(metrics['avg_volume'], 300_000)
        self.assertFalse(metrics['passed'])

    def test_single_volume_spike_cannot_lift_illiquid_stock(self):
        closes = [5.0] * 20
        volumes = [10_000] * 19 + [10_000_000]

        metrics = USScanner._liquidity_metrics(closes, volumes, 'test')

        self.assertEqual(metrics['active_sessions'], 20)
        self.assertGreater(metrics['avg_volume'], 300_000)
        self.assertEqual(metrics['median_dollar_volume'], 50_000)
        self.assertEqual(metrics['trimmed_avg_dollar_volume'], 50_000)
        self.assertFalse(metrics['passed'])

    def test_consistently_liquid_stock_passes(self):
        closes = [20.0] * 20
        volumes = [1_000_000] * 20

        metrics = USScanner._liquidity_metrics(closes, volumes, 'test')

        self.assertEqual(metrics['active_sessions'], 20)
        self.assertEqual(metrics['median_dollar_volume'], 20_000_000)
        self.assertTrue(metrics['passed'])

    def test_unified_first_layer_filter_drops_failed_candidate(self):
        scanner = object.__new__(USScanner)
        scanner._layer1_drop_stats = {'liquidity_dropped': 0}
        scanner._load_daily_liquidity_cache = lambda: {
            'ADXN': USScanner._liquidity_metrics(
                [4.0] * 20,
                [0] * 7 + [9_000] * 12 + [7_270_000],
                'test',
            ),
            'AAPL': USScanner._liquidity_metrics(
                [200.0] * 20,
                [50_000_000] * 20,
                'test',
            ),
        }
        scanner._save_daily_liquidity_cache = lambda entries: None

        kept = scanner._filter_candidates_by_liquidity([
            {'symbol': 'ADXN', 'base_score': 90},
            {'symbol': 'AAPL', 'base_score': 80},
        ])

        self.assertEqual([item['symbol'] for item in kept], ['AAPL'])
        self.assertEqual(scanner._layer1_drop_stats['liquidity_dropped'], 1)

    def test_old_cache_version_is_ignored(self):
        scanner = object.__new__(USScanner)
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / 'liquidity.json'
            cache_path.write_text(json.dumps({
                'date': SCANNER_MODULE.current_us_market_date().isoformat(),
                'entries': {'ADXN': {'passed': True}},
            }), encoding='utf-8')

            with patch.object(SCANNER_MODULE, '_LIQUIDITY_CACHE_PATH', cache_path):
                self.assertEqual(scanner._load_daily_liquidity_cache(), {})

                scanner._save_daily_liquidity_cache({'AAPL': {'passed': True}})
                payload = json.loads(cache_path.read_text(encoding='utf-8'))

        self.assertEqual(payload['version'], SCANNER_MODULE._LIQUIDITY_CACHE_VERSION)
        self.assertIn('AAPL', payload['entries'])


if __name__ == '__main__':
    unittest.main()
