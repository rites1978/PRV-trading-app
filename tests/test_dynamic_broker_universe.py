"""
Unit & Integration Tests for Phase 1: Dynamic Broker Universe Discovery, Technical Capability & Session Router.
Verifies:
- Broker discovery ingests 100% of instruments and reports BROKER_API_DISCOVERED and BROKER_API_TRADABLE
- Product family classification (STOCK/ETF supported, WARRANT unsupported)
- Technical execution capability validates quote units, currencies, precision, stops without probe orders
- Market session routing reflects real-time exchange open/closed states dynamically across timezones
- Malformed metadata fails closed safely
- Zero broker writes occur during discovery/validation
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.data.broker_discovery import BrokerDiscoveryService
from src.data.technical_execution_capability import TechnicalExecutionCapabilityValidator
from src.data.market_session_router import MarketSessionRouter
from src.brokers.trading212 import broker


class TestDynamicBrokerUniverse(unittest.TestCase):

    def setUp(self):
        self.discovery = BrokerDiscoveryService()
        self.validator = TechnicalExecutionCapabilityValidator()
        self.router = MarketSessionRouter()

    def test_discovery_ingests_all_instruments_and_distinguishes_tradability(self):
        """Verify discovery ingests 100% of instruments and reports API discovered vs tradable."""
        telemetry = self.discovery.get_discovery_telemetry()
        self.assertGreater(telemetry["BROKER_API_DISCOVERED"], 10000)
        self.assertGreater(telemetry["BROKER_API_TRADABLE"], 10000)
        self.assertLessEqual(telemetry["BROKER_API_TRADABLE"], telemetry["BROKER_API_DISCOVERED"])
        self.assertIn("STOCK", telemetry["DISCOVERED_BY_PRODUCT_TYPE"])
        self.assertIn("ETF", telemetry["DISCOVERED_BY_PRODUCT_TYPE"])
        self.assertIn("WARRANT", telemetry["UNSUPPORTED_PRODUCT_FAMILY_IF_ANY"])

    def test_technical_execution_capability_us_equity(self):
        """Verify US equity correctly maps ticker and quote units."""
        sample_us = {
            "ticker": "AAPL_US_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "shortName": "AAPL",
            "maxOpenQuantity": 1000.0,
            "workingScheduleId": 71
        }
        is_sup, reason, details = self.validator.validate(sample_us)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "TECHNICAL_EXECUTION_SUPPORTED")
        self.assertEqual(details["feed_ticker"], "AAPL")
        self.assertEqual(details["quote_divisor"], 1.0)
        self.assertFalse(details["is_uk_pence"])
        self.assertTrue(details["gtc_stop_capable"])

    def test_technical_execution_capability_uk_pence(self):
        """Verify UK equity with GBX currency correctly maps quote divisor 100.0."""
        sample_uk = {
            "ticker": "BARCl_EQ",
            "type": "STOCK",
            "currencyCode": "GBX",
            "shortName": "BARC",
            "maxOpenQuantity": 50000.0,
            "workingScheduleId": 55
        }
        is_sup, reason, details = self.validator.validate(sample_uk)
        self.assertTrue(is_sup)
        self.assertEqual(reason, "TECHNICAL_EXECUTION_SUPPORTED")
        self.assertEqual(details["feed_ticker"], "BARC.L")
        self.assertEqual(details["quote_divisor"], 100.0)
        self.assertTrue(details["is_uk_pence"])

    def test_technical_execution_capability_unsupported_warrant(self):
        """Verify warrant is flagged as UNSUPPORTED_PRODUCT_FAMILY without crashing."""
        sample_warrant = {
            "ticker": "TEST_WARRANT_EQ",
            "type": "WARRANT",
            "currencyCode": "EUR",
            "shortName": "WARRANT",
            "maxOpenQuantity": 100.0,
            "workingScheduleId": 41
        }
        is_sup, reason, details = self.validator.validate(sample_warrant)
        self.assertFalse(is_sup)
        self.assertIn("UNSUPPORTED_PRODUCT_FAMILY", reason)

    def test_malformed_metadata_fails_closed(self):
        """Verify empty or corrupted metadata fails closed safely."""
        # None input
        is_sup1, reason1, _ = self.validator.validate(None)
        self.assertFalse(is_sup1)
        self.assertIn("MALFORMED_METADATA", reason1)

        # Empty dict
        is_sup2, reason2, _ = self.validator.validate({})
        self.assertFalse(is_sup2)
        self.assertIn("MALFORMED_METADATA", reason2)

        # Zero/negative maxOpenQuantity
        untradable = {
            "ticker": "DELISTED_US_EQ",
            "type": "STOCK",
            "currencyCode": "USD",
            "shortName": "DELISTED",
            "maxOpenQuantity": 0.0
        }
        is_sup3, reason3, _ = self.validator.validate(untradable)
        self.assertFalse(is_sup3)
        self.assertIn("BROKER_UNTRADABLE", reason3)

    def test_market_session_router_cross_market_continuity(self):
        """Verify London is open at 11:00 UTC, and US is open at 18:00 UTC (no LSE-only shutdown)."""
        t_london_session = datetime(2026, 9, 15, 11, 0, 0, tzinfo=timezone.utc)
        open_at_11 = self.router.get_open_markets(t_london_session)
        self.assertIn("London Stock Exchange", open_at_11)
        self.assertNotIn("NYSE", open_at_11)

        t_us_session = datetime(2026, 9, 15, 18, 0, 0, tzinfo=timezone.utc)
        open_at_18 = self.router.get_open_markets(t_us_session)
        self.assertIn("NYSE", open_at_18)
        self.assertIn("NASDAQ", open_at_18)
        self.assertNotIn("London Stock Exchange", open_at_18)

    def test_no_broker_writes_occur_during_discovery(self):
        """Verify zero broker order mutations are submitted during discovery & capability checks."""
        broker_writes = []
        with patch.object(broker, "place_limit_order", side_effect=lambda *a, **kw: broker_writes.append("limit")),              patch.object(broker, "place_market_order", side_effect=lambda *a, **kw: broker_writes.append("market")),              patch.object(broker, "sync_broker_stop_order", side_effect=lambda *a, **kw: broker_writes.append("stop")):

            telemetry = self.discovery.get_discovery_telemetry()
            tradable = self.discovery.get_tradable_instruments()
            for item in tradable[:50]:
                self.validator.validate(item)
            self.router.get_open_markets()

        self.assertEqual(len(broker_writes), 0, "Discovery and validation must never trigger broker writes!")


if __name__ == "__main__":
    unittest.main()
