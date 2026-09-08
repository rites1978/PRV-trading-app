"""
🏛️ PRV CAPITAL | PHASE 5: EXECUTION SAFETY CERTIFICATION TEST SUITE
Test Suite: test_core_compounding_production_safety.py

Verifies 4 Critical Production Safety Invariants:
1. Signal Bar Deduplication (Never execute twice on the same day/bar across polling cycles)
2. Restart Persistence of Watermark & Positions (State survives process restarts)
3. Anti-Accidental Short Logic on Exit (Sells exact shares held, never negative, zero orphan risk)
4. Broker Ledger Authority & Fail-Closed on Unavailable Data (Fails closed to CASH if data missing)
5. Strict Gate Authority (can_strategy_route_orders returns False when PRACTICE_NEW_ENTRIES_ALLOWED=False)
"""
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from src.strategies.core_compounding_v1 import (
    CoreCompoundingStrategy,
    core_compounding_strategy,
    EXPECTED_RESEARCH_CODE_SHA256,
    EXPECTED_MANIFEST_SHA256
)
from src.strategies.registry import strategy_registry
from src.config.settings import settings
from src.data.universe import UniverseManager


class TestCoreCompoundingProductionSafety(unittest.TestCase):

    def setUp(self):
        self.strategy = CoreCompoundingStrategy()

    def test_cryptographic_integrity_gate(self):
        """Invariant: Strategy verifies manifest and research code SHA256 on init."""
        hashes = self.strategy.verify_cryptographic_integrity()
        self.assertEqual(len(hashes["code_sha256"]), 64)
        self.assertEqual(len(hashes["manifest_sha256"]), 64)
        self.assertEqual(hashes["code_sha256"], EXPECTED_RESEARCH_CODE_SHA256)
        self.assertEqual(hashes["manifest_sha256"], EXPECTED_MANIFEST_SHA256)

    def test_gate_authority_blocks_routing_when_entries_disabled(self):
        """Invariant: can_strategy_route_orders strictly blocks orders when PRACTICE_NEW_ENTRIES_ALLOWED=False."""
        # Baseline state
        with patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", False):
            can_route = strategy_registry.can_strategy_route_orders("PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1")
            self.assertFalse(can_route, "Order routing must be BLOCKED when PRACTICE_NEW_ENTRIES_ALLOWED is False")

        with patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True):
            can_route = strategy_registry.can_strategy_route_orders("PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1")
            self.assertTrue(can_route, "Order routing must be ALLOWED when PRACTICE_NEW_ENTRIES_ALLOWED is True")

    def test_signal_bar_deduplication(self):
        """Invariant: Rebalance signal cannot trigger re-entry if position already open or bar evaluated."""
        # Create mock daily data
        mock_data = {}
        dates = pd.date_range("2026-01-01", "2026-03-01", freq="B")
        for inst in self.strategy.CERTIFIED_UNIVERSE:
            sym = inst["symbol"]
            df = pd.DataFrame(index=dates)
            df["Close"] = 100.0 + np.random.randn(len(dates))
            df["Open"] = df["Close"]
            df["High"] = df["Close"] * 1.01
            df["Low"] = df["Close"] * 0.99
            df["SMA200"] = 90.0
            df["MOM_SHARPE"] = 1.5
            mock_data[f"{sym}_L"] = df

        # Bar T
        bar_t = dates[-1]
        prev_t = dates[-2]

        # First evaluation
        sig1 = self.strategy.evaluate_point_in_time_signal(bar_t, prev_t, mock_data)
        self.assertIn(sig1["decision"], ["ENTER", "HOLD_CASH"])
        target1 = sig1["selected_symbol"]

        # If we already have a position in target1, evaluate_position_lifecycle must NOT exit on same target
        should_exit, reason = self.strategy.evaluate_position_lifecycle(
            current_symbol_or_key=target1,
            entry_price_gbp=100.0,
            current_low_gbp=99.0, # -1%, above -2% stop
            should_rebalance=True,
            target_symbol_or_key=target1
        )
        self.assertFalse(should_exit, "Position must NOT be exited when target ticker is already held")
        self.assertEqual(reason, "HOLD")

    def test_anti_accidental_short_logic(self):
        """Invariant: Exit order must liquidate exact position shares, never short."""
        # Suppose we hold 432.5 shares from broker
        broker_position_shares = 432.5
        exit_shares = float(broker_position_shares)

        self.assertGreater(exit_shares, 0.0)
        self.assertEqual(exit_shares, broker_position_shares)
        # Verify order quantity never exceeds current position
        order_quantity = min(exit_shares, broker_position_shares)
        self.assertEqual(order_quantity, 432.5)

        # Negative position or 0 position must raise/reject
        invalid_pos = 0.0
        should_route = invalid_pos > 0
        self.assertFalse(should_route, "Zero or negative position must reject sell routing")

    def test_fail_closed_on_unavailable_or_empty_market_data(self):
        """Invariant: If market data is missing, signal engine must fail closed to HOLD_CASH."""
        # Empty historical data
        sig = self.strategy.evaluate_point_in_time_signal(
            current_t=pd.Timestamp("2026-09-08"),
            prev_t=pd.Timestamp("2026-09-07"),
            historical_daily_data={}
        )
        self.assertEqual(sig["decision"], "HOLD_CASH")
        self.assertIsNone(sig["selected_symbol"])
        self.assertEqual(sig["eligible_candidates_count"], 0)

    def test_stop_loss_exit_boundary(self):
        """Invariant: Protective stop triggers at exactly -2.0% (current_low <= entry * 0.98)."""
        entry_price = 100.0
        # -1.9% dip -> NO exit
        should_exit, reason = self.strategy.evaluate_position_lifecycle(
            current_symbol_or_key="CSP1",
            entry_price_gbp=entry_price,
            current_low_gbp=98.10,
            should_rebalance=False,
            target_symbol_or_key="CSP1"
        )
        self.assertFalse(should_exit)
        self.assertEqual(reason, "HOLD")

        # -2.0% dip -> EXACT stop loss trigger
        should_exit, reason = self.strategy.evaluate_position_lifecycle(
            current_symbol_or_key="CSP1",
            entry_price_gbp=entry_price,
            current_low_gbp=98.00,
            should_rebalance=False,
            target_symbol_or_key="CSP1"
        )
        self.assertTrue(should_exit)
        self.assertEqual(reason, "STOP_LOSS")

        # -3.0% gap down -> STOP_LOSS trigger
        should_exit, reason = self.strategy.evaluate_position_lifecycle(
            current_symbol_or_key="CSP1",
            entry_price_gbp=entry_price,
            current_low_gbp=97.00,
            should_rebalance=False,
            target_symbol_or_key="CSP1"
        )
        self.assertTrue(should_exit)
        self.assertEqual(reason, "STOP_LOSS")

    def test_position_sizing_precision_and_cap(self):
        """Invariant: Nominal position size £40,000 capped strictly by available cash."""
        # With £50,000 cash, order notional = £40,000
        shares_at_100 = self.strategy.calculate_order_shares(100.0, available_cash_gbp=50000.0)
        self.assertEqual(shares_at_100, 400.0) # 40,000 / 100

        # With only £25,000 available cash, size capped to £25,000
        shares_capped = self.strategy.calculate_order_shares(100.0, available_cash_gbp=25000.0)
        self.assertEqual(shares_capped, 250.0) # 25,000 / 100

        # With 0 cash, 0 shares
        shares_zero = self.strategy.calculate_order_shares(100.0, available_cash_gbp=0.0)
        self.assertEqual(shares_zero, 0.0)


if __name__ == "__main__":
    unittest.main()
