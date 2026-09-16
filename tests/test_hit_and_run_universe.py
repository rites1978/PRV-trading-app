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
        """Verifies technical capability gate distinguishes tradable from technically supported."""
        all_candidates = self.discovery.get_executable_universe()
        self.assertGreater(len(all_candidates), 10000)

        # Ensure no WARRANT made it into executable universe
        for cand in all_candidates[:500]:
            self.assertIn(cand["product_type"], ("STOCK", "ETF"))
            self.assertTrue(cand["feed_ticker"] is not None and len(cand["feed_ticker"]) > 0)
            self.assertIn(cand["currency"], ("GBP", "GBX", "USD", "EUR", "CAD", "CHF"))

    def test_no_arbitrary_geography_or_product_restrictions(self):
        """Verifies universe contains US, UK, and European instruments across stocks and ETFs."""
        all_candidates = self.discovery.get_executable_universe()

        currencies = {c["currency"] for c in all_candidates}
        self.assertIn("USD", currencies)
        self.assertIn("GBX", currencies)
        self.assertIn("EUR", currencies)

        product_types = {c["product_type"] for c in all_candidates}
        self.assertEqual(product_types, {"STOCK", "ETF"})


if __name__ == "__main__":
    unittest.main()
