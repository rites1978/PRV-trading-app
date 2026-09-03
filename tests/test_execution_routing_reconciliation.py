"""
TDD Regression Suite: Execution Routing, Broker Parity & Order Lifecycle Reconciliation.
Enforces:
1. ACCOUNT_MODE=PRACTICE calls broker.place_market_order() (Trading212 Demo API).
2. PRACTICE never returns SIMULATED_FILL.
3. Internal simulator remains available only in explicit SIMULATION mode.
4. Accepted / open / filled symbol cannot be submitted again in the next scan.
5. Telemetry cannot say TRADES EXECUTED without broker fill evidence.
"""
import unittest
from unittest.mock import patch, MagicMock
from src.config.settings import settings
from src.execution.order_router import order_router
from src.core.engine import PRVQuantEngine
from src.brokers.trading212 import broker
from src.database.db import db
from src.portfolio.daily_objective_service import daily_objective_service

class TestExecutionRoutingReconciliation(unittest.TestCase):

    def setUp(self):
        self.orig_mode = settings.ACCOUNT_MODE
        self.orig_entries = settings.PRACTICE_NEW_ENTRIES_ALLOWED
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine.is_running = False

    def tearDown(self):
        settings.ACCOUNT_MODE = self.orig_mode
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_entries

    def test_1_practice_calls_broker_place_market_order(self):
        """1. ACCOUNT_MODE=PRACTICE must call broker.place_market_order() on Trading212 Demo API."""
        import uuid
        settings.ACCOUNT_MODE = "PRACTICE"
        mock_status = {
            "new_discretionary_entries_allowed": True,
            "gate_reason": "CLEAR",
            "sizing_multiplier": 1.0,
            "emergency_risk_mode": False
        }
        order_id = f"OP_TEST_{uuid.uuid4().hex[:8]}"
        with patch.object(broker, "place_market_order", return_value={"success": True, "data": {"id": order_id, "status": "FILLED", "fillPrice": 1.50}}) as mock_order, \
             patch.object(daily_objective_service, "get_daily_status", return_value=mock_status):
            success, msg, res = order_router.route_entry_order(
                symbol="VOD",
                t212_ticker="VOD_EQ",
                quantity=100.0,
                price=1.50,
                target_price=1.70,
                stop_loss_price=1.46,
                sector="Telecommunications",
                confidence_score=85.0,
                market_regime="BULL",
                agent_votes={"trend": "BUY", "momentum": "BUY", "volatility": "BUY", "liquidity": "BUY", "risk": "BUY"},
                risk_approved=True,
                is_simulation=False,
                bypass_market_hours=True
            )
            self.assertTrue(success, f"Route entry order failed: {msg}")
            mock_order.assert_called_once_with("VOD_EQ", 100.0)

    def test_2_practice_never_returns_simulated_fill(self):
        """2. ACCOUNT_MODE=PRACTICE must never return SIMULATED_FILL in trade log or audit trail."""
        import uuid
        settings.ACCOUNT_MODE = "PRACTICE"
        mock_status = {
            "new_discretionary_entries_allowed": True,
            "gate_reason": "CLEAR",
            "sizing_multiplier": 1.0,
            "emergency_risk_mode": False
        }
        order_id = f"OP_TEST_{uuid.uuid4().hex[:8]}"
        with patch.object(broker, "place_market_order", return_value={"success": True, "data": {"id": order_id, "status": "FILLED", "fillPrice": 6.50}}), \
             patch.object(daily_objective_service, "get_daily_status", return_value=mock_status):
            success, msg, res = order_router.route_entry_order(
                symbol="HSBA",
                t212_ticker="HSBA_EQ",
                quantity=50.0,
                price=6.50,
                target_price=7.40,
                stop_loss_price=6.30,
                sector="Financials",
                confidence_score=85.0,
                market_regime="BULL",
                agent_votes={"trend": "BUY", "momentum": "BUY", "volatility": "BUY", "liquidity": "BUY", "risk": "BUY"},
                risk_approved=True,
                is_simulation=False,
                bypass_market_hours=True
            )
            self.assertNotIn("SIMULATED", msg.upper())
            self.assertNotIn("PAPER", msg.upper())

    def test_3_internal_simulator_remains_available_only_in_explicit_simulation_mode(self):
        """3. Internal simulator is active ONLY when explicitly in SIMULATION mode."""
        settings.ACCOUNT_MODE = "SIMULATION"
        mock_status = {
            "new_discretionary_entries_allowed": True,
            "gate_reason": "CLEAR",
            "sizing_multiplier": 1.0,
            "emergency_risk_mode": False
        }
        with patch.object(broker, "place_market_order") as mock_broker, \
             patch.object(daily_objective_service, "get_daily_status", return_value=mock_status):
            success, msg, res = order_router.route_entry_order(
                symbol="BP",
                t212_ticker="BP_EQ",
                quantity=100.0,
                price=4.50,
                target_price=5.10,
                stop_loss_price=4.38,
                sector="Energy",
                confidence_score=85.0,
                market_regime="BULL",
                agent_votes={"trend": "BUY", "momentum": "BUY", "volatility": "BUY", "liquidity": "BUY", "risk": "BUY"},
                risk_approved=True,
                is_simulation=True,
                bypass_market_hours=True
            )
            self.assertTrue(success, f"Simulation order failed: {msg}")
            mock_broker.assert_not_called()
            self.assertIn("SIMULATED", msg.upper())

    def test_4_accepted_open_filled_symbol_cannot_be_submitted_again_next_scan(self):
        """4. A symbol with an existing open position or pending order at the broker cannot be re-ordered."""
        with patch.object(broker, "get_open_positions", return_value=[{"ticker": "ULVR_EQ", "quantity": 10, "currentPrice": 40.0, "averagePrice": 39.0}]), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "place_market_order") as mock_place:
            
            # Attempt to evaluate / route candidate when already held
            blocked = self.engine._is_symbol_active_or_pending("ULVR_EQ")
            self.assertTrue(blocked)
            mock_place.assert_not_called()

    def test_5_telemetry_cannot_say_trades_executed_without_broker_fill_evidence(self):
        """5. Telemetry must track separate lifecycle counters and never state TRADES EXECUTED without fills."""
        telemetry = self.engine.get_execution_monitor_telemetry()
        self.assertIn("signals_approved_today", telemetry)
        self.assertIn("dispatch_attempts_today", telemetry)
        self.assertIn("broker_orders_accepted_today", telemetry)
        self.assertIn("broker_fills_today", telemetry)
        self.assertIn("broker_rejections_today", telemetry)

        # When 0 fills, decision must NOT say TRADES EXECUTED
        self.engine.broker_fills_today = 0
        self.engine.broker_orders_accepted_today = 2
        t = self.engine.get_execution_monitor_telemetry()
        self.assertNotEqual(t["last_decision"], "TRADES EXECUTED")

if __name__ == "__main__":
    unittest.main()
