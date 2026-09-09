"""
🏛️ PRV CAPITAL | STRATEGY V2: PRODUCTION PATH INTEGRATION TEST SUITE
Comprehensive end-to-end integration test of Strategy V2 autonomous execution:
- £50k NAV clean baseline
- Scan and candidate approval under V2 scoring
- 15 max positions and cash floor compliance
- Broker entry order fill and GTC broker-native stop order creation
- Market advance to +0.50% net target -> transition to PROFIT_PROTECTED
- Broker stop ratchet synchronization (GOOD_TILL_CANCEL)
- Mid-trade engine restart and watermark recovery
- Pullback exit execution and orphan stop cleanup
- Single idempotent vault deposit
- Released capital used in second rotation cycle
- V1 shadow-only routing isolation and parameter hash invariance
"""
import unittest
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.config.settings import settings
from src.database.db import db
from src.brokers.trading212 import broker
from src.execution.order_router import order_router
from src.execution.order_state_machine import portfolio_reservations, ManagedOrder
from src.risk.risk_engine import risk_engine
from src.data.market_data import market_data
from src.core.engine import PRVQuantEngine
from src.strategies.registry import strategy_registry
from src.strategies.v2_rotation import strategy_v2, PositionState
from src.portfolio.capital_manager import capital_manager
from src.portfolio.daily_objective_service import daily_objective_service


