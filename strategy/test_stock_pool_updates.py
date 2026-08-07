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


if __name__ == '__main__':
    unittest.main()
