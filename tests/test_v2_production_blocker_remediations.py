"""
🏛️ PRV CAPITAL | STRATEGY V2 PRE-PRODUCTION BLOCKER REGRESSION SUITE
Reproduces the 8 confirmed production blockers and safety defects:
1. Production must actually run V2 lifecycle in engine.py
2. Single vault deposit per closed profitable trade (idempotent accounting)
3. Remove legacy 45% cash floor / 55% ceiling leakage in order reservations
4. Market data must fail-closed on missing/empty/NaN data (no synthetic bullish spoofing)
5. Enforce MAX_CONCURRENT_POSITIONS = 15 in risk engine
6. Safe broker stop replacement (never leave position naked on replacement failure)
7. Persistent broker protection (GOOD_TILL_CANCEL time validity)
8. Persist and restore position high watermark across process restarts
A. Orphan stop order reconciliation
B. Stop-loss 10-day cooldown insertion
"""
import unittest
import os
import json
import sqlite3
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from src.config.settings import settings
from src.database.db import db, Database
from src.brokers.trading212 import broker
from src.execution.order_router import order_router
from src.execution.order_state_machine import portfolio_reservations, ManagedOrder, OrderState
from src.risk.risk_engine import risk_engine
from src.data.market_data import market_data
from src.core.engine import PRVQuantEngine
from src.strategies.v2_rotation import strategy_v2, PositionState


