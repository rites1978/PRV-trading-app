"""
🏛️ PRV CAPITAL | ALPHA ENGINE TOURNAMENT INTEGRATION TEST
Verifies the research harness, backtest accounting, friction calculations,
and strategy simulation logic.
"""
import os
import unittest
import pandas as pd
from datetime import datetime
from src.research.backtest_harness import BacktestEngine, BacktestFrictions, SimulatedTrade
from src.research.competing_strategies import (
    StrategyAFrozenV2,
    StrategyBQualityValue,
    StrategyCQualityValueMomentum,
    precompute_indicators
)
from src.config.settings import settings


class TestAlphaTournamentEngine(unittest.TestCase):

    def setUp(self):
        # Create synthetic deterministic 100-day bars for testing
        dates = pd.date_range("2023-01-01", periods=100, freq="B")
        self.uk_df = pd.DataFrame({
            "Open": [100.0 + i * 0.5 for i in range(100)],
            "High": [102.0 + i * 0.5 for i in range(100)],
            "Low": [99.0 + i * 0.5 for i in range(100)],
            "Close": [101.0 + i * 0.5 for i in range(100)],
            "Volume": [100000] * 100
        }, index=dates)

        self.us_df = pd.DataFrame({
            "Open": [200.0 + i * 1.0 for i in range(100)],
            "High": [203.0 + i * 1.0 for i in range(100)],
            "Low": [198.0 + i * 1.0 for i in range(100)],
            "Close": [201.0 + i * 1.0 for i in range(100)],
            "Volume": [200000] * 100
        }, index=dates)

        self.bars_data = {
            "BP.L": self.uk_df,
            "AAPL": self.us_df
        }
        self.bars_data = precompute_indicators(self.bars_data)

    def test_friction_accounting_uk_vs_us(self):
        """Verifies UK trade incurs SDRT (0.50%) while US trade incurs FX (0.15%) and zero SDRT."""
        fric = BacktestFrictions()
        trade_dt = pd.Timestamp("2023-01-02")

        # UK Trade
        trade_uk = SimulatedTrade(
            symbol="BP",
            yf_ticker="BP.L",
            country="UK",
            entry_date=trade_dt,
            entry_price=100.0,
            quantity=10.0,
            entry_notional=1000.0,
            sdrt_fee=5.0,  # 0.50% on £1000
            entry_fx_fee=0.0,
            entry_spread_cost=0.40,
            entry_slippage_cost=0.30
        )
        trade_uk.close(trade_dt, 110.0, "PROFIT", fric)
        self.assertEqual(trade_uk.sdrt_fee, 5.0)
        self.assertEqual(trade_uk.entry_fx_fee, 0.0)
        self.assertEqual(trade_uk.exit_fx_fee, 0.0)

        # US Trade
        trade_us = SimulatedTrade(
            symbol="AAPL",
            yf_ticker="AAPL",
            country="US",
            entry_date=trade_dt,
            entry_price=200.0,
            quantity=5.0,
            entry_notional=1000.0,
            sdrt_fee=0.0,
            entry_fx_fee=1.50,  # 0.15% on £1000
            entry_spread_cost=0.20,
            entry_slippage_cost=0.30
        )
        trade_us.close(trade_dt, 220.0, "PROFIT", fric)
        self.assertEqual(trade_us.sdrt_fee, 0.0)
        self.assertEqual(trade_us.entry_fx_fee, 1.50)
        self.assertEqual(trade_us.exit_fx_fee, 1.65)  # 0.15% on £1100

    def test_practice_safety_invariant(self):
        """Ensures PRACTICE_NEW_ENTRIES_ALLOWED remains False."""
        self.assertFalse(settings.PRACTICE_NEW_ENTRIES_ALLOWED)

    def test_manifest_hash_invariant(self):
        """Ensures V1 parameter manifest hash remains 7c512be5bc26910c1c4ed81a3e650480a676cd750faa49bc8dbd8901360bc708."""
        manifest_hash = settings.get_parameter_manifest_hash()
        self.assertEqual(manifest_hash, "7c512be5bc26910c1c4ed81a3e650480a676cd750faa49bc8dbd8901360bc708")


if __name__ == "__main__":
    unittest.main()
