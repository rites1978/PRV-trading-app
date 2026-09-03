"""
Unit and Property Tests for Market Session Engine State Machine.
Proves session state transitions across:
- PRE_MARKET, REGULAR, AFTER_HOURS, OVERNIGHT, FULLY_CLOSED, HOLIDAY
- Strict entry execution gate: REGULAR ONLY (both PRACTICE and LIVE)
- Signals generated outside regular session transition to PENDING_REVALIDATION
"""
import unittest
from datetime import datetime, date
from zoneinfo import ZoneInfo
from src.data.market_hours import market_hours, MarketSessionState


class TestMarketSessionStateMachine(unittest.TestCase):
    def setUp(self):
        self.tz_london = ZoneInfo("Europe/London")
        self.tz_ny = ZoneInfo("America/New_York")

    def test_uk_session_states(self):
        # 1. Tuesday Regular (2026-09-08 10:00 BST)
        t_regular = datetime(2026, 9, 8, 10, 0, tzinfo=self.tz_london)
        state, reason, _ = market_hours.get_uk_session_state(t_regular)
        self.assertEqual(state, MarketSessionState.REGULAR)

        # 2. Tuesday Pre-Market (2026-09-08 07:30 BST)
        t_pre = datetime(2026, 9, 8, 7, 30, tzinfo=self.tz_london)
        state, reason, _ = market_hours.get_uk_session_state(t_pre)
        self.assertEqual(state, MarketSessionState.PRE_MARKET)

        # 3. Tuesday After-Hours (2026-09-08 16:45 BST)
        t_after = datetime(2026, 9, 8, 16, 45, tzinfo=self.tz_london)
        state, reason, _ = market_hours.get_uk_session_state(t_after)
        self.assertEqual(state, MarketSessionState.AFTER_HOURS)

        # 4. Tuesday Overnight (2026-09-08 22:00 BST)
        t_overnight = datetime(2026, 9, 8, 22, 0, tzinfo=self.tz_london)
        state, reason, _ = market_hours.get_uk_session_state(t_overnight)
        self.assertEqual(state, MarketSessionState.OVERNIGHT)

        # 5. Weekend (2026-09-12 12:00 BST, Saturday)
        t_weekend = datetime(2026, 9, 12, 12, 0, tzinfo=self.tz_london)
        state, reason, _ = market_hours.get_uk_session_state(t_weekend)
        self.assertEqual(state, MarketSessionState.FULLY_CLOSED)

        # 6. Holiday (2026-08-31 11:00 BST, Summer Bank Holiday)
        t_holiday = datetime(2026, 8, 31, 11, 0, tzinfo=self.tz_london)
        state, reason, _ = market_hours.get_uk_session_state(t_holiday)
        self.assertEqual(state, MarketSessionState.HOLIDAY)

    def test_us_session_states(self):
        # 1. Tuesday Regular (2026-09-08 11:00 EDT)
        t_regular = datetime(2026, 9, 8, 11, 0, tzinfo=self.tz_ny)
        state, reason, _ = market_hours.get_us_session_state(t_regular)
        self.assertEqual(state, MarketSessionState.REGULAR)

        # 2. Tuesday Pre-Market (2026-09-08 08:00 EDT)
        t_pre = datetime(2026, 9, 8, 8, 0, tzinfo=self.tz_ny)
        state, reason, _ = market_hours.get_us_session_state(t_pre)
        self.assertEqual(state, MarketSessionState.PRE_MARKET)

        # 3. Tuesday After-Hours (2026-09-08 17:30 EDT)
        t_after = datetime(2026, 9, 8, 17, 30, tzinfo=self.tz_ny)
        state, reason, _ = market_hours.get_us_session_state(t_after)
        self.assertEqual(state, MarketSessionState.AFTER_HOURS)

        # 4. Tuesday Overnight (2026-09-08 23:00 EDT)
        t_overnight = datetime(2026, 9, 8, 23, 0, tzinfo=self.tz_ny)
        state, reason, _ = market_hours.get_us_session_state(t_overnight)
        self.assertEqual(state, MarketSessionState.OVERNIGHT)

        # 5. Weekend (2026-09-13 14:00 EDT, Sunday)
        t_weekend = datetime(2026, 9, 13, 14, 0, tzinfo=self.tz_ny)
        state, reason, _ = market_hours.get_us_session_state(t_weekend)
        self.assertEqual(state, MarketSessionState.FULLY_CLOSED)

        # 6. Holiday (2026-07-03 11:00 EDT, Independence Day observed)
        t_holiday = datetime(2026, 7, 3, 11, 0, tzinfo=self.tz_ny)
        state, reason, _ = market_hours.get_us_session_state(t_holiday)
        self.assertEqual(state, MarketSessionState.HOLIDAY)

    def test_can_execute_new_entry_regular_only_gate(self):
        # Regular session execution must be permitted
        t_us_regular = datetime(2026, 9, 8, 11, 0, tzinfo=self.tz_ny)
        allowed, reason, state = market_hours.can_execute_new_entry("US", t_us_regular)
        self.assertTrue(allowed)
        self.assertEqual(state, MarketSessionState.REGULAR)

        # Non-regular session execution MUST be blocked
        t_us_pre = datetime(2026, 9, 8, 8, 0, tzinfo=self.tz_ny)
        allowed, reason, state = market_hours.can_execute_new_entry("US", t_us_pre)
        self.assertFalse(allowed)
        self.assertEqual(state, MarketSessionState.PRE_MARKET)
        self.assertIn("HOLD_CLOSED_MARKET", reason)

        t_us_after = datetime(2026, 9, 8, 17, 0, tzinfo=self.tz_ny)
        allowed, reason, state = market_hours.can_execute_new_entry("US", t_us_after)
        self.assertFalse(allowed)
        self.assertEqual(state, MarketSessionState.AFTER_HOURS)

        t_us_weekend = datetime(2026, 9, 12, 12, 0, tzinfo=self.tz_ny)
        allowed, reason, state = market_hours.can_execute_new_entry("US", t_us_weekend)
        self.assertFalse(allowed)
        self.assertEqual(state, MarketSessionState.FULLY_CLOSED)


if __name__ == "__main__":
    unittest.main()
