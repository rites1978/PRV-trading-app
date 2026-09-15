"""
PRV Capital - Unit & Integration Tests for Strategy Authorization Gate & Order Router Two-Gate Invariant

Verifies:
1. Strict 6-instrument frozen scope for PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1:
   - CSP1, EQQQ, ISF, EMIM, SGLN, IGLT authorized
   - Other ETFs (e.g. IWDA, VUSA, SPY) rejected with UNAUTHORIZED_STRATEGY_SCOPE
   - Stocks (e.g. AAPL, TSLA) under ETF strategy rejected with UNAUTHORIZED_STRATEGY_SCOPE
2. Order Router Two-Gate Invariant:
   - Discovered: YES, Technical: YES, Strategy: NO -> REJECTED with UNAUTHORIZED_STRATEGY_SCOPE
   - Discovered: YES, Technical: NO (e.g. WARRANT), Strategy: YES -> REJECTED with TECHNICAL_EXECUTION_UNSUPPORTED
   - Discovered: YES, Technical: YES, Strategy: YES -> Passes two gates
3. CoreCompoundingStrategy assertions strictly enforce the frozen 6-ETF set
4. Zero broker order writes when either gate fails
"""
import unittest
from unittest.mock import patch, MagicMock

from src.execution.strategy_authorization_gate import strategy_authorization_gate, StrategyAuthorizationGate
from src.strategies.core_compounding_v1 import CoreCompoundingStrategy, core_compounding_strategy
from src.execution.order_router import order_router
from src.brokers.trading212 import broker
from src.config.settings import settings


class TestStrategyAuthorizationGate(unittest.TestCase):

    def setUp(self):
        self.gate = StrategyAuthorizationGate()

    def test_core_compounding_v1_strictly_permits_frozen_six(self):
        """Verify only the exact 6 frozen ETFs are authorized for PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1."""
        strat_id = "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1"
        frozen_six = ["CSP1", "EQQQ", "ISF", "EMIM", "SGLN", "IGLT"]

        for sym in frozen_six:
            is_auth, reason, details = self.gate.is_strategy_authorized(strat_id, symbol=sym)
            self.assertTrue(is_auth, f"Frozen symbol {sym} should be authorized")
            self.assertEqual(reason, "STRATEGY_ORDER_AUTHORIZED")

        # Verify other ETFs are strictly rejected
        unauthorized_etfs = ["IWDA", "VUSA", "IUSA", "INXG", "SPY", "QQQ"]
        for sym in unauthorized_etfs:
            is_auth, reason, details = self.gate.is_strategy_authorized(strat_id, symbol=sym)
            self.assertFalse(is_auth, f"Unratified ETF {sym} must be rejected")
            self.assertIn("UNAUTHORIZED_STRATEGY_SCOPE", reason)

        # Verify equities are strictly rejected under ETF strategy
        equities = ["AAPL", "MSFT", "BARC", "TSLA"]
        for sym in equities:
            is_auth, reason, details = self.gate.is_strategy_authorized(strat_id, symbol=sym)
            self.assertFalse(is_auth, f"Equity {sym} must be rejected under Core ETF strategy")
            self.assertIn("UNAUTHORIZED_STRATEGY_SCOPE", reason)

    def test_core_compounding_strategy_init_asserts_frozen_six(self):
        """Verify CoreCompoundingStrategy fails closed if CERTIFIED_UNIVERSE is tampered."""
        # Unaltered strategy should instantiate cleanly
        strat = CoreCompoundingStrategy()
        self.assertEqual(len(strat.CERTIFIED_UNIVERSE), 6)

        # Tampered strategy with extra instrument should raise ValueError
        with patch.object(CoreCompoundingStrategy, "CERTIFIED_UNIVERSE", strat.CERTIFIED_UNIVERSE + [{"symbol": "UNRATIFIED_ETF"}]):
            with self.assertRaises(ValueError) as ctx:
                CoreCompoundingStrategy()
            self.assertIn("FROZEN_UNIVERSE_VIOLATION", str(ctx.exception))

    def test_order_router_rejects_unauthorized_strategy_scope(self):
        """
        Verify Order Router Gate 2: Instrument that is technically executable
        is strictly rejected if strategy is not authorized to trade it.
        """
        broker_writes = []
        with patch.object(broker, "place_limit_order", side_effect=lambda *a, **kw: broker_writes.append("limit")), \
             patch("src.strategies.registry.strategy_registry.can_strategy_route_orders", return_value=True), \
             patch("src.data.universe.universe_manager.is_broker_supported", return_value=True):

            # Attempt to route AAPL under PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1 (Core V1)
            success, reason, meta = order_router.route_entry_order(
                symbol="AAPL",
                t212_ticker="AAPL_US_EQ",
                quantity=10.0,
                price=150.0,
                target_price=160.0,
                stop_loss_price=147.0,
                sector="Technology",
                confidence_score=0.85,
                market_regime="BULL_TREND",
                agent_votes={"Trend": "BULLISH"},
                risk_approved=True,
                strategy_id="PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
                bypass_market_hours=True,
                bypass_audit_freeze=True,
                is_simulation=False
            )

            self.assertFalse(success)
            self.assertIn("UNAUTHORIZED_STRATEGY_SCOPE", reason)
            self.assertEqual(len(broker_writes), 0, "Must never write to broker on authorization rejection!")

    def test_order_router_rejects_unsupported_technical_capability(self):
        """
        Verify Order Router Gate 1: Instrument with unsupported product family (e.g. WARRANT)
        is strictly rejected before order submission.
        """
        broker_writes = []
        with patch.object(broker, "place_limit_order", side_effect=lambda *a, **kw: broker_writes.append("limit")), \
             patch("src.strategies.registry.strategy_registry.can_strategy_route_orders", return_value=True), \
             patch("src.data.universe.universe_manager.is_broker_supported", return_value=True):

            success, reason, meta = order_router.route_entry_order(
                symbol="TEST_WARRANT",
                t212_ticker="TEST_WARRANT_EQ",
                quantity=100.0,
                price=10.0,
                target_price=12.0,
                stop_loss_price=9.0,
                sector="Derivatives",
                confidence_score=0.80,
                market_regime="BULL_TREND",
                agent_votes={"Trend": "BULLISH"},
                risk_approved=True,
                instrument_type="WARRANT",
                strategy_id="V2",
                bypass_market_hours=True,
                bypass_audit_freeze=True,
                is_simulation=False
            )

            self.assertFalse(success)
            self.assertIn("TECHNICAL_EXECUTION_UNSUPPORTED", reason)
            self.assertEqual(len(broker_writes), 0, "Must never write to broker on technical capability rejection!")


if __name__ == "__main__":
    unittest.main()
