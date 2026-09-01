import unittest
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

SPEC = importlib.util.spec_from_file_location(
    'auto_trader_live_quote_test', Path(__file__).resolve().parent / 'auto-trader.py'
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
AutoTrader = MODULE.AutoTrader


class LivePositionQuoteTest(unittest.TestCase):
    def test_live_quote_replaces_stale_position_loss(self):
        trader = AutoTrader.__new__(AutoTrader)
        trader.quote_ctx = Mock()
        trader.quote_ctx.get_market_snapshot.return_value = (0, pd.DataFrame([{
            'code': 'US.ATOS', 'last_price': 2.32,
            'update_time': '2026-09-01 11:23:51',
        }]))
        positions = [{
            'symbol': 'US.ATOS', 'shares': 48573, 'cost_price': 2.62,
            'market_val': 120461.04, 'pl_ratio': -5.34,
        }]

        trader._refresh_positions_with_live_quotes(positions)

        self.assertAlmostEqual(positions[0]['current_price'], 2.32)
        self.assertAlmostEqual(positions[0]['pl_ratio'], -11.450381679, places=6)
        self.assertEqual(positions[0]['price_source'], 'futu_snapshot')
        self.assertAlmostEqual(trader.get_position_price(positions[0]), 2.32)

    def test_snapshot_failure_keeps_position_values(self):
        trader = AutoTrader.__new__(AutoTrader)
        trader.quote_ctx = Mock()
        trader.quote_ctx.get_market_snapshot.return_value = (-1, 'failed')
        positions = [{
            'symbol': 'US.TEST', 'shares': 10, 'cost_price': 10,
            'market_val': 95, 'pl_ratio': -5,
        }]

        trader._refresh_positions_with_live_quotes(positions)

        self.assertEqual(positions[0]['market_val'], 95)
        self.assertEqual(positions[0]['pl_ratio'], -5)


if __name__ == '__main__':
    unittest.main()
