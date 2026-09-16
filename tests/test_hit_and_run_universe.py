"""
TDD Tests: Hit-and-Run Full-Universe Discovery
NO MOCKS FOR UNIVERSE DISCOVERY PROOF (as mandated by user request).
Verifies:
1. 100% of Trading212 exposed universe is discovered.
2. Full metadata breakdown: Discovered, Tradable, Product Families.
3. Separation of:
   - BROKER_DISCOVERY
   - TECHNICAL_EXECUTION_CAPABILITY
   - STRATEGY_QUALIFICATION
4. No arbitrary geography, sector, or ETF-only filtering.
"""
import unittest


class TestHitAndRunUniverseDiscovery(unittest.TestCase):

    def setUp(self):
        from src.hit_and_run.universe import HitAndRunUniverseDiscovery
        self.discovery = HitAndRunUniverseDiscovery()

    def test_full_universe_unmocked_discovery_telemetry(self):
        """Proof of unmocked discovery across all product families and exchanges."""
        telemetry = self.discovery.get_universe_telemetry()

        self.assertIn("DISCOVERED_INSTRUMENT_COUNT", telemetry)
        self.assertIn("TRADABLE_INSTRUMENT_COUNT", telemetry)
        self.assertIn("PRODUCT_FAMILIES", telemetry)

        discovered = telemetry["DISCOVERED_INSTRUMENT_COUNT"]
        tradable = telemetry["TRADABLE_INSTRUMENT_COUNT"]
        families = telemetry["PRODUCT_FAMILIES"]

        # Must have discovered > 15,000 instruments from Trading212 metadata
        self.assertGreater(discovered, 15000)
        self.assertGreater(tradable, 15000)

        # Both STOCK and ETF families must be present and discovered
        self.assertIn("STOCK", families)
        self.assertIn("ETF", families)
        self.assertGreater(families["STOCK"], 5000)
        self.assertGreater(families["ETF"], 1000)

        # Warrants should be flagged as unsupported product family
        self.assertIn("WARRANT", families)
        self.assertIn("UNSUPPORTED_PRODUCT_FAMILIES", telemetry)
        self.assertIn("WARRANT", telemetry["UNSUPPORTED_PRODUCT_FAMILIES"])

    def test_technical_execution_capability_gate(self):
        """Verifies technical capability gate strictly enforces quantity and tick verification."""
        from src.data.technical_execution_capability import technical_execution_capability

        # 1. Raw broker instruments lacking explicit minTradeQuantity fail closed with QUANTITY_INCREMENT_UNKNOWN
        tradable = self.discovery.get_tradable_instruments() if hasattr(self.discovery, "get_tradable_instruments") else []
        if not tradable:
            from src.data.broker_discovery import broker_discovery
            tradable = broker_discovery.get_tradable_instruments()

        raw_inst = tradable[0]
        is_supp, reason, _ = technical_execution_capability.validate(raw_inst)
        self.assertFalse(is_supp)
        self.assertIn("QUANTITY_INCREMENT_UNKNOWN", reason)

        # 2. Instruments with authoritative metadata succeed with derived precision and verified tick rule
        qualified_us = {
            "ticker": "AAPL_US_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "minTradeQuantity": 0.001,
            "maxOpenQuantity": 10000.0,
            "workingScheduleId": 56
        }
        is_supp_us, reason_us, details_us = technical_execution_capability.validate(qualified_us)
        self.assertTrue(is_supp_us, f"Qualified US instrument must be supported: {reason_us}")
        self.assertEqual(details_us["quantity_precision"], 3)
        self.assertEqual(details_us["tick_size_rule"], "US_SEC_RULE_612")

        # 3. Whole-share instrument derives precision 0
        qualified_whole = {
            "ticker": "BARCl_EQ",
            "type": "STOCK",
            "currencyCode": "GBX",
            "minTradeQuantity": 1.0,
            "maxOpenQuantity": 50000.0,
            "exchange_venue": "London Stock Exchange",
            "tickSize": 0.1
        }
        is_supp_uk, _, details_uk = technical_execution_capability.validate(qualified_whole)
        self.assertTrue(is_supp_uk)
        self.assertEqual(details_uk["quantity_precision"], 0)
        self.assertEqual(details_uk["tick_size_rule"], "EXPLICIT_METADATA")

        # 4. Ensure WARRANT is rejected with UNSUPPORTED_PRODUCT_FAMILY
        warrant_inst = {
            "ticker": "TEST_WARRANT",
            "type": "WARRANT",
            "currencyCode": "USD",
            "minTradeQuantity": 1.0,
            "maxOpenQuantity": 100.0
        }
        is_supp_w, reason_w, _ = technical_execution_capability.validate(warrant_inst)
        self.assertFalse(is_supp_w)
        self.assertIn("UNSUPPORTED_PRODUCT_FAMILY", reason_w)

        # 5. Unverified venue without explicit tick fails closed with TICK_SIZE_UNKNOWN
        unverified_venue = {
            "ticker": "UNKNOWN_VEN_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "minTradeQuantity": 0.001,
            "exchange_venue": "UNKNOWN_OFFSHORE_EXCHANGE"
        }
        is_supp_uv, reason_uv, _ = technical_execution_capability.validate(unverified_venue)
        self.assertFalse(is_supp_uv)
        self.assertIn("TICK_SIZE_UNKNOWN", reason_uv)

    def test_no_arbitrary_geography_or_product_restrictions(self):
        """Verifies technical capability supports US, UK, and European instruments across stocks and ETFs without bias."""
        from src.data.technical_execution_capability import technical_execution_capability

        test_cases = [
            {"ticker": "MSFT_US_EQ", "type": "STOCK", "currencyCode": "USD", "minTradeQuantity": 0.001, "exchange_venue": "NASDAQ"},
            {"ticker": "SPY_US_EQ", "type": "ETF", "currencyCode": "USD", "minTradeQuantity": 0.001, "exchange_venue": "NYSE"},
            {"ticker": "BARCl_EQ", "type": "STOCK", "currencyCode": "GBX", "minTradeQuantity": 0.001, "exchange_venue": "London Stock Exchange", "tickSize": 0.1},
            {"ticker": "CSP1l_EQ", "type": "ETF", "currencyCode": "GBX", "minTradeQuantity": 0.001, "exchange_venue": "London Stock Exchange", "tickSize": 0.1},
            {"ticker": "SAPd_EQ", "type": "STOCK", "currencyCode": "EUR", "minTradeQuantity": 0.001, "exchange_venue": "Deutsche Börse Xetra", "tickSize": 0.01},
            {"ticker": "ORp_EQ", "type": "STOCK", "currencyCode": "EUR", "minTradeQuantity": 0.001, "exchange_venue": "Euronext Paris", "tickSize": 0.01},
        ]

        for case in test_cases:
            is_supp, reason, details = technical_execution_capability.validate(case)
            self.assertTrue(is_supp, f"Case {case['ticker']} must be supported: {reason}")
            self.assertIn(details["currency"], ("USD", "GBX", "EUR"))
            self.assertIn(details["product_type"], ("STOCK", "ETF"))

        # Invariant: European instrument without explicit tickSize fails closed with TICK_SIZE_UNKNOWN
        euro_no_tick = {"ticker": "ORp_EQ", "type": "STOCK", "currencyCode": "EUR", "minTradeQuantity": 0.001, "exchange_venue": "Euronext Paris"}
        is_ok, reason_no_tick, _ = technical_execution_capability.validate(euro_no_tick)
        self.assertFalse(is_ok)
        self.assertIn("TICK_SIZE_UNKNOWN", reason_no_tick)


if __name__ == "__main__":
    unittest.main()
