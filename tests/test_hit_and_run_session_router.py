"""
Unit Tests: Market Session Router and Extended Hours Metadata Model (Deliverable 2B)
Verifies:
1. Instrument metadata preserves extendedHours in technical execution capability details.
2. Multi-session states supported: PRE_MARKET, REGULAR, AFTER_HOURS, OVERNIGHT, CLOSED, UNKNOWN.
3. Distinction between REGULAR_SESSION_CLOSED and INSTRUMENT_NOT_TRADABLE_NOW.
4. Correct exposure of:
   - SESSION_OPEN_NOW
   - EXTENDED_HOURS_ELIGIBLE
   - EXECUTION_SESSION
   - NEXT_SESSION_TRANSITION
5. Exact universe replay at 2026-09-16T21:53:31Z proving 5,268 open after-hours instruments.
"""
import unittest
from datetime import datetime, timezone
import json
import os

from src.data.broker_discovery import broker_discovery
from src.data.market_session_router import market_session_router
from src.data.technical_execution_capability import technical_execution_capability
from src.hit_and_run.opportunity_state import opportunity_state_builder


class TestMarketSessionRouter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        broker_discovery.initialize()

    def test_extended_hours_preservation_in_metadata_and_validation(self):
        """Audit that extendedHours boolean is preserved across technical validation."""
        inst_ext_true = {
            "ticker": "AAPL_US_EQ",
            "name": "Apple Inc",
            "type": "STOCK",
            "currencyCode": "USD",
            "minTradeQuantity": 0.001,
            "maxOpenQuantity": 100000.0,
            "workingScheduleId": 107,
            "extendedHours": True,
            "isin": "US0378331005"
        }
        supported, reason, details = technical_execution_capability.validate(inst_ext_true)
        self.assertTrue(supported, f"Validation failed: {reason}")
        self.assertIn("extended_hours", details)
        self.assertTrue(details["extended_hours"])

        inst_ext_false = dict(inst_ext_true)
        inst_ext_false["extendedHours"] = False
        supported2, _, details2 = technical_execution_capability.validate(inst_ext_false)
        self.assertTrue(supported2)
        self.assertIn("extended_hours", details2)
        self.assertFalse(details2["extended_hours"])

    def test_regular_session_active(self):
        """During regular NYSE hours (e.g. 15:00 UTC), both extended and non-extended are open."""
        utc_dt = datetime(2026, 9, 16, 15, 0, 0, tzinfo=timezone.utc)
        inst_ext_true = {"workingScheduleId": 107, "extendedHours": True}
        inst_ext_false = {"workingScheduleId": 107, "extendedHours": False}

        d_true = market_session_router.get_instrument_session_details(inst_ext_true, utc_dt=utc_dt)
        d_false = market_session_router.get_instrument_session_details(inst_ext_false, utc_dt=utc_dt)

        self.assertTrue(d_true["session_open_now"])
        self.assertEqual(d_true["execution_session"], "REGULAR")
        self.assertFalse(d_true["regular_session_closed"])
        self.assertFalse(d_true["instrument_not_tradable_now"])
        self.assertIsNotNone(d_true["next_session_transition"])

        self.assertTrue(d_false["session_open_now"])
        self.assertEqual(d_false["execution_session"], "REGULAR")
        self.assertFalse(d_false["regular_session_closed"])
        self.assertFalse(d_false["instrument_not_tradable_now"])

    def test_after_hours_session_distinguishes_eligibility(self):
        """During after-hours (21:53 UTC), only extendedHours=True instruments are tradable."""
        utc_dt = datetime(2026, 9, 16, 21, 53, 31, tzinfo=timezone.utc)
        inst_ext_true = {"workingScheduleId": 107, "extendedHours": True}
        inst_ext_false = {"workingScheduleId": 107, "extendedHours": False}

        d_true = market_session_router.get_instrument_session_details(inst_ext_true, utc_dt=utc_dt)
        d_false = market_session_router.get_instrument_session_details(inst_ext_false, utc_dt=utc_dt)

        # Extended-eligible instrument IS tradable now in AFTER_HOURS
        self.assertTrue(d_true["session_open_now"])
        self.assertTrue(d_true["extended_hours_eligible"])
        self.assertEqual(d_true["execution_session"], "AFTER_HOURS")
        self.assertTrue(d_true["regular_session_closed"])
        self.assertFalse(d_true["instrument_not_tradable_now"])
        self.assertEqual(d_true["next_session_transition"]["timestamp"], "2026-09-17T00:00:00.000Z")

        # Non-extended instrument IS NOT tradable now
        self.assertFalse(d_false["session_open_now"])
        self.assertFalse(d_false["extended_hours_eligible"])
        self.assertEqual(d_false["execution_session"], "CLOSED")
        self.assertTrue(d_false["regular_session_closed"])
        self.assertTrue(d_false["instrument_not_tradable_now"])
        self.assertIn("REGULAR_SESSION_CLOSED", d_false["status_reason"])
        self.assertIn("INSTRUMENT_NOT_TRADABLE_NOW", d_false["status_reason"])

    def test_closed_market_session(self):
        """When the exchange itself is closed (e.g. LSE at 21:53 UTC), neither is tradable."""
        utc_dt = datetime(2026, 9, 16, 21, 53, 31, tzinfo=timezone.utc)
        inst_lse = {"workingScheduleId": 55, "extendedHours": False}

        d_lse = market_session_router.get_instrument_session_details(inst_lse, utc_dt=utc_dt)
        self.assertFalse(d_lse["session_open_now"])
        self.assertEqual(d_lse["execution_session"], "CLOSED")
        self.assertTrue(d_lse["regular_session_closed"])
        self.assertTrue(d_lse["instrument_not_tradable_now"])
        self.assertIn("MARKET_CLOSED", d_lse["status_reason"])

    def test_universe_replay_at_2026_09_16_21_53_31_utc(self):
        """
        Authoritative re-evaluation of 100% of discovered tradable instruments at 2026-09-16T21:53:31Z.
        Proves that 5,268 instruments were actively open in AFTER_HOURS.
        """
        utc_dt = datetime(2026, 9, 16, 21, 53, 31, tzinfo=timezone.utc)
        tradable = broker_discovery.get_tradable_instruments()
        self.assertEqual(len(tradable), 17441)

        counts = {
            "REGULAR": 0,
            "PRE_MARKET": 0,
            "AFTER_HOURS": 0,
            "OVERNIGHT": 0,
            "CLOSED": 0,
            "UNKNOWN": 0
        }
        open_now_count = 0

        for inst in tradable:
            details = market_session_router.get_instrument_session_details(inst, utc_dt=utc_dt)
            sess = details["execution_session"]
            counts[sess] = counts.get(sess, 0) + 1
            if details["session_open_now"]:
                open_now_count += 1

        self.assertEqual(counts["REGULAR"], 0)
        self.assertEqual(counts["PRE_MARKET"], 0)
        self.assertEqual(counts["AFTER_HOURS"], 5268)
        self.assertEqual(counts["OVERNIGHT"], 0)
        self.assertEqual(counts["CLOSED"], 12173)
        self.assertEqual(counts["UNKNOWN"], 0)
        self.assertEqual(open_now_count, 5268)
        self.assertEqual(counts["AFTER_HOURS"] + counts["CLOSED"], 17441)

    def test_live_opportunity_state_builder_hydrates_session_fields(self):
        """Ensures LiveOpportunityState correctly reflects session details."""
        utc_dt = datetime(2026, 9, 16, 21, 53, 31, tzinfo=timezone.utc)
        inst_meta = {
            "ticker": "NVDA_US_EQ",
            "name": "NVIDIA",
            "workingScheduleId": 109,
            "extendedHours": True,
            "currencyCode": "USD",
            "minTradeQuantity": 0.001,
            "maxOpenQuantity": 50000.0
        }
        snap = {
            "instrument_id": "NVDA_US_EQ",
            "current_price": 120.0,
            "bid": 119.95,
            "ask": 120.05
        }
        state = opportunity_state_builder.build_state(snap, instrument_meta=inst_meta, utc_dt=utc_dt)
        self.assertTrue(state.session_open)
        self.assertTrue(state.extended_hours_eligible)
        self.assertEqual(state.execution_session, "AFTER_HOURS")
        self.assertIsNotNone(state.next_session_transition)
        self.assertEqual(state.next_session_transition["event_type"], "OVERNIGHT_OPEN")


if __name__ == "__main__":
    unittest.main()
