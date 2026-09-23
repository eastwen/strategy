#!/usr/bin/env python3
"""Regression tests for weekly official stock-pool refreshes."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HK = load_module('hk_pool_updater', 'get-constituents.py')
US = load_module('us_pool_updater', 'get-us-constituents.py')


class StockPoolUpdateTest(unittest.TestCase):
    @patch.object(US, 'fetch_sp500_github')
    @patch.object(US, 'fetch_sp500_wikipedia')
    def test_sp500_runs_both_sources_and_prefers_wikipedia(self, wiki, github):
        wiki.return_value = [f'SP{i}' for i in range(500)]
        github.return_value = [f'SP{i}' for i in range(499)] + ['GITHUB_ONLY']
        result = US.fetch_sp500()
        self.assertEqual(result, wiki.return_value)
        wiki.assert_called_once_with()
        github.assert_called_once_with()

    @patch.object(US, 'fetch_sp500_github')
    @patch.object(US, 'fetch_sp500_wikipedia')
    def test_sp500_uses_github_when_wikipedia_fails(self, wiki, github):
        wiki.side_effect = RuntimeError('blocked')
        github.return_value = [f'SP{i}' for i in range(500)]
        self.assertEqual(US.fetch_sp500(), github.return_value)

    def test_hk_keeps_official_and_explicit_custom_symbols(self):
        hsi = [f'HK.{i:05d}' for i in range(1, 51)]
        hstech = [f'HK.{i:05d}' for i in range(700, 720)]
        manual = ['HK.01234']
        updated = HK.build_updated_pool(hsi, hstech, manual)
        expected_custom = manual + HK.REQUIRED_CUSTOM_SYMBOLS
        expected = list(dict.fromkeys(hsi + hstech + expected_custom))
        self.assertEqual(updated['hk_all'], expected)
        self.assertEqual(updated['custom'], expected_custom)
        self.assertNotIn('legacy_extra', updated)

    def test_us_keeps_official_and_explicit_custom_symbols(self):
        sp500 = [f'SP{i}' for i in range(450)] + ['AAPL']
        nasdaq = [f'NQ{i}' for i in range(3000)] + ['MSFT']
        finnhub = ['MSFT', 'AMEX_ONLY']
        custom = ['USER_PICK']
        updated = US.build_updated_pool(
            sp500, nasdaq, finnhub, existing_custom=custom,
        )
        self.assertEqual(
            updated['all'],
            list(dict.fromkeys(
                sp500 + nasdaq + finnhub + custom
            )),
        )
        self.assertEqual(updated['custom'], custom)
        self.assertNotIn('legacy_extra', updated)

    def test_nasdaq_security_type_filter(self):
        base = {'Test Issue': 'N', 'ETF': 'N'}
        self.assertTrue(US._is_supported_nasdaq_security({
            **base, 'Symbol': 'AEHR', 'Security Name': 'Aehr Test Systems - Common Stock',
        }))
        for name in (
            'Example Corp - Warrant',
            'Example Corp - Rights',
            'Example Corp - Unit',
            'Example Corp - Preferred Stock',
        ):
            self.assertFalse(US._is_supported_nasdaq_security({
                **base, 'Symbol': 'TEST', 'Security Name': name,
            }))

    def test_us_market_cap_filter_removes_sub_500m_from_pool(self):
        updated = US.build_updated_pool(
            ['AAPL'], ['SMALL', 'LARGE'], ['SMALL'],
            existing_custom=['TINY'],
            market_caps={
                'AAPL': 3_000_000_000_000,
                'SMALL': 499_999_999,
                'LARGE': 2_000_000_000,
                'TINY': 100_000_000,
            },
        )
        self.assertEqual(updated['all'], ['AAPL', 'LARGE'])
        self.assertEqual(updated['nasdaq'], ['LARGE'])
        self.assertEqual(updated['finnhub_us'], [])
        self.assertEqual(updated['custom'], [])
        self.assertEqual(
            updated['market_cap_filter']['excluded_symbols'], ['SMALL', 'TINY'],
        )

    def test_unknown_market_cap_is_excluded_from_strict_pool(self):
        updated = US.build_updated_pool(
            ['AAPL'], ['UNKNOWN'], market_caps={'AAPL': 3_000_000_000_000},
        )
        self.assertNotIn('UNKNOWN', updated['all'])
        self.assertEqual(
            updated['market_cap_filter']['unresolved_excluded_symbols'], ['UNKNOWN'],
        )


if __name__ == '__main__':
    unittest.main()
