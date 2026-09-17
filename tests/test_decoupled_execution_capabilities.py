"""
PRV Capital - Targeted Tests for Decoupled Execution Capabilities & Broker Tradability Semantics
Governing Specification: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Proves:
1. Missing maxOpenQuantity -> UNKNOWN, not zero
2. Explicit maxOpenQuantity=0 remains known zero
3. Positive maxOpenQuantity remains known broker metadata
4. Unknown quantity rule fails closed
5. Unknown tick rule fails closed
6. Unknown stop support fails closed
7. Unknown cost completeness fails closed
8. Capability statuses remain independent
9. No capability can become PROVEN without provenance
10. One proven capability cannot promote another capability
11. Zero broker writes occur from the capability evaluator
12. No strategy decision is introduced by this layer

All fixtures in this file are synthetic test fixtures explicitly labelled SYNTHETIC.
"""
import unittest
from unittest.mock import patch, MagicMock
from typing import Dict, Any

from src.data.broker_discovery import broker_discovery
from src.data.technical_execution_capability import (
    technical_execution_capability,
    CapabilityState
)


class TestDecoupledExecutionCapabilities(unittest.TestCase):
    """Targeted contract tests for decoupled execution verification and tradability plumbing."""

    # =========================================================================
    # 1. BROKER TRADABILITY SEMANTICS (Section 1)
    # =========================================================================

    def test_tradability_missing_max_open_quantity_yields_unknown_not_zero(self):
        """Prove missing or null maxOpenQuantity yields UNKNOWN, never 0.0 or False-negative zero."""
        # SYNTHETIC FIXTURE 1: Missing key entirely
        synthetic_missing_key: Dict[str, Any] = {
            "ticker": "SYNTH_MISSING_QTY_EQ",
            "type": "STOCK",
            "currencyCode": "USD"
        }
        res1 = broker_discovery.evaluate_tradability(synthetic_missing_key)
        self.assertIsNone(res1["max_open_quantity"], "Missing maxOpenQuantity must be None, never 0 or 0.0")
        self.assertEqual(res1["max_open_quantity_status"], "UNKNOWN")
        self.assertEqual(res1["broker_tradability_status"], "UNKNOWN")
        self.assertFalse(res1["is_tradable"])

        # SYNTHETIC FIXTURE 2: Explicit None value
        synthetic_null_val: Dict[str, Any] = {
            "ticker": "SYNTH_NULL_QTY_EQ",
            "type": "STOCK",
            "currencyCode": "GBP",
            "maxOpenQuantity": None
        }
        res2 = broker_discovery.evaluate_tradability(synthetic_null_val)
        self.assertIsNone(res2["max_open_quantity"])
        self.assertEqual(res2["max_open_quantity_status"], "UNKNOWN")
        self.assertEqual(res2["broker_tradability_status"], "UNKNOWN")
        self.assertFalse(res2["is_tradable"])

    def test_tradability_explicit_zero_remains_known_zero(self):
        """Prove explicit maxOpenQuantity=0 is preserved as KNOWN_ZERO, distinct from UNKNOWN."""
        # SYNTHETIC FIXTURE: Explicit zero from broker
        synthetic_zero: Dict[str, Any] = {
            "ticker": "SYNTH_ZERO_QTY_EQ",
            "type": "STOCK",
            "currencyCode": "EUR",
            "maxOpenQuantity": 0.0
        }
        res = broker_discovery.evaluate_tradability(synthetic_zero)
        self.assertEqual(res["max_open_quantity"], 0.0)
        self.assertEqual(res["max_open_quantity_status"], "KNOWN_ZERO")
        self.assertEqual(res["broker_tradability_status"], "UNTRADABLE_ZERO_QUANTITY")
        self.assertFalse(res["is_tradable"])

    def test_tradability_positive_remains_known_broker_metadata(self):
        """Prove positive maxOpenQuantity is preserved as KNOWN_POSITIVE and TRADABLE."""
        # SYNTHETIC FIXTURE: Explicit positive quantity
        synthetic_pos: Dict[str, Any] = {
            "ticker": "SYNTH_POS_QTY_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "maxOpenQuantity": 1500.0
        }
        res = broker_discovery.evaluate_tradability(synthetic_pos)
        self.assertEqual(res["max_open_quantity"], 1500.0)
        self.assertEqual(res["max_open_quantity_status"], "KNOWN_POSITIVE")
        self.assertEqual(res["broker_tradability_status"], "TRADABLE")
        self.assertTrue(res["is_tradable"])

    # =========================================================================
    # 2. DECOUPLED CAPABILITY EVALUATION & FAIL-CLOSED SEMANTICS (Section 2)
    # =========================================================================

    def test_unknown_quantity_rule_fails_closed(self):
        """Prove instrument with missing quantity precision fails closed."""
        # SYNTHETIC FIXTURE: Missing minTradeQuantity and quantityPrecision
        synthetic_no_qty: Dict[str, Any] = {
            "ticker": "SYNTH_NO_QTY_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "exchange_venue": "NYSE",
            "tickSize": 0.01
        }
        caps = technical_execution_capability.evaluate_capabilities(synthetic_no_qty)
        qty_cap = caps["quantity_rule"]
        self.assertEqual(qty_cap.status, "UNKNOWN")
        self.assertIsNone(qty_cap.value)
        self.assertEqual(qty_cap.evidence_level, "SYNTHETIC_FIXTURE_NOT_PROVEN")

        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(synthetic_no_qty)
        self.assertFalse(is_exec, "Missing quantity rule must fail closed")
        self.assertIn("QUANTITY_RULE_UNPROVEN", reason)

    def test_unknown_tick_rule_fails_closed(self):
        """Prove instrument with unknown tick rule fails closed."""
        # SYNTHETIC FIXTURE: European stock on Euronext Paris without explicit tickSize
        synthetic_no_tick: Dict[str, Any] = {
            "ticker": "SYNTH_NO_TICK_EQ",
            "type": "STOCK",
            "currencyCode": "EUR",
            "exchange_venue": "Euronext Paris",
            "minTradeQuantity": 1.0,
            "quantityPrecision": 0
        }
        caps = technical_execution_capability.evaluate_capabilities(synthetic_no_tick)
        tick_cap = caps["tick_rule"]
        self.assertEqual(tick_cap.status, "UNKNOWN")
        self.assertIsNone(tick_cap.value)
        self.assertEqual(tick_cap.evidence_level, "SYNTHETIC_FIXTURE_NOT_PROVEN")

        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(synthetic_no_tick)
        self.assertFalse(is_exec, "Unknown tick size must fail closed")
        self.assertIn("TICK_RULE_UNPROVEN", reason)

    def test_unknown_stop_support_fails_closed(self):
        """Prove instrument without empirical stop evidence fails closed."""
        # SYNTHETIC FIXTURE: US stock with valid qty and tick, but unproven stop support
        synthetic_no_stop: Dict[str, Any] = {
            "ticker": "AAPL_US_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "exchange_venue": "NASDAQ",
            "minTradeQuantity": 0.001,
            "quantityPrecision": 3,
            "tickSize": 0.01
        }
        caps = technical_execution_capability.evaluate_capabilities(synthetic_no_stop)
        stop_cap = caps["stop_support"]
        self.assertEqual(stop_cap.status, "UNPROVEN")
        self.assertIsNone(stop_cap.value)
        self.assertEqual(stop_cap.evidence_level, "UNPROVEN")

        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(synthetic_no_stop)
        self.assertFalse(is_exec, "Unevidenced stop support must fail closed")
        self.assertIn("STOP_SUPPORT_UNPROVEN", reason)

    def test_unknown_cost_completeness_fails_closed(self):
        """Prove instrument with incomplete or unproven transaction taxes/fees fails closed."""
        # SYNTHETIC FIXTURE: Italian instrument where Italian Tobin tax applicability on Trading212 is unverified
        synthetic_unknown_cost: Dict[str, Any] = {
            "ticker": "SYNTH_IT_EQ",
            "type": "STOCK",
            "currencyCode": "EUR",
            "exchange_venue": "Borsa Italiana",
            "isin": "IT0003132476",
            "minTradeQuantity": 1.0,
            "quantityPrecision": 0,
            "tickSize": 0.01
        }
        caps = technical_execution_capability.evaluate_capabilities(synthetic_unknown_cost)
        cost_cap = caps["cost_completeness"]
        self.assertIn(cost_cap.status, ("UNKNOWN", "INCOMPLETE"))

        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(synthetic_unknown_cost)
        self.assertFalse(is_exec, "Incomplete cost coverage must fail closed")
        self.assertIn("COST_COMPLETENESS_INCOMPLETE", reason)

    # =========================================================================
    # 3. INDEPENDENCE & PROVENANCE INVARIANTS (Section 2 & 4)
    # =========================================================================

    def test_capability_statuses_remain_independent(self):
        """Prove capability statuses remain completely decoupled for the same instrument."""
        # REAL EVIDENCED INSTRUMENT: IGLTl_EQ
        # Has proven stop support (order #54650651212) and complete cost model,
        # but quantity rule and broker tick size on Trading212 are UNKNOWN (absent from broker metadata).
        iglt_instrument: Dict[str, Any] = {
            "ticker": "IGLTl_EQ",
            "symbol": "IGLT",
            "type": "ETF",
            "currencyCode": "GBP",
            "exchange_venue": "London Stock Exchange",
            "isin": "IE00B1FZSB30",
        }
        caps = technical_execution_capability.evaluate_capabilities(iglt_instrument)
        self.assertEqual(caps["quantity_rule"].status, "UNKNOWN")
        self.assertEqual(caps["stop_support"].status, "PROVEN")
        self.assertEqual(caps["stop_support"].evidence_level, "EMPIRICAL_DEMO_PROVEN")
        self.assertEqual(caps["cost_completeness"].status, "COMPLETE")
        self.assertEqual(caps["tick_rule"].status, "UNKNOWN")

        # Verifier must fail closed because quantity_rule and tick_rule are UNKNOWN, despite stop_support being PROVEN
        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(iglt_instrument)
        self.assertFalse(is_exec)
        self.assertIn("QUANTITY_RULE_UNPROVEN", reason)
        self.assertIn("TICK_RULE_UNPROVEN", reason)

    def test_no_capability_proven_without_provenance(self):
        """Prove that any PROVEN or COMPLETE capability contains a verifiable provenance reference."""
        # Check IGLT stop provenance
        iglt_instrument = {
            "ticker": "IGLTl_EQ",
            "type": "ETF",
            "currencyCode": "GBP",
            "isin": "IE00B1FZSB30",
        }
        caps = technical_execution_capability.evaluate_capabilities(iglt_instrument)
        stop_cap = caps["stop_support"]
        self.assertEqual(stop_cap.status, "PROVEN")
        self.assertIsNotNone(stop_cap.provenance)
        self.assertIn("54650651212", stop_cap.provenance)
        self.assertEqual(stop_cap.evidence_level, "EMPIRICAL_DEMO_PROVEN")

        # Check US statutory tick provenance
        us_inst = {
            "ticker": "MSFT_US_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "exchange_venue": "NASDAQ",
            "price": 420.0
        }
        us_caps = technical_execution_capability.evaluate_capabilities(us_inst)
        tick_cap = us_caps["tick_rule"]
        # Regulatory tick is known under statutory Rule 612
        self.assertEqual(tick_cap.regulatory_tick_status, "REGULATORY_MINIMUM_INCREMENT_KNOWN")
        self.assertEqual(tick_cap.regulatory_tick_value, 0.01)
        self.assertEqual(tick_cap.regulatory_tick_source, "STATUTORY_RULE:17_CFR_242_612")
        # BUT broker tick rule is UNKNOWN (absent from Trading212 metadata)
        self.assertEqual(tick_cap.broker_tick_rule_status, "UNKNOWN")
        self.assertEqual(tick_cap.status, "UNKNOWN")

    def test_one_proven_capability_cannot_promote_another_capability(self):
        """Prove that having one or three capabilities PROVEN does not promote unproven capabilities."""
        # SYNTHETIC FIXTURE: Instrument with 3 simulated proven capabilities (qty, tick, cost) but unproven stop support
        synthetic_inst: Dict[str, Any] = {
            "ticker": "SYNTH_BARC_EQ",
            "symbol": "BARC",
            "type": "STOCK",
            "currencyCode": "GBX",
            "exchange_venue": "London Stock Exchange",
            "isin": "GB0031348658",
            "minTradeQuantity": 1.0,
            "quantityPrecision": 0,
            "tickSize": 0.1,
            "is_synthetic": True,
            "allow_synthetic_proven": True
        }
        caps = technical_execution_capability.evaluate_capabilities(synthetic_inst)
        self.assertEqual(caps["quantity_rule"].status, "PROVEN")
        self.assertEqual(caps["quantity_rule"].evidence_level, "SYNTHETIC_FIXTURE_NOT_PROVEN")
        self.assertEqual(caps["tick_rule"].status, "PROVEN")
        self.assertEqual(caps["tick_rule"].evidence_level, "SYNTHETIC_FIXTURE_NOT_PROVEN")
        self.assertEqual(caps["cost_completeness"].status, "COMPLETE")
        # Invariant: Proven quantity, tick, and cost DO NOT promote stop support
        self.assertEqual(caps["stop_support"].status, "UNPROVEN")
        self.assertIsNone(caps["stop_support"].provenance)

        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(synthetic_inst)
        self.assertFalse(is_exec)
        self.assertIn("STOP_SUPPORT_UNPROVEN", reason)

    def test_real_trading212_snapshot_lacks_quantity_and_tick_fields(self):
        """Prove real Trading212 metadata snapshot contains 10 keys and strictly lacks qty/tick fields."""
        import json
        with open("data/trading212_instruments_snapshot_20260917.json") as f:
            snapshot = json.load(f)

        self.assertEqual(len(snapshot), 17563)
        distinct_keys = set()
        for item in snapshot:
            distinct_keys.update(item.keys())

        expected_keys = {
            "addedOn", "currencyCode", "extendedHours", "isin", "maxOpenQuantity",
            "name", "shortName", "ticker", "type", "workingScheduleId"
        }
        self.assertEqual(distinct_keys, expected_keys)
        self.assertNotIn("minTradeQuantity", distinct_keys)
        self.assertNotIn("quantityPrecision", distinct_keys)
        self.assertNotIn("tickSize", distinct_keys)

    def test_synthetic_fixture_cannot_establish_read_only_real_data_proven(self):
        """Prove a synthetic test fixture cannot establish READ_ONLY_REAL_DATA_PROVEN."""
        synthetic_fixture: Dict[str, Any] = {
            "ticker": "SYNTH_TEST_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "minTradeQuantity": 0.001,
            "quantityPrecision": 3,
            "tickSize": 0.01,
            "is_synthetic": True,
            "allow_synthetic_proven": True
        }
        caps = technical_execution_capability.evaluate_capabilities(synthetic_fixture)
        self.assertNotEqual(caps["quantity_rule"].evidence_level, "READ_ONLY_REAL_DATA_PROVEN")
        self.assertEqual(caps["quantity_rule"].evidence_level, "SYNTHETIC_FIXTURE_NOT_PROVEN")
        self.assertNotEqual(caps["tick_rule"].evidence_level, "READ_ONLY_REAL_DATA_PROVEN")
        self.assertEqual(caps["tick_rule"].evidence_level, "SYNTHETIC_FIXTURE_NOT_PROVEN")

    def test_regulatory_tick_separated_from_broker_tick(self):
        """Prove US Rule 612 sets regulatory increment known while broker tick rule remains UNKNOWN."""
        us_equity: Dict[str, Any] = {
            "ticker": "AAPL_US_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "exchange_venue": "NASDAQ",
            "price": 150.0
        }
        caps = technical_execution_capability.evaluate_capabilities(us_equity)
        tick_state = caps["tick_rule"]

        # 1. Regulatory tick is known under 17 CFR § 242.612
        self.assertEqual(tick_state.regulatory_tick_status, "REGULATORY_MINIMUM_INCREMENT_KNOWN")
        self.assertEqual(tick_state.regulatory_tick_value, 0.01)
        self.assertEqual(tick_state.regulatory_tick_source, "STATUTORY_RULE:17_CFR_242_612")

        # 2. Broker tick rule is UNKNOWN (absent from Trading212 metadata)
        self.assertEqual(tick_state.broker_tick_rule_status, "UNKNOWN")
        self.assertIsNone(tick_state.broker_tick_rule_value)
        self.assertEqual(tick_state.broker_tick_rule_source, "UNAVAILABLE:ABSENT_FROM_TRADING212_METADATA")

        # 3. Gate evaluates broker tick rule, so overall tick_rule status is UNKNOWN
        self.assertEqual(tick_state.status, "UNKNOWN")

        # 4. Verifier fails closed on broker tick rule
        is_exec, reason, _ = technical_execution_capability.verify_execution_capabilities(us_equity)
        self.assertFalse(is_exec)
        self.assertIn("TICK_RULE_UNPROVEN", reason)

    def test_iglt_stop_evidence_level_empirical_demo_proven(self):
        """Prove IGLT stop order is EMPIRICAL_DEMO_PROVEN and component level is TESTED."""
        self.assertEqual(technical_execution_capability.COMPONENT_EVIDENCE_LEVEL, "TESTED")
        reg_entry = technical_execution_capability.STOP_SUPPORT_REGISTRY["IGLTl_EQ"]
        self.assertEqual(reg_entry["status"], "PROVEN")
        self.assertEqual(reg_entry["evidence"], "EMPIRICAL_DEMO_STOP_ORDER")
        self.assertEqual(reg_entry["evidence_level"], "EMPIRICAL_DEMO_PROVEN")
        self.assertEqual(reg_entry["order_id"], 54650651212)

        caps = technical_execution_capability.evaluate_capabilities({"ticker": "IGLTl_EQ"})
        self.assertEqual(caps["stop_support"].status, "PROVEN")
        self.assertEqual(caps["stop_support"].evidence_level, "EMPIRICAL_DEMO_PROVEN")

    # =========================================================================
    # 4. ARCHITECTURAL ISOLATION: ZERO BROKER WRITES & NO STRATEGY (Section 3)
    # =========================================================================

    def test_zero_broker_writes_occur_from_capability_evaluator(self):
        """Prove that capability evaluation performs zero HTTP mutations or broker writes."""
        from src.brokers.trading212 import broker
        with patch.object(broker, "_request_with_retry") as mock_req:
            # Execute capability evaluation across multiple instruments
            test_items = [
                {"ticker": "AAPL_US_EQ", "type": "STOCK", "currencyCode": "USD"},
                {"ticker": "IGLTl_EQ", "type": "ETF", "currencyCode": "GBP", "minTradeQuantity": 1.0, "tickSize": 0.01},
                {"ticker": "BARCl_EQ", "type": "STOCK", "currencyCode": "GBX"}
            ]
            for item in test_items:
                technical_execution_capability.evaluate_capabilities(item)
                technical_execution_capability.verify_execution_capabilities(item)
                technical_execution_capability.validate(item)
                broker_discovery.evaluate_tradability(item)

            # Assert zero mutating calls occurred
            mock_req.assert_not_called()

    def test_no_strategy_decision_introduced_by_capability_layer(self):
        """Prove capability verifier outputs only mechanical flags, with zero trading strategy rules."""
        sample_inst: Dict[str, Any] = {
            "ticker": "IGLTl_EQ",
            "type": "ETF",
            "currencyCode": "GBP",
            "minTradeQuantity": 1.0,
            "quantityPrecision": 0,
            "tickSize": 0.01
        }
        is_exec, reason, caps = technical_execution_capability.verify_execution_capabilities(sample_inst)
        cap_dict = {k: v.to_dict() for k, v in caps.items()}

        # Verify no strategy fields exist
        for field in ("opportunity_score", "weight", "allocation", "target_quantity", "action", "signal", "rank"):
            self.assertNotIn(field, cap_dict)

        # Output contains only mechanical capability metadata
        for cap_name in ("quantity_rule", "tick_rule", "stop_support", "cost_completeness"):
            self.assertIn(cap_name, cap_dict)
            self.assertIn("status", cap_dict[cap_name])
            self.assertIn("evidence_level", cap_dict[cap_name])
            self.assertIn("source", cap_dict[cap_name])


if __name__ == "__main__":
    unittest.main()