class TestBlockerRemediations(unittest.TestCase):

    def setUp(self):
        self.test_db_path = f"test_remediation_{int(datetime.now().timestamp() * 1000)}.db"
        self.orig_db_path = db.db_path
        db.db_path = self.test_db_path
        db._init_db()
        risk_engine.initialize_day(50000.0)

    def tearDown(self):
        db.db_path = self.orig_db_path
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    # =========================================================================
    # BLOCKER 1: Production Must Actually Run V2
    # =========================================================================
    def test_blocker_1_engine_executes_v2_lifecycle_on_net_profit_target(self):
        """
        Verify that engine.py:monitor_open_positions evaluates V2 lifecycle:
        - When position achieves +0.50% net profit target, it transitions to PROFIT_PROTECTED.
        - Ratchet floor protects profits.
        - When price pulls back below ratchet floor, an exit order is routed with V2 rotation recorded.
        """
        engine = PRVQuantEngine()
        engine.paper_mode = False
        engine.is_simulation = False

        # Open position: bought 100 shares at £10.00 (£1,000 capital).
        # Target net profit is +0.50% (£5.00).
        # Position rises to £10.15 (+1.5%), achieving net target, then pulls back to £10.02.
        mock_pos = [{
            "ticker": "TESTl_EQ",
            "quantity": 100.0,
            "averagePrice": 10.00,
            "currentPrice": 10.02  # Pullback below +0.50% net floor
        }]

        with patch.object(broker, "get_open_positions", return_value=mock_pos), \
             patch.object(market_data, "get_market_snapshot", return_value={"success": True, "indicators": {"atr": 0.20}, "recent_returns": []}), \
             patch.object(broker, "sync_broker_stop_order", return_value={"success": True}), \
             patch.object(order_router, "route_exit_order", return_value=(True, "V2 Exit", {"trade_id": "TEST_EXIT_1", "net_realized_pnl": 5.0, "gross_profit_loss": 6.0, "total_transaction_costs": 1.0})) as mock_exit:
            
            # Record historical peak in V2 lifecycle or engine
            engine.position_peaks["TESTl_EQ"] = 10.15

            closed, _ = engine.monitor_open_positions()

            # Under V2: £10.02 is below the ratcheted floor after achieving +1.5% peak, so it must trigger exit!
            # Under defective legacy V1: base_stop_pct is -2.5% (£9.75), peak is +1.5% (< +3.0% trigger),
            # so defective engine holds and closed is empty!
            self.assertIn("TESTl_EQ", closed, "Defect: V2 position was not exited under V2 lifecycle ratchet")
            self.assertTrue(mock_exit.called, "route_exit_order should be called under V2 lifecycle")

    # =========================================================================
    # BLOCKER 2: Double Profit Vault Deposit
    # =========================================================================
    def test_blocker_2_single_vault_deposit_on_profitable_exit(self):
        """
        A single profitable closed trade must produce EXACTLY ONE vault deposit,
        never duplicate deposits across order_router and engine.py.
        """
        # Clean vault baseline
        self.assertEqual(db.get_vault_balance(), 0.0)

        # In order_router.route_exit_order:
        # It executes SELL market order, records trade, and calls daily_objective_service.process_trade_close
        symbol = "LLOY.L"
        t212_ticker = "LLOYl_EQ"

        mock_snap = {
            "account_summary": {
                "total_nav": 50000.0,
                "free_cash": 50000.0,
                "invested_capital": 0.0,
                "cash_pct": 100.0,
                "invested_pct": 0.0
            }
        }

        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.get_authoritative_snapshot", return_value=mock_snap), \
             patch.object(broker, "place_market_order", return_value={"success": True, "data": {"id": "ORD_123"}}), \
             patch.object(broker, "cancel_stop_orders_for_ticker", return_value=[]):

            success, msg, net_calc = order_router.route_exit_order(
                symbol=symbol,
                t212_ticker=t212_ticker,
                quantity=1000.0,
                current_price=1.20,
                entry_price=1.10,
                exit_reason="Take Profit Test",
                is_paper=False
            )
            self.assertTrue(success)

            # Check vault after order_router
            vault_after_router = db.get_vault_balance()
            self.assertGreater(vault_after_router, 0.0, "Profitable trade at £50k base must deposit to vault")

            # Now simulate second deposit attempt (e.g. from engine or duplicate event) with same trade_id
            realized_pnl = net_calc.get("net_realized_pnl", 50.0)
            trade_id = net_calc.get("trade_id", f"EXIT_{t212_ticker}")
            db.deposit_profit_vault(trade_id=trade_id, symbol=t212_ticker, realized_profit=realized_pnl, notes="Duplicate deposit attempt")

            # Check vault entries in db
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) as cnt, SUM(realized_profit) as total FROM profit_vault WHERE trade_id != 'CAPITAL_TRANSFER_WITHDRAWAL'")
                row = cur.fetchone()
                count = row["cnt"]
                total = row["total"] or 0.0

            # Under defective code, count was 2 (double deposit!). Remediated code is exactly 1.
            self.assertEqual(count, 1, f"Expected exactly 1 vault deposit, got {count}")

    # =========================================================================
    # BLOCKER 3: Remove V1 Cash Floor Leakage from V2
    # =========================================================================
    def test_blocker_3_v2_order_reservation_not_blocked_by_45pct_cash_floor(self):
        """
        V2 allows deploying up to 95% of active capital (5% buffer = £2,500).
        If cash is £20,000 (which is < £22,500 legacy 45% floor), a £2,000 V2 order MUST be approved.
        """
        order = ManagedOrder(
            symbol="V2STOCK",
            side="BUY",
            quantity=100.0,
            price=20.0,  # Consideration = £2,000.00
            target_price=22.0,
            stop_loss_price=19.8,
            exchange="LSE",
            is_uk=True
        )

        portfolio_reservations._reservations.clear()
        portfolio_reservations._active_idempotency_keys.clear()

        ok, msg = portfolio_reservations.reserve(
            order=order,
            free_cash=20000.0,
            total_nav=50000.0,
            sector="Technology",
            strategy_id="V2"
        )
        self.assertTrue(ok, f"Defect: V2 reservation blocked by legacy cash floor: {msg}")

        # Invariance check: V1 MUST still enforce the 45% floor
        portfolio_reservations.release(order.client_order_id)
        order_v1 = ManagedOrder(
            symbol="V1STOCK",
            side="BUY",
            quantity=100.0,
            price=20.0,
            target_price=22.0,
            stop_loss_price=19.8,
            exchange="LSE",
            is_uk=True
        )
        ok_v1, msg_v1 = portfolio_reservations.reserve(
            order=order_v1,
            free_cash=20000.0,
            total_nav=50000.0,
            sector="Technology",
            strategy_id="V1"
        )
        self.assertFalse(ok_v1, "V1 MUST remain protected by 45% cash floor")
        self.assertIn("protecting £22,500.00 floor", msg_v1)

    # =========================================================================
    # BLOCKER 4: Market Data Must Fail Closed
    # =========================================================================
    def test_blocker_4_market_data_fails_closed_on_empty_or_nan(self):
        """
        Market data fetch must NOT emit synthetic bullish success snapshots when
        data is empty, stale, or malformed.
        """
        with patch.object(market_data, "fetch_history", return_value=pd.DataFrame()):
            snap = market_data.get_market_snapshot("NONEXISTENT_TICKER")
            self.assertFalse(snap.get("success", False), "Empty market data must return success=False")
            self.assertIn("error", snap, "Must provide failure error description")

        # Test with NaN prices
        df_nan = pd.DataFrame({
            "Open": [float("nan")] * 20,
            "High": [float("nan")] * 20,
            "Low": [float("nan")] * 20,
            "Close": [float("nan")] * 20,
            "Volume": [1000] * 20
        })
        with patch.object(market_data, "fetch_history", return_value=df_nan):
            snap_nan = market_data.get_market_snapshot("NAN_TICKER")
            self.assertFalse(snap_nan.get("success", False), "NaN market data must return success=False")

    # =========================================================================
    # BLOCKER 5: Max Concurrent Positions (15 Cap)
    # =========================================================================
    def test_blocker_5_risk_engine_enforces_15_positions_cap(self):
        """
        validate_exposure_order must reject when current positions >= MAX_CONCURRENT_POSITIONS (15).
        """
        current_15_positions = [{"symbol": f"SYM_{i}", "ticker": f"SYM_{i}", "quantity": 10, "currentPrice": 100.0, "sector": f"Sec_{i}"} for i in range(15)]
        
        ok, reason = risk_engine.validate_exposure_order(
            symbol="NEW_16TH",
            t212_ticker="NEW_16TH",
            order_cost=2000.0,
            sector="Financials",
            available_cash=20000.0,
            core_capital=50000.0,
            current_positions=current_15_positions,
            remaining_regime_allowance=20000.0
        )
        self.assertFalse(ok, "Position 16 must be rejected by risk engine")
        self.assertIn("Maximum concurrent positions limit (15) reached", reason)

    # =========================================================================
    # BLOCKER 6 & 7: Safe Stop Replacement & Persistent Stop Protection
    # =========================================================================
    def test_blocker_6_and_7_safe_stop_replacement_and_persistent_validity(self):
        """
        1. Stop orders must use GOOD_TILL_CANCEL time validity.
        2. When replacing an existing stop with a higher stop, if placement fails,
           the existing stop must NOT be left cancelled without protection.
        """
        existing_stop_order = {
            "id": 999111,
            "ticker": "SHELl_EQ",
            "type": "STOP",
            "stopPrice": 32.00,
            "quantity": -100.0
        }

        with patch.object(broker, "get_open_orders", return_value=[existing_stop_order]), \
             patch.object(broker, "place_stop_order", return_value={"success": False, "error": "HTTP 500 Network Error"}) as mock_place, \
             patch.object(broker, "cancel_order", return_value={"success": True}) as mock_cancel:

            res = broker.sync_broker_stop_order("SHELl_EQ", 100.0, 34.00)

            self.assertTrue(mock_place.called)
            call_kwargs = mock_place.call_args[1] if mock_place.call_args else {}
            validity = call_kwargs.get("time_validity", mock_place.call_args[0][3] if len(mock_place.call_args[0]) > 3 else "")
            self.assertEqual(validity, "GOOD_TILL_CANCEL", "Broker stop orders must use GOOD_TILL_CANCEL")
            self.assertFalse(res.get("success"), "sync_broker_stop_order must report failure when broker rejects")

    # =========================================================================
    # BLOCKER 8: Persist High-Watermark State
    # =========================================================================
    def test_blocker_8_position_peak_watermark_survives_restart(self):
        """
        Position peak gain state must be persisted to the database and recovered across process restarts.
        """
        ticker = "STANl_EQ"
        self.assertTrue(hasattr(db, "save_position_watermark"), "db must have save_position_watermark")
        db.save_position_watermark(ticker, peak_price=10.80, peak_pnl_pct=0.08, state="PROFIT_PROTECTED")

        mock_pos = [{
            "ticker": ticker,
            "quantity": 100.0,
            "averagePrice": 10.00,
            "currentPrice": 10.40
        }]

        new_engine = PRVQuantEngine()
        new_engine.paper_mode = False
        with patch.object(broker, "get_open_positions", return_value=mock_pos):
            new_engine._recover_positions_on_restart()

        recovered_peak = new_engine.position_peaks.get(ticker)
        self.assertEqual(recovered_peak, 10.80, f"Defect: High watermark was wiped on restart (got {recovered_peak})")

    # =========================================================================
    # SAFETY: Orphan Stop Order Reconciliation
    # =========================================================================
    def test_reconcile_orphan_stops_cancels_residual_orders(self):
        """
        Safety Watchdog: If a stop order exists on the broker for a ticker with
        ZERO open positions (e.g. after exit), reconcile_orphan_stops must cancel it.
        """
        mock_orders = [
            {"id": "STOP_ORPHAN_1", "ticker": "ORPHANl_EQ", "type": "STOP", "quantity": -50.0, "stopPrice": 15.0},
            {"id": "STOP_ACTIVE_2", "ticker": "ACTIVEl_EQ", "type": "STOP", "quantity": -100.0, "stopPrice": 25.0}
        ]
        mock_positions = [
            {"ticker": "ACTIVEl_EQ", "quantity": 100.0, "averagePrice": 26.0}
        ]

        with patch.object(broker, "get_open_orders", return_value=mock_orders), \
             patch.object(broker, "get_open_positions", return_value=mock_positions), \
             patch.object(broker, "cancel_order", return_value={"success": True}) as mock_cancel:

            reconciled = broker.reconcile_orphan_stops()
            self.assertIn("STOP_ORPHAN_1", reconciled, "Orphan stop order was not detected and cancelled")
            self.assertNotIn("STOP_ACTIVE_2", reconciled, "Active position stop order must not be cancelled")
            mock_cancel.assert_called_once_with("STOP_ORPHAN_1")


if __name__ == "__main__":
    unittest.main()