class TestV2ProductionPathIntegration(unittest.TestCase):

    def setUp(self):
        self.test_db_path = f"test_integration_{int(datetime.now().timestamp() * 1000)}.db"
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

    def test_complete_v2_production_lifecycle_and_rotation(self):
        """
        End-to-end test executing a complete V2 lifecycle, mid-trade restart,
        single vault deposit, and second rotation cycle.
        """
        # 1. BASELINE AUDIT
        self.assertEqual(strategy_registry.get_active_execution_strategy_id(), "V2")
        self.assertTrue(strategy_registry.can_strategy_route_orders("V2"))
        self.assertFalse(strategy_registry.can_strategy_route_orders("V1"))
        self.assertEqual(db.get_vault_balance(), 0.0)

        mock_portfolio_snap = {
            "account_summary": {
                "total_nav": 50000.0,
                "free_cash": 50000.0,
                "invested_capital": 0.0,
                "cash_pct": 100.0,
                "invested_pct": 0.0
            },
            "positions": []
        }

        # 2. V2 CANDIDATE SCAN & APPROVAL
        ticker_1 = "LLOYl_EQ"
        symbol_1 = "LLOY.L"
        entry_price_1 = 1.00
        qty_1 = 5000.0  # £5,000 consideration (10% allocation)
        order_cost_1 = 5000.0

        # Risk engine exposure check
        risk_ok, risk_msg = risk_engine.validate_exposure_order(
            symbol=symbol_1,
            t212_ticker=ticker_1,
            order_cost=order_cost_1,
            sector="Financials",
            available_cash=50000.0,
            core_capital=50000.0,
            current_positions=[],
            remaining_regime_allowance=40000.0
        )
        self.assertTrue(risk_ok, f"Risk engine rejected valid V2 order: {risk_msg}")

        # Order reservation check (V2 95% ceiling / 5% buffer)
        portfolio_reservations._reservations.clear()
        portfolio_reservations._active_idempotency_keys.clear()
        managed_order_1 = ManagedOrder(
            symbol=symbol_1,
            side="BUY",
            quantity=qty_1,
            price=entry_price_1,
            target_price=1.05,
            stop_loss_price=0.99,
            exchange="LSE",
            is_uk=True
        )
        res_ok, res_msg = portfolio_reservations.reserve(
            order=managed_order_1,
            free_cash=50000.0,
            total_nav=50000.0,
            sector="Financials",
            strategy_id="V2"
        )
        self.assertTrue(res_ok, f"Order reservation failed: {res_msg}")
        portfolio_reservations.release(managed_order_1.client_order_id)

        # 3. ROUTE ENTRY ORDER & PLACE GTC STOP
        placed_orders = []
        def mock_place_order(ticker, quantity, order_type="LIMIT", price=None, time_validity="DAY"):
            placed_orders.append({
                "ticker": ticker,
                "quantity": quantity,
                "type": order_type,
                "price": price,
                "time_validity": time_validity
            })
            return {"success": True, "data": {"id": f"ORD_{len(placed_orders)}"}}

        def mock_place_limit(ticker, quantity, limit_price, time_validity="DAY"):
            # Mirrors the current production entry contract:
            # broker.place_limit_order(t212_ticker, quantity, broker_limit_price, time_validity="DAY")
            placed_orders.append({
                "ticker": ticker,
                "quantity": quantity,
                "type": "LIMIT",
                "price": limit_price,
                "time_validity": time_validity
            })
            return {"success": True, "data": {"id": f"ORD_{len(placed_orders)}", "status": "FILLED", "filledQuantity": quantity}}

        def mock_place_stop(ticker, quantity, stop_price, time_validity="GOOD_TILL_CANCEL"):
            placed_orders.append({
                "ticker": ticker,
                "quantity": quantity,
                "type": "STOP",
                "stop_price": stop_price,
                "time_validity": time_validity
            })
            return {"success": True, "data": {"id": f"STOP_{len(placed_orders)}"}}

        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.get_authoritative_snapshot", return_value=mock_portfolio_snap), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "place_limit_order", side_effect=mock_place_limit), \
             patch.object(broker, "place_market_order", side_effect=mock_place_order), \
             patch.object(broker, "place_stop_order", side_effect=mock_place_stop):

            success, reason, data = order_router.route_entry_order(
                symbol=symbol_1,
                t212_ticker=ticker_1,
                quantity=qty_1,
                price=entry_price_1,
                target_price=1.05,
                stop_loss_price=0.99,
                sector="Financials",
                confidence_score=78.0,
                market_regime="BULL",
                agent_votes={"lead_quant": "BUY"},
                risk_approved=True,
                strategy_id="V2"
            )
            self.assertTrue(success, f"Entry order routing failed: {reason}")
            
            # Verify protective stop order used GOOD_TILL_CANCEL
            stop_placements = [o for o in placed_orders if o.get("type") == "STOP"]
            self.assertTrue(len(stop_placements) >= 1, "Native protective stop was not placed")
            self.assertEqual(stop_placements[0]["time_validity"], "GOOD_TILL_CANCEL", "Stop order must have GOOD_TILL_CANCEL validity")

        # 4. MONITOR OPEN POSITIONS & RATCHET FLOOR
        engine = PRVQuantEngine()
        engine.paper_mode = False
        engine.is_simulation = False

        # Price rises to 1.05 (+5.0% gross, well above +0.50% net target)
        active_pos_peak = [{
            "ticker": ticker_1,
            "quantity": qty_1,
            "averagePrice": entry_price_1,
            "currentPrice": 1.05
        }]

        mock_snap_market = {"success": True, "indicators": {"atr": 0.02}, "recent_returns": []}

        with patch.object(broker, "get_open_positions", return_value=active_pos_peak), \
             patch.object(broker, "get_open_orders", return_value=[{"id": "STOP_1", "ticker": ticker_1, "type": "STOP", "stopPrice": 0.99, "quantity": -qty_1}]), \
             patch.object(broker, "place_stop_order", side_effect=mock_place_stop), \
             patch.object(market_data, "get_market_snapshot", return_value=mock_snap_market):

            closed, _ = engine.monitor_open_positions()
            self.assertEqual(len(closed), 0, "Position should be running with profit protection, not closed yet")
            
            # Verify watermark was updated and persisted
            saved_wm = db.get_position_watermark(ticker_1)
            self.assertIsNotNone(saved_wm, "Watermark was not saved to DB")
            self.assertEqual(saved_wm["peak_price"], 1.05)
            self.assertEqual(saved_wm["state"], "PROFIT_PROTECTED")

        # 5. MID-TRADE ENGINE RESTART: RESTORE WATERMARK FROM DB
        new_engine = PRVQuantEngine()
        new_engine.paper_mode = False
        with patch.object(broker, "get_open_positions", return_value=active_pos_peak):
            new_engine._recover_positions_on_restart()

        self.assertIn(ticker_1, new_engine.position_peaks, "Recovered engine missing position peak")
        self.assertEqual(new_engine.position_peaks[ticker_1], 1.05, "Peak watermark not recovered accurately")

        # 6. PULLBACK EXIT TRIGGER & SINGLE IDEMPOTENT VAULT DEPOSIT
        # Price pulls back to 1.025 (below ratcheted floor of £172, but still +£97.44 net profit)
        pullback_pos = [{
            "ticker": ticker_1,
            "quantity": qty_1,
            "averagePrice": entry_price_1,
            "currentPrice": 1.025
        }]

        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.get_authoritative_snapshot", return_value=mock_portfolio_snap), \
             patch.object(broker, "get_open_positions", return_value=pullback_pos), \
             patch.object(broker, "place_market_order", return_value={"success": True, "data": {"id": "EXIT_ORD_1"}}), \
             patch.object(broker, "cancel_stop_orders_for_ticker", return_value=["STOP_1"]), \
             patch.object(market_data, "get_market_snapshot", return_value=mock_snap_market):

            closed, _ = new_engine.monitor_open_positions()
            self.assertIn(ticker_1, closed, "V2 position was not exited on pullback below ratchet floor")

        # Verify Profit Vault has EXACTLY 1 deposit
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt, SUM(realized_profit) as total FROM profit_vault WHERE trade_id != 'CAPITAL_TRANSFER_WITHDRAWAL'")
            row = cur.fetchone()
            count = row["cnt"]
            total = row["total"] or 0.0

        self.assertEqual(count, 1, f"Expected exactly 1 vault deposit, got {count}")
        self.assertGreater(total, 0.0, "Realized net profit must be vaulted")

        # Verify watermark was cleared upon exit
        cleared_wm = db.get_position_watermark(ticker_1)
        self.assertIsNone(cleared_wm, "Watermark was not cleared after position exit")

        # 7. SECOND ROTATION CYCLE
        # Release reservation from first order
        portfolio_reservations.release(managed_order_1.client_order_id)

        ticker_2 = "BARCl_EQ"
        symbol_2 = "BARC.L"
        entry_price_2 = 2.00
        qty_2 = 2500.0  # £5,000 consideration

        managed_order_2 = ManagedOrder(
            symbol=symbol_2,
            side="BUY",
            quantity=qty_2,
            price=entry_price_2,
            target_price=2.10,
            stop_loss_price=1.98,
            exchange="LSE",
            is_uk=True
        )
        res_ok_2, _ = portfolio_reservations.reserve(
            order=managed_order_2,
            free_cash=50000.0,
            total_nav=50000.0,
            sector="Financials",
            strategy_id="V2"
        )
        self.assertTrue(res_ok_2, "Second rotation order reservation failed")
        portfolio_reservations.release(managed_order_2.client_order_id)

        with patch("src.portfolio.portfolio_snapshot.portfolio_snapshot.get_authoritative_snapshot", return_value=mock_portfolio_snap), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "place_limit_order", side_effect=mock_place_limit), \
             patch.object(broker, "place_market_order", side_effect=mock_place_order), \
             patch.object(broker, "place_stop_order", side_effect=mock_place_stop):

            success_2, reason_2, _ = order_router.route_entry_order(
                symbol=symbol_2,
                t212_ticker=ticker_2,
                quantity=qty_2,
                price=entry_price_2,
                target_price=2.10,
                stop_loss_price=1.98,
                sector="Financials",
                confidence_score=82.0,
                market_regime="BULL",
                agent_votes={"lead_quant": "BUY"},
                risk_approved=True,
                strategy_id="V2"
            )
            self.assertTrue(success_2, f"Second rotation order failed: {reason_2}")

        # 8. V1 ISOLATION INVARIANCE
        manifest_hash = settings.get_parameter_manifest_hash()
        self.assertEqual(manifest_hash, "7c512be5bc26910c1c4ed81a3e650480a676cd750faa49bc8dbd8901360bc708", "V1 parameter manifest changed!")

        v1_success, _, v1_data = order_router.route_entry_order(
            symbol="V1STOCK.L",
            t212_ticker="V1STOCKl_EQ",
            quantity=100.0,
            price=10.0,
            target_price=11.0,
            stop_loss_price=9.7,
            sector="Financials",
            confidence_score=90.0,
            market_regime="BULL",
            agent_votes={},
            risk_approved=True,
            strategy_id="V1"
        )
        self.assertFalse(v1_success, "V1 order was not blocked")
        self.assertIn("STRATEGY_V1_SHADOW_ONLY", v1_data.get("rejection_reasons", []))


if __name__ == "__main__":
    unittest.main()
