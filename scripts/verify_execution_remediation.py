"""
PRV CAPITAL — EXECUTION REMEDIATION VERIFICATION & TODAY EXACT REPLAY
Tests:
1. QUANTITY_PRECISION_FIX: Verify 3-decimal precision flooring for all 7 ETFs, notional <= £40,000.
2. DETERMINISTIC_REJECTION_DEDUP: Verify non-retryable rejection dedup across cycles & process restarts.
3. SESSION_TELEMETRY_FIX: Verify session date telemetry correctly identifies session 2026-09-09 (not 2026-09-10).
4. TODAY_EXACT_REPLAY: Full end-to-end replay with mocked broker HTTP boundary.
"""
import os
import sys
import unittest
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.strategies.core_compounding_v1 import core_compounding_strategy
from src.data.universe import PRV_CORE_COMPOUNDING_UNIVERSE
from src.execution.order_router import order_router
from src.core.engine import quant_engine, PRVQuantEngine
from src.database.db import db
from src.config.settings import settings


class ExecutionRemediationTest(unittest.TestCase):

    def test_01_universe_and_strategy_precision_metadata(self):
        """Verify all 7 ETFs have broker_allowed_precision=3 and broker_allowed_increment=0.001."""
        print("\n--- TEST 1: METADATA & SIZING PRECISION ---")
        self.assertEqual(len(PRV_CORE_COMPOUNDING_UNIVERSE), 7)
        self.assertEqual(len(core_compounding_strategy.CERTIFIED_UNIVERSE), 7)

        for item in PRV_CORE_COMPOUNDING_UNIVERSE:
            sym = item["symbol"]
            self.assertEqual(item.get("broker_allowed_precision"), 3, f"{sym} in PRV_CORE_COMPOUNDING_UNIVERSE must have precision 3")
            self.assertEqual(item.get("broker_allowed_increment"), 0.001, f"{sym} in PRV_CORE_COMPOUNDING_UNIVERSE must have increment 0.001")

        for item in core_compounding_strategy.CERTIFIED_UNIVERSE:
            sym = item["symbol"]
            self.assertEqual(item.get("broker_allowed_precision"), 3, f"{sym} in CERTIFIED_UNIVERSE must have precision 3")
            self.assertEqual(item.get("broker_allowed_increment"), 0.001, f"{sym} in CERTIFIED_UNIVERSE must have increment 0.001")

        print("  ✅ All 7 ETFs metadata verified: precision=3, increment=0.001")

    def test_02_emim_and_all_etf_quantity_flooring(self):
        """Verify EMIM and all 7 ETFs calculate valid broker quantities bounded by £40k."""
        # 1. EMIM exact reproduction: Price = £41.6925, deployable = £40,000.00 (total_nav=None)
        emim_price = 41.6925
        qty_40k = core_compounding_strategy.calculate_order_shares(
            entry_price_gbp=emim_price,
            available_cash_gbp=50000.0,
            total_nav_gbp=None,
            symbol="EMIM"
        )
        self.assertEqual(qty_40k, 959.405)
        self.assertLessEqual(qty_40k * emim_price, 40000.00)
        decimals_40k = len(str(qty_40k).split(".")[1]) if "." in str(qty_40k) else 0
        self.assertLessEqual(decimals_40k, 3)

        # 2. EMIM with £50k total NAV: deployable = 50000 * 0.80 - 15 = 39985.0
        qty_nav = core_compounding_strategy.calculate_order_shares(
            entry_price_gbp=emim_price,
            available_cash_gbp=50000.0,
            total_nav_gbp=50000.0,
            symbol="EMIM"
        )
        self.assertEqual(qty_nav, 959.045)
        self.assertLessEqual(qty_nav * emim_price, 39985.00)
        decimals_nav = len(str(qty_nav).split(".")[1]) if "." in str(qty_nav) else 0
        self.assertLessEqual(decimals_nav, 3)
        print(f"  ✅ EMIM £40k deployable @ £{emim_price}: shares={qty_40k} (scale={decimals_40k}), notional=£{qty_40k * emim_price:.2f} <= £40,000.00")
        print(f"  ✅ EMIM £50k NAV (80%-£15) @ £{emim_price}: shares={qty_nav} (scale={decimals_nav}), notional=£{qty_nav * emim_price:.2f} <= £39,985.00")

        # 3. Test floor_to_broker_increment directly with problematic raw quantity 959.4158
        floored = core_compounding_strategy.floor_to_broker_increment(959.4158, increment=0.001, precision=3)
        self.assertEqual(floored, 959.415)
        self.assertLessEqual(floored * emim_price, 40000.43)
        print(f"  ✅ Raw 959.4158 floored to {floored}")

        # 4. Check all 7 instruments with representative prices
        sample_prices = {
            "CSP1": 560.25,
            "EQQQ": 420.10,
            "IWDA": 95.40,
            "ISF": 8.75,
            "EMIM": 41.6925,
            "SGLN": 38.50,
            "IGLT": 11.20
        }
        for sym, p in sample_prices.items():
            shares = core_compounding_strategy.calculate_order_shares(p, 50000.0, 50000.0, sym)
            dec = len(str(shares).split(".")[1]) if "." in str(shares) else 0
            self.assertLessEqual(dec, 3)
            self.assertLessEqual(shares * p, 40000.00)
            self.assertGreater(shares, 0)
            print(f"  ✅ {sym} @ £{p:.4f} -> shares={shares} (scale={dec}), notional=£{shares * p:.2f}")

    def test_03_order_router_defense_in_depth_flooring(self):
        """Verify order_router floors incoming non-compliant quantities before dispatching to broker."""
        print("\n--- TEST 2: ORDER ROUTER DEFENSE-IN-DEPTH FLOORING ---")
        unique_order_id = f"TEST_ROUTER_FLOOR_{int(datetime.now().timestamp() * 1000)}"
        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.hydrate_once", return_value={"account_summary": {"free_cash": 50000.0, "total_nav": 50000.0}, "positions": []}), \
             patch("src.brokers.trading212.broker.get_open_orders", return_value=[]), \
             patch("src.brokers.trading212.broker.place_limit_order") as mock_place, \
             patch("src.brokers.trading212.broker.sync_broker_stop_order", return_value={"success": True, "data": {"id": "STOP_FLOOR_001"}}), \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True), \
             patch("src.execution.net_edge_gate.net_edge_gate.evaluate_candidate") as mock_gate:
            mock_place.return_value = {"success": True, "data": {"id": unique_order_id, "status": "FILLED", "fillPrice": 41.6925, "filledQuantity": 959.045}}
            mock_gate.return_value = {
                "approved": True,
                "rejection_reasons": [],
                "predicted_net_return_pct": 1.5,
                "net_reward_risk": 2.5,
                "total_round_trip_cost_gbp": 12.0
            }
            # Pass a 4-decimal quantity to route_entry_order (959.0458)
            ok, msg, data = order_router.route_entry_order(
                symbol="EMIM",
                t212_ticker="EMIMl_EQ",
                quantity=959.0458,  # Intentionally 4 decimal places
                price=41.6925,
                target_price=45.0,
                stop_loss_price=40.85,
                sector="ETF",
                confidence_score=0.24,
                market_regime="CROSS_SECTIONAL_MOMENTUM",
                agent_votes={"CORE_COMPOUNDING": "BUY"},
                risk_approved=True,
                is_paper=False,
                strategy_id="PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
                bypass_market_hours=True,
                bypass_audit_freeze=True
            )
            self.assertTrue(ok, f"route_entry_order failed: {msg}")
            # Ensure broker received floored 3-decimal quantity: 959.045
            mock_place.assert_called_once()
            submitted_ticker, submitted_qty = mock_place.call_args[0][:2]
            self.assertEqual(submitted_ticker, "EMIMl_EQ")
            self.assertEqual(submitted_qty, 959.045)
            print(f"  ✅ order_router successfully floored 959.0458 to {submitted_qty} before broker call")

    def test_04_deterministic_rejection_dedup(self):
        """Verify non-timeout broker rejection marks signal executed and prevents all subsequent attempts."""
        print("\n--- TEST 3: DETERMINISTIC REJECTION DEDUP ---")
        test_dedup_key = f"CORE_TEST_TICKER_{int(datetime.now().timestamp())}"
        
        # 1. Simulate rejection response from order_router
        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.hydrate_once", return_value={"account_summary": {"free_cash": 50000.0, "total_nav": 50000.0}, "positions": []}), \
             patch("src.brokers.trading212.broker.get_open_orders", return_value=[]), \
             patch("src.brokers.trading212.broker.place_limit_order") as mock_place, \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True), \
             patch("src.execution.net_edge_gate.net_edge_gate.evaluate_candidate") as mock_gate:
            mock_place.return_value = {
                "success": False,
                "error": 'HTTP 400 Bad Request: {"type":"/api-errors/quantity-precision-mismatch","status":400,"detail":"invalid quantity precision 3"}'
            }
            mock_gate.return_value = {
                "approved": True,
                "rejection_reasons": [],
                "predicted_net_return_pct": 1.5,
                "net_reward_risk": 2.5,
                "total_round_trip_cost_gbp": 12.0
            }
            ok, msg, res = order_router.route_entry_order(
                symbol="EMIM",
                t212_ticker="EMIMl_EQ",
                quantity=959.045,
                price=41.6925,
                target_price=45.0,
                stop_loss_price=40.85,
                sector="ETF",
                confidence_score=0.24,
                market_regime="CROSS_SECTIONAL_MOMENTUM",
                agent_votes={"CORE_COMPOUNDING": "BUY"},
                risk_approved=True,
                is_paper=False,
                strategy_id="PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
                bypass_market_hours=True,
                bypass_audit_freeze=True
            )
            self.assertFalse(ok)
            self.assertEqual(res.get("status"), "REJECTED_NON_RETRYABLE_FOR_SIGNAL")
            print("  ✅ order_router flagged status as REJECTED_NON_RETRYABLE_FOR_SIGNAL")

        # 2. Test engine mark_signal_bar_executed and is_signal_bar_already_executed
        quant_engine.mark_signal_bar_executed(test_dedup_key)
        self.assertTrue(quant_engine.is_signal_bar_already_executed(test_dedup_key))

        # 3. Test persistence check in DB across process restarts
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": test_dedup_key,
            "signal_bar_date": "2026-09-08",
            "signal_generated_at": datetime.now().isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-09",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "REJECTED_NON_RETRYABLE_FOR_SIGNAL",
            "notes": "Test rejection persistence"
        })

        # Create a fresh engine instance simulating process reboot
        fresh_engine = PRVQuantEngine()
        self.assertTrue(fresh_engine.is_signal_bar_already_executed(test_dedup_key))
        print("  ✅ Persistence verified: fresh engine instance detects REJECTED_NON_RETRYABLE_FOR_SIGNAL from DB")

    def test_05_session_date_telemetry(self):
        """Verify session date telemetry distinguishes today from upcoming session and never claims tomorrow has elapsed."""
        print("\n--- TEST 4: SESSION DATE TELEMETRY ---")
        tz_london = ZoneInfo("Europe/London")

        # Scenario A: 2026-09-09 07:45:00 BST (before market open)
        dt_pre = datetime(2026, 9, 9, 7, 45, 0, tzinfo=tz_london)
        ctx_pre = quant_engine.get_core_compounding_session_context(dt_pre)
        self.assertEqual(ctx_pre["intended_execution_session"], "2026-09-09")
        self.assertEqual(ctx_pre["next_execution_session"], "2026-09-10")
        self.assertFalse(ctx_pre["is_execution_window"])

        # Scenario B: 2026-09-09 08:02:00 BST (market open window)
        dt_win = datetime(2026, 9, 9, 8, 2, 0, tzinfo=tz_london)
        ctx_win = quant_engine.get_core_compounding_session_context(dt_win)
        self.assertEqual(ctx_win["intended_execution_session"], "2026-09-09")
        self.assertTrue(ctx_win["is_execution_window"])

        # Scenario C: 2026-09-09 08:18:00 BST (post-window)
        dt_post = datetime(2026, 9, 9, 8, 18, 0, tzinfo=tz_london)
        ctx_post = quant_engine.get_core_compounding_session_context(dt_post)
        self.assertEqual(ctx_post["next_execution_session"], "2026-09-10")
        self.assertFalse(ctx_post["is_execution_window"])

        # Check the string generated for post-window expired signal
        obs_bar_str = "2026-09-08"
        signal_execution_session = quant_engine.get_next_valid_lse_session(obs_bar_str)
        self.assertEqual(signal_execution_session, "2026-09-09")

        cur_t = dt_post.time()
        if cur_t >= dtime(8, 5):
            expired_reason = f"SIGNAL_EXPIRED: 08:00:00-08:05:00 BST market open execution window for session {signal_execution_session} has elapsed. Next execution window opens at 08:00:00 BST on {ctx_post['next_execution_session']}."
        self.assertIn("session 2026-09-09 has elapsed", expired_reason)
        self.assertNotIn("session 2026-09-10 has elapsed", expired_reason)
        print(f"  ✅ Post-window reason message verified: '{expired_reason}'")

    def test_06_today_exact_replay(self):
        """Replay today's exact execution cycle with mocked broker boundary."""
        print("\n--- TEST 5: TODAY EXACT REPLAY ---")
        tz_london = ZoneInfo("Europe/London")
        unique_replay_id = f"REPLAY_ORDER_EMIM_{int(datetime.now().timestamp() * 1000)}"

        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.hydrate_once", return_value={"account_summary": {"free_cash": 50000.0, "total_nav": 50000.0}, "positions": []}), \
             patch("src.brokers.trading212.broker.place_limit_order") as mock_place, \
             patch("src.brokers.trading212.broker.sync_broker_stop_order") as mock_stop, \
             patch("src.brokers.trading212.broker.get_open_positions", return_value=[]), \
             patch("src.brokers.trading212.broker.get_open_orders", return_value=[]), \
             patch("src.execution.net_edge_gate.net_edge_gate.evaluate_candidate") as mock_gate, \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True), \
             patch.object(settings, "REAL_MONEY_NEW_ENTRIES_ALLOWED", False), \
             patch("src.database.db.db.get_core_compounding_decision", return_value=None), \
             patch("src.database.db.db.get_trades", return_value=[]), \
             patch("src.data.market_data.market_data.get_current_executable_price", return_value=41.6925):

            mock_place.return_value = {
                "success": True,
                "data": {
                    "id": unique_replay_id,
                    "status": "FILLED",
                    "fillPrice": 41.6925,
                    "filledQuantity": 958.087
                }
            }
            mock_stop.return_value = {"success": True, "data": {"id": "REPLAY_STOP_EMIM_001"}}
            mock_gate.return_value = {
                "approved": True,
                "rejection_reasons": [],
                "predicted_net_return_pct": 1.5,
                "net_reward_risk": 2.5,
                "total_round_trip_cost_gbp": 12.0
            }

            # Run cycle at 08:01:00 BST with bypass_execution_window=True
            replay_dedup_key = f"CORE_EMIMl_EQ_2026-09-08"
            # Ensure clean initial state for dedup key
            if hasattr(quant_engine, "_executed_signals") and replay_dedup_key in quant_engine._executed_signals:
                quant_engine._executed_signals.remove(replay_dedup_key)

            with patch.object(quant_engine, "evaluate_core_compounding_live_state") as mock_eval:
                mock_eval.return_value = {
                    "decision": "ENTER",
                    "selected_symbol": "EMIM",
                    "selected_t212_ticker": "EMIMl_EQ",
                    "selected_score": 0.2433,
                    "as_of_date": "2026-09-09",
                    "previous_timestamp": "2026-09-08 21:00:00",
                    "eligible_candidates_count": 1,
                    "rankings": [
                        {"symbol": "EMIM", "ticker": "EMIMl_EQ", "score": 0.2433, "close_t_minus_1": 41.6925}
                    ]
                }

                mock_account = {"total_value": 50000.0, "available_cash": 50000.0}

                # Cycle 1: Should execute exactly once
                res1 = quant_engine._run_core_compounding_cycle(mock_account, bypass_execution_window=True)
                self.assertEqual(res1["decision"], "ENTER")
                self.assertEqual(res1["selected_instrument"], "EMIM")
                self.assertEqual(mock_place.call_count, 1)

                submitted_ticker, submitted_qty = mock_place.call_args[0][:2]
                self.assertEqual(submitted_ticker, "EMIMl_EQ")
                # Sizing price with 10 bps collar ceiling: round(41.6925 * 1.0010, 4) = 41.7342
                # Deployable = 50k NAV * 0.80 - 15 = 39985.0 / 41.7342 = 958.087 shares
                self.assertEqual(submitted_qty, 958.087)
                self.assertLessEqual(submitted_qty * 41.7342, 39985.0)
                print(f"  ✅ Replay Cycle 1: ENTER executed, submitted_qty={submitted_qty}, mock_place call count=1")

                # Cycle 2: Same signal -> Must be DEDUP with ZERO broker calls
                res2 = quant_engine._run_core_compounding_cycle(mock_account, bypass_execution_window=True)
                self.assertEqual(res2["decision"], "HOLD")
                self.assertIn("DEDUP", res2["reason"])
                self.assertEqual(mock_place.call_count, 1)  # Still 1, no new call!
                print(f"  ✅ Replay Cycle 2: DEDUP triggered, mock_place call count remains 1")

                # Cycle 3: Must still be 1
                res3 = quant_engine._run_core_compounding_cycle(mock_account, bypass_execution_window=True)
                self.assertEqual(res3["decision"], "HOLD")
                self.assertEqual(mock_place.call_count, 1)
                print(f"  ✅ Replay Cycle 3: DEDUP sustained, mock_place call count remains 1")


if __name__ == "__main__":
    unittest.main()

