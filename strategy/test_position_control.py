#!/usr/bin/env python3
"""Offline regression tests for position sizing and local trade state."""

import importlib.util
import json
import threading
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from llm_stock_analyzer import LLMStockAnalyzer


STRATEGY_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    'auto_trader_under_test',
    STRATEGY_DIR / 'auto-trader.py',
)
AUTO_TRADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTO_TRADER)
AutoTrader = AUTO_TRADER.AutoTrader

TECH_SPEC = importlib.util.spec_from_file_location(
    'technical_indicators_us_under_test',
    STRATEGY_DIR / 'technical_indicators_us.py',
)
TECH_MODULE = importlib.util.module_from_spec(TECH_SPEC)
TECH_SPEC.loader.exec_module(TECH_MODULE)
USTechIndicators = TECH_MODULE.USTechIndicators

HK_TECH_SPEC = importlib.util.spec_from_file_location(
    'technical_indicators_hk_under_test',
    STRATEGY_DIR / 'technical_indicators_hk.py',
)
HK_TECH_MODULE = importlib.util.module_from_spec(HK_TECH_SPEC)
HK_TECH_SPEC.loader.exec_module(HK_TECH_MODULE)
HKTechIndicators = HK_TECH_MODULE.HKTechIndicators

SCANNER_SPEC = importlib.util.spec_from_file_location(
    'us_scanner_under_test',
    STRATEGY_DIR / 'us-scanner.py',
)
SCANNER_MODULE = importlib.util.module_from_spec(SCANNER_SPEC)
SCANNER_SPEC.loader.exec_module(SCANNER_MODULE)
USScanner = SCANNER_MODULE.USScanner

HK_SCANNER_SPEC = importlib.util.spec_from_file_location(
    'hk_scanner_under_test',
    STRATEGY_DIR / 'hk-scanner.py',
)
HK_SCANNER_MODULE = importlib.util.module_from_spec(HK_SCANNER_SPEC)
HK_SCANNER_SPEC.loader.exec_module(HK_SCANNER_MODULE)
HKScanner = HK_SCANNER_MODULE.HKScanner


