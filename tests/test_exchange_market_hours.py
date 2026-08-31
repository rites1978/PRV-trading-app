"""
🏛️ PRV CAPITAL | EXCHANGE MARKET HOURS & HOLIDAY CALENDAR TEST SUITE
Verifies:
1. LSE (UK) and NYSE/NASDAQ (US) Holiday Calendars
2. Dynamic Easter and Bank Holiday Substitutions
3. Accurate Market Open/Closed State and Closure Reason Resolution
4. 2026-08-31 UK Summer Bank Holiday Detection (UK Closed, US Open)
5. 08:30 Readiness Gate Automated Holiday Validation
"""
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from main import app
from src.data.exchange_calendar import exchange_calendar, get_easter_sunday
from src.data.market_hours import market_hours
from src.monitoring.production_readiness_gate import readiness_gate


class TestExchangeMarketHours(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tz_london = ZoneInfo("Europe/London")
        self.tz_ny = ZoneInfo("America/New_York")

    def test_01_easter_sunday_calculation(self):
        """Verify Meeus/Jones/Butcher algorithm across multiple years."""
        self.assertEqual(get_easter_sunday(2024), date(2024, 3, 31))
        self.assertEqual(get_easter_sunday(2025), date(2025, 4, 20))
        self.assertEqual(get_easter_sunday(2026), date(2026, 4, 5))
        self.assertEqual(get_easter_sunday(2027), date(2027, 3, 28))

    def test_02_uk_lse_2026_holidays(self):
        """Verify UK LSE Bank Holidays for 2026 including Aug 31 Summer Bank Holiday."""
        uk_hols_2026 = exchange_calendar.get_uk_lse_holidays(2026)
        
        # Must contain all 8 official bank holidays
        self.assertGreaterEqual(len(uk_hols_2026), 8)
        self.assertIn(date(2026, 1, 1), uk_hols_2026)    # New Year's Day
        self.assertIn(date(2026, 4, 3), uk_hols_2026)    # Good Friday
        self.assertIn(date(2026, 4, 6), uk_hols_2026)    # Easter Monday
        self.assertIn(date(2026, 5, 4), uk_hols_2026)    # Early May Bank Holiday
        self.assertIn(date(2026, 5, 25), uk_hols_2026)   # Spring Bank Holiday
        self.assertIn(date(2026, 8, 31), uk_hols_2026)   # Summer Bank Holiday
        self.assertIn(date(2026, 12, 25), uk_hols_2026)  # Christmas Day
        self.assertIn(date(2026, 12, 28), uk_hols_2026)  # Boxing Day (Observed Mon)

        self.assertEqual(exchange_calendar.get_uk_holiday_name(date(2026, 8, 31)), "Summer Bank Holiday")
        self.assertTrue(exchange_calendar.is_uk_holiday(date(2026, 8, 31)))

    def test_03_us_nyse_2026_holidays(self):
        """Verify US NYSE / NASDAQ Holidays for 2026."""
        us_hols_2026 = exchange_calendar.get_us_nyse_holidays(2026)
        
        self.assertGreaterEqual(len(us_hols_2026), 10)
        self.assertIn(date(2026, 1, 1), us_hols_2026)    # New Year's Day
        self.assertIn(date(2026, 1, 19), us_hols_2026)   # MLK Day
        self.assertIn(date(2026, 2, 16), us_hols_2026)   # Presidents' Day
        self.assertIn(date(2026, 4, 3), us_hols_2026)    # Good Friday
        self.assertIn(date(2026, 5, 25), us_hols_2026)   # Memorial Day
        self.assertIn(date(2026, 6, 19), us_hols_2026)   # Juneteenth
        self.assertIn(date(2026, 7, 3), us_hols_2026)    # Independence Day (Observed Fri)
        self.assertIn(date(2026, 9, 7), us_hols_2026)    # Labor Day
        self.assertIn(date(2026, 11, 26), us_hols_2026)  # Thanksgiving
        self.assertIn(date(2026, 12, 25), us_hols_2026)  # Christmas Day

        # 2026-08-31 is NOT a US holiday
        self.assertIsNone(exchange_calendar.get_us_holiday_name(date(2026, 8, 31)))
        self.assertFalse(exchange_calendar.is_us_holiday(date(2026, 8, 31)))

    def test_04_aug_31_2026_status_resolution(self):
        """
        Verify that on 2026-08-31 during afternoon trading hours:
        - UK Market is CLOSED due to Summer Bank Holiday
        - US Market is OPEN
        - Headline is 'US MARKET OPEN'
        - Asset routing returns False for UK and True for US
        """
        # Test simulated timestamp: 2026-08-31 14:30 London / 09:30 NY
        sim_dt_uk = datetime(2026, 8, 31, 14, 30, tzinfo=self.tz_london)
        sim_dt_us = datetime(2026, 8, 31, 9, 30, tzinfo=self.tz_ny)

        uk_status = market_hours.get_uk_market_status(sim_dt_uk)
        us_status = market_hours.get_us_market_status(sim_dt_us)

        self.assertFalse(uk_status["is_open"])
        self.assertEqual(uk_status["status"], "UK MARKET CLOSED (Summer Bank Holiday)")
        self.assertEqual(uk_status["reason"], "Summer Bank Holiday")
        self.assertTrue(uk_status["is_holiday"])

        self.assertTrue(us_status["is_open"])
        self.assertEqual(us_status["status"], "US MARKET OPEN")
        self.assertEqual(us_status["reason"], "Regular Trading Hours")
        self.assertFalse(us_status["is_holiday"])

    def test_05_weekend_and_pre_post_market_reasons(self):
        """Verify accurate closure reasons for weekend and outside trading hours."""
        # Weekend (Saturday)
        sat_uk = datetime(2026, 8, 29, 12, 0, tzinfo=self.tz_london)
        sat_us = datetime(2026, 8, 29, 12, 0, tzinfo=self.tz_ny)
        self.assertEqual(market_hours.get_uk_market_status(sat_uk)["reason"], "Weekend")
        self.assertEqual(market_hours.get_us_market_status(sat_us)["reason"], "Weekend")

        # Pre-Market (07:00 London / 08:00 NY on a normal Tuesday)
        tue_pre_uk = datetime(2026, 9, 1, 7, 0, tzinfo=self.tz_london)
        tue_pre_us = datetime(2026, 9, 1, 8, 0, tzinfo=self.tz_ny)
        self.assertIn("Pre-Market", market_hours.get_uk_market_status(tue_pre_uk)["reason"])
        self.assertIn("Pre-Market", market_hours.get_us_market_status(tue_pre_us)["reason"])

        # Post-Market (17:00 London / 17:00 NY on a normal Tuesday)
        tue_post_uk = datetime(2026, 9, 1, 17, 0, tzinfo=self.tz_london)
        tue_post_us = datetime(2026, 9, 1, 17, 0, tzinfo=self.tz_ny)
        self.assertIn("Post-Market", market_hours.get_uk_market_status(tue_post_uk)["reason"])
        self.assertIn("Post-Market", market_hours.get_us_market_status(tue_post_us)["reason"])

    def test_06_api_endpoints_return_market_status(self):
        """Verify API endpoints /api/monitoring/market_hours and /api/portfolio/fast_summary."""
        res_mh = self.client.get("/api/monitoring/market_hours")
        self.assertEqual(res_mh.status_code, 200)
        data_mh = res_mh.json()
        self.assertIn("uk", data_mh)
        self.assertIn("us", data_mh)
        self.assertIn("headline", data_mh)
        self.assertIn("reason_summary", data_mh)

        res_sum = self.client.get("/api/portfolio/summary_fast")
        self.assertEqual(res_sum.status_code, 200)
        data_sum = res_sum.json()
        self.assertIn("market_status", data_sum)
        self.assertIn("headline", data_sum["market_status"])

    def test_07_readiness_gate_automated_holiday_validation(self):
        """Verify 08:30 Readiness Gate verifies holiday calendars and exchange sessions."""
        gate_res = readiness_gate.evaluate_readiness_gate()
        self.assertEqual(gate_res["overall_status"], "READY FOR TRADING")
        
        data_suite = gate_res["verification_suites"]["3_data"]
        self.assertEqual(data_suite["status"], "PASS")
        self.assertEqual(data_suite["subtests"]["holiday_calendar_validated"], "PASS")
        self.assertEqual(data_suite["subtests"]["lse_holiday_calendar_loaded"], "PASS")
        self.assertEqual(data_suite["subtests"]["nyse_holiday_calendar_loaded"], "PASS")
        self.assertEqual(data_suite["subtests"]["exchange_schedule_verified"], "PASS")
        
        self.assertIn("market_session", gate_res)


if __name__ == "__main__":
    unittest.main()