class PositionControlTest(unittest.TestCase):
    def setUp(self):
        self.trader = AutoTrader()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.trader.open_positions_file = str(root / 'open-positions.json')
        self.trader.closed_trades_file = str(root / 'closed-trades.json')
        self.trader.staged_reductions_file = str(root / 'staged-reductions.json')
        self.trader.us_entry_state_file = str(root / 'us-entry-timing.json')
        self.trader.hk_entry_state_file = str(root / 'hk-entry-timing.json')
        Path(self.trader.open_positions_file).write_text('[]', encoding='utf-8')
        Path(self.trader.closed_trades_file).write_text('[]', encoding='utf-8')
        Path(self.trader.staged_reductions_file).write_text('{}', encoding='utf-8')

    def test_us_combined_score_uses_first_layer_90_percent(self):
        combine = SCANNER_MODULE.combine_layer_scores
        self.assertEqual(combine(85, 67), 83)
        self.assertEqual(combine(90, 100), 91)
        self.assertEqual(combine(65, 50), 64)

    def test_hk_combined_score_uses_first_layer_90_percent(self):
        combine = HK_SCANNER_MODULE.combine_layer_scores
        self.assertEqual(combine(85, 67), 83)
        self.assertEqual(combine(90, 100), 91)
        self.assertEqual(combine(65, 50), 64)

    def test_hk_five_source_fields_and_coverage_fallback(self):
        base_fs = {
            'score_news': 20, 'score_announce': 15, 'score_community': 12,
            'score_institution': 18, 'score_capital': 5, 'score_total': 70,
            'available_news': True, 'available_announce': True,
            'available_community': True, 'available_institution': True,
            'available_capital': True, 'available_count': 5,
            'evidence_news': 'n', 'evidence_announce': 'a',
            'evidence_community': 'c', 'evidence_institution': 'i',
            'evidence_capital': 'f', 'raw': {},
        }
        real = {'base_score': 80, 'first_layer_score': 80}
        HKScanner._apply_five_source_score(real, base_fs)
        self.assertEqual(real['five_source_effective_score'], 70)
        self.assertEqual(real['combined_base_score'], 79)
        self.assertEqual(real['five_source_available_count'], 5)
        self.assertTrue(real['scoring_mode'].startswith('first90_five10:five_source_real'))

        low_coverage_fs = dict(base_fs, available_count=2)
        fallback = {'base_score': 80, 'first_layer_score': 80}
        HKScanner._apply_five_source_score(fallback, low_coverage_fs)
        self.assertEqual(fallback['five_source_effective_score'], 64)
        self.assertEqual(fallback['combined_base_score'], 78)
        self.assertIn('legacy_discounted', fallback['scoring_mode'])

    def test_hk_save_results_passes_combined_score_to_llm(self):
        scanner = object.__new__(HKScanner)
        scanner.data_source = 'test'
        scanner.news_sentiment = {}
        scanner.market_sentiment = {}
        scanner.hsi = ['00700']
        scanner.hstech = []
        scanner.stocks = ['00700']
        scanner.get_buying_power = lambda: 100_000
        scanner.execute_trades_directly = Mock()
        candidate = {
            'symbol': 'HK.00700', 'name': '腾讯控股', 'base_score': 80,
            'price': 500.0, 'change_pct': 2.0, 'index': 'HSI',
        }
        fs = {
            'score_news': 20, 'score_announce': 15, 'score_community': 12,
            'score_institution': 18, 'score_capital': 5, 'score_total': 70,
            'available_news': True, 'available_announce': True,
            'available_community': True, 'available_institution': True,
            'available_capital': True, 'available_count': 5,
            'evidence_news': 'n', 'evidence_announce': 'a',
            'evidence_community': 'c', 'evidence_institution': 'i',
            'evidence_capital': 'f', 'raw': {},
        }
        llm_inputs = []

        def fake_llm(symbol, market_data):
            llm_inputs.append(market_data)
            return {
                'final_score': 79, 'score_adjust': 0,
                'llm_reason': '测试通过', 'passed': True,
                'llm_status': 'parsed',
            }

        temp_data = Path(self.temp_dir.name)
        fake_tech = Mock()
        fake_tech.get_llm_snapshot.return_value = {
            'rsi': 50.0,
            'macd_state': '多头',
            'kline_volume_ratio': 1.0,
        }
        with patch.object(HK_SCANNER_MODULE, 'DATA_DIR', temp_data), patch(
            'technical_indicators_hk.HKTechIndicators', return_value=fake_tech,
        ), patch(
            'four_source_scorer.score_all', return_value=fs,
        ), patch(
            'llm_stock_analyzer.analyze_stock', side_effect=fake_llm,
        ):
            scanner.save_results([candidate])

        saved = json.loads((temp_data / 'hk-opportunities.json').read_text())
        self.assertEqual(llm_inputs[0]['base_score'], 79)
        self.assertEqual(saved['opportunities'][0]['combined_base_score'], 79)
        self.assertEqual(saved['opportunities'][0]['five_source_available_count'], 5)
        scanner.execute_trades_directly.assert_called_once()

    def test_hk_llm_prompt_includes_five_source_without_weight_formula(self):
        analyzer = object.__new__(LLMStockAnalyzer)
        prompt = analyzer._build_prompt('HK.00700', {
            'market': 'hk', 'base_score': 79, 'price': 500,
            'change_pct': 1.2, 'score_news': 13, 'score_announce': 0,
            'score_community': 17, 'score_institution': 10,
            'score_capital': 7, 'available_news': True,
            'available_announce': False, 'available_community': True,
            'available_institution': True, 'available_capital': True,
            'evidence_news': '资讯证据', 'evidence_community': '社区证据',
            'evidence_institution': '机构证据', 'evidence_capital': '资金证据',
        })
        self.assertIn('港股综合基础评分: 79分', prompt)
        self.assertIn('港股五源真实证据', prompt)
        self.assertIn('国际资讯: 资讯证据', prompt)
        self.assertIn('官方公告: 公告未覆盖', prompt)
        self.assertNotIn('港股未启用五源第二层', prompt)
        self.assertNotIn('第一层79×90%', prompt)

    def test_us_layer2_candidate_threshold_is_65(self):
        scanner = object.__new__(USScanner)
        scanner.news_sentiment = {}
        scanner.sp500 = []
        scanner.nasdaq = []
        scanner._layer1_drop_stats = {'dropped': 0, 'near_miss': []}
        scanner._drop_stats_lock = threading.Lock()
        scanner.calculate_score = lambda *args: 64
        self.assertIsNone(
            scanner._build_quote_candidate('TEST', 100, 99, 1, 'test')
        )

        scanner.calculate_score = lambda *args: 65
        candidate = scanner._build_quote_candidate('TEST', 100, 99, 1, 'test')
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate['score'], 65)

    def test_us_score_position_bands_include_75_to_79(self):
        expected = {
            74: 0.0,
            75: 0.06,
            76: 0.065,
            79: 0.08,
            80: 0.08,
            84: 0.10,
            85: 0.10,
            89: 0.11,
            90: 0.11,
            94: 0.12,
            95: 0.12,
        }
        for score, position in expected.items():
            with self.subTest(score=score):
                self.assertAlmostEqual(
                    self.trader.get_score_based_position(score, 'us'),
                    position,
                )

    def test_hk_score_position_bands_include_75_to_79(self):
        expected = {
            74: 0.0,
            75: 0.02,
            79: 0.02,
            80: 0.03,
            85: 0.04,
            90: 0.05,
            95: 0.06,
        }
        for score, position in expected.items():
            with self.subTest(score=score):
                self.assertAlmostEqual(
                    self.trader.get_score_based_position(score, 'hk'),
                    position,
                )

    def _us_technical_result(self, score, trend, rsi, volume, macd):
        indicator = object.__new__(USTechIndicators)
        indicator.check_trend = lambda symbol: {
            'trend': 'up' if trend else 'down',
            'above_ma20': bool(trend),
            'ma20': 100.0,
            'ma50': 95.0 if trend else 105.0,
            'price': 102.0,
        }
        indicator.check_rsi = lambda symbol: 55.0 if rsi else 70.0
        indicator.check_volume = lambda symbol: 2.0 if volume else 1.0
        indicator.check_macd_death_cross = lambda symbol: not macd
        return indicator.get_entry_signals('TEST', entry_score=score)

    def test_us_technical_condition_score_gradient(self):
        cases = (
            (90, (False, False, False, True), True, 1),
            (89, (False, False, False, True), False, 2),
            (89, (False, True, False, True), True, 2),
            (84, (True, True, False, False), False, 3),
            (84, (True, True, False, True), True, 3),
            (79, (True, True, True, False), False, 4),
            (79, (True, True, True, True), True, 4),
            (74, (True, True, True, True), False, 5),
        )
        for score, conditions, expected, required in cases:
            with self.subTest(score=score, conditions=conditions):
                result = self._us_technical_result(score, *conditions)
                self.assertEqual(result['can_enter'], expected)
                self.assertEqual(result['details']['required_conditions'], required)
                self.assertEqual(
                    result['details']['matched_conditions'],
                    sum(conditions),
                )

    def test_us_volume_requires_1_8_times_at_score_75(self):
        indicator = object.__new__(USTechIndicators)
        indicator.check_trend = lambda symbol: {
            'trend': 'up', 'above_ma20': True,
            'ma20': 100.0, 'ma50': 95.0, 'price': 102.0,
        }
        indicator.check_rsi = lambda symbol: 55.0
        indicator.check_macd_death_cross = lambda symbol: False

        indicator.check_volume = lambda symbol: 1.79
        rejected = indicator.get_entry_signals('TEST', entry_score=75)
        indicator.check_volume = lambda symbol: 1.8
        accepted = indicator.get_entry_signals('TEST', entry_score=75)

        self.assertFalse(rejected['can_enter'])
        self.assertTrue(accepted['can_enter'])

    def _hk_technical_result(self, score, trend, rsi, volume, enhance):
        indicator = object.__new__(HKTechIndicators)
        indicator.check_ma_trend = lambda symbol: {'can_entry': trend}
        indicator.check_rsi_entry = lambda symbol: {
            'can_entry': rsi, 'rsi': 50.0 if rsi else 75.0,
        }
        indicator.check_volume = lambda symbol: {
            'meets_condition': volume, 'ratio': 2.0 if volume else 1.0,
        }
        indicator.check_enhance_signals = lambda symbol: {
            'meets_condition': enhance,
            'signals': ['突破高点'] if enhance else [],
        }
        return indicator.get_entry_signals('HK.TEST', entry_score=score)

    def test_hk_technical_condition_score_gradient(self):
        cases = (
            (90, (False, False, False, True), True, 1),
            (89, (False, False, False, True), False, 2),
            (89, (False, True, False, True), True, 2),
            (84, (True, True, False, False), False, 3),
            (84, (True, True, False, True), True, 3),
            (79, (True, True, True, False), False, 4),
            (79, (True, True, True, True), True, 4),
            (74, (True, True, True, True), False, 5),
        )
        for score, conditions, expected, required in cases:
            with self.subTest(score=score, conditions=conditions):
                result = self._hk_technical_result(score, *conditions)
                self.assertEqual(result['can_enter'], expected)
                self.assertEqual(result['details']['required_conditions'], required)
                self.assertEqual(
                    result['details']['matched_conditions'],
                    sum(conditions),
                )

    def test_prepare_buy_order_accepts_score_75(self):
        self.trader.get_market_sentiment_multiplier = lambda: (
            1.0,
            70.0,
            'test',
            1.0,
            {'sentiment_score': 70},
        )
        account = {
            'total_assets': 1_000_000,
            'cash': 1_000_000,
            'market_val': 0,
            'positions': [],
        }

        result = self.trader.prepare_buy_order(
            account,
            'US.TEST',
            100,
            75,
            market='us',
        )

        self.assertTrue(result['can_buy'])
        self.assertEqual(result['quantity'], 600)
        self.assertAlmostEqual(result['base_pct'], 0.06)
        self.assertAlmostEqual(result['order_value'], 60_000)

    def test_prepare_buy_order_rejects_below_threshold_with_clear_reason(self):
        account = {
            'total_assets': 1_000_000,
            'cash': 1_000_000,
            'market_val': 0,
            'positions': [],
        }

        result = self.trader.prepare_buy_order(
            account,
            'US.TEST',
            100,
            74,
            market='us',
        )

        self.assertFalse(result['can_buy'])
        self.assertIn('低于交易门槛75', result['reason'])

    def _mock_entry_snapshot(self, **overrides):
        value = {
            'current_price': 100.0,
            'ask_price': 100.01,
            'day_high': 101.0,
            'near_high_distance_pct': 0.99,
            'vwap': 99.8,
            'ema9': 99.9,
            'support': 99.9,
            'pullback_ready': False,
            'breakout_ready': False,
            'breakout_level': 100.0,
            'breakout_volume_ratio': 1.0,
            'price_spread': 0.01,
            'completed_bars': 20,
            'quote_time': '2026-09-21 10:00:00',
        }
        value.update(overrides)
        self.trader._get_intraday_entry_snapshot = Mock(return_value=(value, ''))
        return value

    def test_us_entry_timing_builds_passive_day_limit_without_expiry(self):
        now = datetime(2026, 9, 21, 22, 0)
        self._mock_entry_snapshot()

        result = self.trader.evaluate_us_entry_timing(
            'US.TEST', 100, opp={'timestamp': now.isoformat(), 'final_score': 88}, now=now
        )

        self.assertTrue(result['ready'])
        self.assertEqual(result['setup'], 'DAY被动限价等待回踩')
        self.assertAlmostEqual(result['limit_price'], 99.7)
        self.assertIsNone(result['order_expires_at'])
        self.assertIn('挂DAY被动限价', result['reason'])

    def test_us_intraday_snapshot_builds_vwap_from_futu_minutes(self):
        self.trader.quote_ctx = Mock()
        self.trader.quote_ctx.get_market_snapshot.return_value = (0, pd.DataFrame([{
            'last_price': 100.2,
            'ask_price': 100.21,
            'high_price': 101.0,
            'price_spread': 0.01,
            'update_time': '2026-09-21 09:40:30',
        }]))
        self.trader.quote_ctx.subscribe.return_value = (0, None)
        closes = [100.0, 100.1, 100.2, 100.1, 100.0, 99.9, 100.0, 100.1, 100.15, 100.2]
        volumes = [1000] * len(closes)
        bars = pd.DataFrame({
            'time_key': pd.date_range('2026-09-21 09:30', periods=len(closes), freq='min').astype(str),
            'open': closes,
            'close': closes,
            'high': [value + 0.1 for value in closes],
            'low': [value - 0.1 for value in closes],
            'volume': volumes,
            'turnover': [price * volume for price, volume in zip(closes, volumes)],
        })
        self.trader.quote_ctx.get_cur_kline.return_value = (0, bars)

        snapshot, error = self.trader._get_us_intraday_entry_snapshot(
            'US.TEST',
            now_et=datetime(2026, 9, 21, 9, 41, 0, tzinfo=AUTO_TRADER.ZoneInfo('America/New_York')),
        )

        self.assertEqual(error, '')
        self.assertEqual(snapshot['completed_bars'], 10)
        self.assertAlmostEqual(snapshot['vwap'], sum(closes) / len(closes))
        self.assertGreater(snapshot['ema9'], 0)
        self.trader.quote_ctx.unsubscribe.assert_called_once()

    def test_us_entry_timing_blocks_near_high_without_breakout(self):
        now = datetime(2026, 9, 21, 22, 0)
        self.trader.us_config['entry_timing'] = {
            **self.trader.us_config['entry_timing'], 'mode': 'confirmed_entry'
        }
        self._mock_entry_snapshot(
            pullback_ready=True,
            near_high_distance_pct=0.2,
            day_high=100.2,
        )

        result = self.trader.evaluate_us_entry_timing(
            'US.TEST', 100, opp={'timestamp': now.isoformat(), 'final_score': 88}, now=now
        )

        self.assertFalse(result['ready'])
        self.assertIn('距日内高点', result['reason'])

    def test_us_entry_timing_allows_confirmed_breakout_near_high(self):
        now = datetime(2026, 9, 21, 22, 0)
        self.trader.us_config['entry_timing'] = {
            **self.trader.us_config['entry_timing'], 'mode': 'confirmed_entry'
        }
        self._mock_entry_snapshot(
            breakout_ready=True,
            breakout_level=99.8,
            breakout_volume_ratio=1.5,
            near_high_distance_pct=0.1,
        )

        result = self.trader.evaluate_us_entry_timing(
            'US.TEST', 100, opp={'timestamp': now.isoformat(), 'final_score': 90}, now=now
        )

        self.assertTrue(result['ready'])
        self.assertEqual(result['setup'], '放量突破确认')

    def test_hk_entry_timing_uses_hk_state_and_market_snapshot(self):
        now = datetime(2026, 9, 21, 10, 0)
        self._mock_entry_snapshot(pullback_ready=True)

        result = self.trader.evaluate_entry_timing(
            'HK.00700', 500,
            market='hk',
            opp={'timestamp': now.isoformat(), 'final_score': 88},
            now=now,
        )

        self.assertTrue(result['ready'])
        self.assertEqual(result['setup'], '回踩企稳')
        self.assertTrue(Path(self.trader.hk_entry_state_file).exists())
        self.assertFalse(Path(self.trader.us_entry_state_file).exists())
        kwargs = self.trader._get_intraday_entry_snapshot.call_args.kwargs
        self.assertEqual(kwargs['market'], 'hk')

    def test_us_entry_timing_blocks_price_chasing(self):
        now = datetime(2026, 9, 21, 22, 0)
        self.trader.us_config['entry_timing'] = {
            **self.trader.us_config['entry_timing'], 'mode': 'confirmed_entry'
        }
        self._mock_entry_snapshot(
            current_price=102.0,
            ask_price=102.01,
            day_high=103.0,
            pullback_ready=True,
        )

        result = self.trader.evaluate_us_entry_timing(
            'US.TEST', 100, opp={'timestamp': now.isoformat(), 'final_score': 95}, now=now
        )

        self.assertFalse(result['ready'])
        self.assertIn('追高上限', result['reason'])

    def test_us_entry_timing_expires_after_thirty_minutes(self):
        start = datetime(2026, 9, 21, 22, 0)
        self.trader.us_config['entry_timing'] = {
            **self.trader.us_config['entry_timing'], 'mode': 'confirmed_entry'
        }
        self._mock_entry_snapshot()
        opp = {'timestamp': start.isoformat(), 'final_score': 88}

        first = self.trader.evaluate_us_entry_timing('US.TEST', 100, opp=opp, now=start)
        expired = self.trader.evaluate_us_entry_timing(
            'US.TEST', 100, opp=opp, now=start + timedelta(minutes=31)
        )

        self.assertFalse(first['ready'])
        self.assertFalse(expired['ready'])
        self.assertIn('本次放弃', expired['reason'])
        self.assertEqual(self.trader._get_intraday_entry_snapshot.call_count, 1)

    def test_prepare_buy_order_uses_live_entry_price(self):
        self.trader.get_market_sentiment_multiplier = lambda: (
            1.0, 70.0, 'test', 1.0, {'sentiment_score': 70},
        )
        self.trader.evaluate_entry_timing = Mock(return_value={
            'ready': True,
            'current_price': 110.0,
            'limit_price': 110.2,
            'signal_id': 'TEST|signal',
            'order_expires_at': '2026-09-21T22:02:00',
            'setup': '回踩企稳',
        })
        account = {
            'total_assets': 1_000_000,
            'cash': 1_000_000,
            'market_val': 0,
            'positions': [],
        }

        result = self.trader.prepare_buy_order(
            account, 'US.TEST', 100, 75, market='us', opp={'timestamp': 'now'}
        )

        self.assertTrue(result['can_buy'])
        self.assertEqual(result['quantity'], 545)
        self.assertEqual(result['execution_price'], 110.0)
        self.assertEqual(result['limit_price'], 110.2)
        self.assertAlmostEqual(result['order_value'], 59_950)

    def test_prepare_hk_buy_order_uses_entry_timing_and_board_lot(self):
        self.trader.evaluate_entry_timing = Mock(return_value={
            'ready': True,
            'current_price': 110.0,
            'limit_price': 110.2,
            'signal_id': 'hk|TEST|signal',
            'order_expires_at': '2026-09-21T10:02:00',
            'setup': '回踩企稳',
        })
        account = {
            'total_assets': 1_000_000,
            'cash': 1_000_000,
            'market_val': 0,
            'positions': [],
        }

        result = self.trader.prepare_buy_order(
            account, 'HK.00700', 100, 80,
            market='hk', lot_size=100, opp={'timestamp': 'now'},
        )

        self.assertTrue(result['can_buy'])
        self.assertEqual(result['quantity'] % 100, 0)
        self.assertEqual(result['execution_price'], 110.0)
        self.assertEqual(result['limit_price'], 110.2)
        self.trader.evaluate_entry_timing.assert_called_once_with(
            'HK.00700', 100.0, market='hk', opp={'timestamp': 'now'}
        )

    def test_place_order_uses_protected_limit_for_us_buy(self):
        self.trader.trade_ctx = Mock()
        self.trader.trade_ctx.position_list_query.return_value = (
            0, pd.DataFrame(columns=['qty'])
        )
        self.trader.trade_ctx.order_list_query.return_value = (
            0, pd.DataFrame(columns=['order_status'])
        )
        self.trader.trade_ctx.place_order.return_value = (
            0, pd.DataFrame([{'order_id': 'test-order'}])
        )

        success, order_id = self.trader.place_order(
            'US.TEST', 'BUY', 100, market='us', limit_price=100.25
        )

        self.assertTrue(success)
        self.assertEqual(order_id, 'test-order')
        kwargs = self.trader.trade_ctx.place_order.call_args.kwargs
        self.assertEqual(kwargs['price'], 100.25)
        self.assertEqual(kwargs['order_type'], AUTO_TRADER.OrderType.NORMAL)
        self.assertEqual(kwargs['time_in_force'], AUTO_TRADER.TimeInForce.DAY)

    def test_place_order_uses_protected_limit_for_hk_buy(self):
        self.trader.hk_trade_ctx = Mock()
        self.trader.hk_trade_ctx.position_list_query.return_value = (
            0, pd.DataFrame(columns=['qty'])
        )
        self.trader.hk_trade_ctx.order_list_query.return_value = (
            0, pd.DataFrame(columns=['order_status'])
        )
        self.trader.hk_trade_ctx.place_order.return_value = (
            0, pd.DataFrame([{'order_id': 'hk-test-order'}])
        )

        success, order_id = self.trader.place_order(
            'HK.00700', 'BUY', 100, market='hk', limit_price=500.2
        )

        self.assertTrue(success)
        self.assertEqual(order_id, 'hk-test-order')
        kwargs = self.trader.hk_trade_ctx.place_order.call_args.kwargs
        self.assertEqual(kwargs['price'], 500.2)
        self.assertEqual(kwargs['order_type'], AUTO_TRADER.OrderType.NORMAL)
        self.assertEqual(kwargs['time_in_force'], AUTO_TRADER.TimeInForce.DAY)

    def test_should_trade_ignores_zero_quantity_futu_rows(self):
        allowed, reason = self.trader.should_trade(
            'US.ZERO',
            [{'symbol': 'US.ZERO', 'shares': 0}],
            [],
        )

        self.assertTrue(allowed)
        self.assertEqual(reason, '可以交易')

    def test_reconcile_open_positions_removes_closed_and_updates_partial(self):
        Path(self.trader.open_positions_file).write_text(json.dumps([
            {'symbol': 'US.CLOSED', 'market': 'us', 'shares': 100},
            {'symbol': 'US.PART', 'market': 'us', 'shares': 100},
            {'symbol': 'HK.00700', 'market': 'hk', 'shares': 200},
        ]), encoding='utf-8')
        Path(self.trader.staged_reductions_file).write_text(json.dumps({
            'US.CLOSED': {'status': 'stage1_done'},
        }), encoding='utf-8')

        result = self.trader.reconcile_open_positions(
            'us',
            [{'symbol': 'US.PART', 'shares': 40}],
        )

        remaining = json.loads(
            Path(self.trader.open_positions_file).read_text(encoding='utf-8')
        )
        staged = json.loads(
            Path(self.trader.staged_reductions_file).read_text(encoding='utf-8')
        )
        self.assertEqual(result['removed'], ['US.CLOSED'])
        self.assertEqual(result['updated'], ['US.PART'])
        self.assertEqual(
            [(item['symbol'], item['shares']) for item in remaining],
            [('US.PART', 40), ('HK.00700', 200)],
        )
        self.assertNotIn('US.CLOSED', staged)

    def test_pending_sell_fill_triggers_futu_position_sync_once(self):
        pending_path = Path(self.temp_dir.name) / 'pending-sell-orders.json'
        pending_path.write_text(json.dumps({
            '12345': {
                'order_id': '12345',
                'symbol': 'US.TEST',
                'market': 'us',
                'quantity': 50,
                'entry_price': 100,
                'reason': '测试止盈',
                'created_at': '2026-07-15T01:00:00',
            },
        }), encoding='utf-8')
        Path(self.trader.open_positions_file).write_text(json.dumps([
            {
                'symbol': 'US.TEST',
                'market': 'us',
                'shares': 50,
                'entry_score': 80,
                'entry_reasons': ['测试'],
            },
        ]), encoding='utf-8')

        context = Mock()
        context.order_list_query.return_value = (
            AUTO_TRADER.RET_OK,
            pd.DataFrame([{
                'order_id': '12345',
                'order_status': 'FILLED_ALL',
                'dealt_avg_price': 110.0,
                'dealt_qty': 50,
            }]),
        )
        self.trader.trade_ctx = context
        self.trader._sync_open_positions_from_futu = Mock(return_value=True)

        pusher = Mock()
        with patch.object(AUTO_TRADER, 'DATA_DIR', Path(self.temp_dir.name)), patch(
            'feishu_pusher.FeishuPusher',
            return_value=pusher,
        ):
            self.trader.reconcile_pending_sells()

        self.trader._sync_open_positions_from_futu.assert_called_once_with('us')
        self.assertEqual(
            json.loads(pending_path.read_text(encoding='utf-8')),
            {},
        )
        closed = json.loads(
            Path(self.trader.closed_trades_file).read_text(encoding='utf-8')
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]['order_id'], '12345')
        pusher.send_sell_notification.assert_called_once()

    def test_pending_buy_fill_creates_risk_record_and_notification(self):
        pending_path = Path(self.temp_dir.name) / 'pending-buy-orders.json'
        pending_path.write_text(json.dumps({
            '54321': {
                'order_id': '54321',
                'symbol': 'US.NEW',
                'market': 'us',
                'quantity': 50,
                'score': 78,
                'reasons': ['测试买入'],
                'created_at': '2026-07-17T11:54:26',
                'signal_price': 10.0,
                'limit_price': 10.3,
                'entry_setup': '回踩企稳',
            },
        }), encoding='utf-8')
        context = Mock()
        context.order_list_query.return_value = (
            AUTO_TRADER.RET_OK,
            pd.DataFrame([{
                'order_id': '54321',
                'order_status': 'FILLED_ALL',
                'dealt_avg_price': 10.25,
                'dealt_qty': 50,
            }]),
        )
        self.trader.trade_ctx = context
        self.trader._calc_risk_targets = Mock(return_value={
            'atr_stop': 9.2, 'tp_trend': 12.0, 'rule_note': '测试风控',
        })
        self.trader.find_opportunity = Mock(return_value={})
        self.trader.build_dynamic_signal_details = Mock(return_value={
            'score_total': 78,
            'score_news': 20,
            'score_announce': 15,
            'score_community': 15,
            'score_institution': 18,
            'score_capital': 10,
            'signal_type': '测试信号',
            'llm_conclusion': '测试结论',
        })
        pusher = Mock()
        with patch.object(AUTO_TRADER, 'DATA_DIR', Path(self.temp_dir.name)), patch(
            'feishu_pusher.FeishuPusher',
            return_value=pusher,
        ):
            self.trader.reconcile_pending_buys()

        records = json.loads(
            Path(self.trader.open_positions_file).read_text(encoding='utf-8')
        )
        self.assertEqual(json.loads(pending_path.read_text(encoding='utf-8')), {})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['entry_price'], 10.25)
        self.assertEqual(records[0]['atr_stop'], 9.2)
        pusher.send_buy_notification.assert_called_once()
        notification = pusher.send_buy_notification.call_args.kwargs
        self.assertEqual(notification['signal_price'], 10.0)
        self.assertEqual(notification['protected_limit'], 10.3)
        self.assertEqual(notification['entry_setup'], '回踩企稳')

    def test_pending_day_buy_is_not_cancelled_without_local_expiry(self):
        pending_path = Path(self.temp_dir.name) / 'pending-buy-orders.json'
        pending_path.write_text(json.dumps({
            'DAY-ORDER': {
                'order_id': 'DAY-ORDER',
                'symbol': 'US.TEST',
                'market': 'us',
                'quantity': 10,
                'score': 88,
                'reasons': ['测试DAY挂单'],
                'created_at': '2026-09-22T00:00:00',
                'expires_at': None,
            },
        }), encoding='utf-8')
        context = Mock()
        context.order_list_query.return_value = (
            AUTO_TRADER.RET_OK,
            pd.DataFrame([{
                'order_id': 'DAY-ORDER',
                'order_status': 'SUBMITTED',
                'dealt_avg_price': 0,
                'dealt_qty': 0,
            }]),
        )
        self.trader.trade_ctx = context

        with patch.object(AUTO_TRADER, 'DATA_DIR', Path(self.temp_dir.name)):
            self.trader.reconcile_pending_buys()

        remaining = json.loads(pending_path.read_text(encoding='utf-8'))
        self.assertIn('DAY-ORDER', remaining)
        context.modify_order.assert_not_called()


if __name__ == '__main__':
    unittest.main()
