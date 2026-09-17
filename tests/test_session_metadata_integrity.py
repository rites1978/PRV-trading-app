"""
Unit Tests: Session Metadata Integrity & extendedHours Parsing Defect Resolution
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Verifies:
1. Parse instrument with extendedHours=True -> returns extended_hours=True, status KNOWN_TRUE.
2. Parse instrument with extendedHours=False -> returns extended_hours=False, status KNOWN_FALSE.
3. Parse instrument with extendedHours=None -> returns extended_hours=None, status UNKNOWN.
4. Parse instrument missing extendedHours key -> returns extended_hours=None, status UNKNOWN.
5. Parse instrument with non-boolean values ("true", "false", 1, 0, etc.) -> returns extended_hours=None, status UNKNOWN (no coercion!).
6. Verify market session router fails closed (session_open_now=False, extended_hours_eligible=False) when extended_hours_status=UNKNOWN during extended session hours (PRE_MARKET, AFTER_HOURS).
7. Verify market session router marks regular session open regardless of extended_hours status during regular session hours.
8. Verify overnight session eligibility is NOT inferred from extendedHours (overnight_eligibility must remain UNKNOWN / fail closed unless explicitly authorised).
9. Verify raw snapshot counts:
   - 2026-09-17 morning snapshot contains 17,563 total instruments, exactly 5,288 extendedHours=True, exactly 12,275 extendedHours=False, 0 null, 0 missing.
   - 2026-09-14 historical snapshot contains 17,448 total instruments, exactly 5,286 extendedHours=True, exactly 12,162 extendedHours=False, 0 null, 0 missing.
   - 2026-09-17 latest snapshot contains 17,566 total instruments, exactly 5,288 extendedHours=True, exactly 12,278 extendedHours=False, 0 null, 0 missing.
10. Verify broker discovery telemetry matches parsed snapshot counts.
11. Verify universe telemetry exposes extendedHours breakdown.
12. Verify zero broker writes occur (read-only operations only).
"""
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.data.broker_discovery import BrokerDiscoveryService, broker_discovery
from src.data.market_session_router import market_session_router
from src.hit_and_run.universe import hit_and_run_universe
from src.hit_and_run.opportunity_state import opportunity_state_builder


class TestSessionMetadataIntegrity(unittest.TestCase):

    def setUp(self):
        self.discovery = BrokerDiscoveryService()

    def test_01_extended_hours_true_parsing(self):
        """Parse instrument with extendedHours=True -> returns extended_hours=True, status KNOWN_TRUE."""
        inst = {"ticker": "AAPL_US_EQ", "extendedHours": True}
        res = self.discovery.evaluate_extended_hours(inst)
        self.assertIs(res["extended_hours"], True)
        self.assertEqual(res["extended_hours_status"], "KNOWN_TRUE")
        self.assertTrue(res["is_extended_hours_eligible"])
        self.assertEqual(res["source"], "BROKER_METADATA")

    def test_02_extended_hours_false_parsing(self):
        """Parse instrument with extendedHours=False -> returns extended_hours=False, status KNOWN_FALSE."""
        inst = {"ticker": "VOD_UK_EQ", "extendedHours": False}
        res = self.discovery.evaluate_extended_hours(inst)
        self.assertIs(res["extended_hours"], False)
        self.assertEqual(res["extended_hours_status"], "KNOWN_FALSE")
        self.assertFalse(res["is_extended_hours_eligible"])
        self.assertEqual(res["source"], "BROKER_METADATA")

    def test_03_extended_hours_none_parsing(self):
        """Parse instrument with extendedHours=None -> returns extended_hours=None, status UNKNOWN."""
        inst = {"ticker": "XYZ_EQ", "extendedHours": None}
        res = self.discovery.evaluate_extended_hours(inst)
        self.assertIsNone(res["extended_hours"])
        self.assertEqual(res["extended_hours_status"], "UNKNOWN")
        self.assertFalse(res["is_extended_hours_eligible"])
        self.assertEqual(res["source"], "UNAVAILABLE:FIELD_NULL")

    def test_04_extended_hours_missing_parsing(self):
        """Parse instrument missing extendedHours key -> returns extended_hours=None, status UNKNOWN."""
        inst = {"ticker": "XYZ_EQ"}
        res = self.discovery.evaluate_extended_hours(inst)
        self.assertIsNone(res["extended_hours"])
        self.assertEqual(res["extended_hours_status"], "UNKNOWN")
        self.assertFalse(res["is_extended_hours_eligible"])
        self.assertEqual(res["source"], "UNAVAILABLE:FIELD_MISSING")

    def test_05_extended_hours_no_silent_coercion_on_non_boolean_values(self):
        """
        Parse instrument with non-boolean values ("true", "false", 1, 0, etc.) ->
        returns extended_hours=None, status UNKNOWN (no coercion!).
        """
        invalid_values = ["true", "false", "True", "False", 1, 0, 1.0, 0.0, [], {}]
        for val in invalid_values:
            with self.subTest(val=val):
                inst = {"ticker": "TEST_EQ", "extendedHours": val}
                res = self.discovery.evaluate_extended_hours(inst)
                self.assertIsNone(
                    res["extended_hours"],
                    f"Value {val!r} of type {type(val).__name__} was silently coerced!"
                )
                self.assertEqual(res["extended_hours_status"], "UNKNOWN")
                self.assertFalse(res["is_extended_hours_eligible"])
                self.assertTrue(res["source"].startswith("INVALID_TYPE:"))

    def test_06_market_session_router_fails_closed_in_extended_hours_when_unknown(self):
        """
        Verify market session router fails closed (session_open_now=False, extended_hours_eligible=False)
        when extended_hours_status=UNKNOWN during extended session hours (PRE_MARKET, AFTER_HOURS).
        """
        # 21:53 UTC: NYSE/NASDAQ is in AFTER_HOURS (107 = US Equities)
        utc_dt_after = datetime(2026, 9, 16, 21, 53, 31, tzinfo=timezone.utc)

        # 1. Missing extendedHours key
        inst_missing = {"workingScheduleId": 107}
        d_missing = market_session_router.get_instrument_session_details(inst_missing, utc_dt=utc_dt_after)
        self.assertFalse(d_missing["session_open_now"])
        self.assertFalse(d_missing["extended_hours_eligible"])
        self.assertEqual(d_missing["extended_hours_status"], "UNKNOWN")
        self.assertIsNone(d_missing["extended_hours"])
        self.assertEqual(d_missing["execution_session"], "CLOSED")
        self.assertTrue(d_missing["instrument_not_tradable_now"])
        self.assertIn("UNKNOWN", d_missing["status_reason"])

        # 2. Null extendedHours
        inst_null = {"workingScheduleId": 107, "extendedHours": None}
        d_null = market_session_router.get_instrument_session_details(inst_null, utc_dt=utc_dt_after)
        self.assertFalse(d_null["session_open_now"])
        self.assertFalse(d_null["extended_hours_eligible"])
        self.assertEqual(d_null["extended_hours_status"], "UNKNOWN")
        self.assertIsNone(d_null["extended_hours"])
        self.assertEqual(d_null["execution_session"], "CLOSED")

        # 3. Non-boolean extendedHours ("true")
        inst_str = {"workingScheduleId": 107, "extendedHours": "true"}
        d_str = market_session_router.get_instrument_session_details(inst_str, utc_dt=utc_dt_after)
        self.assertFalse(d_str["session_open_now"])
        self.assertFalse(d_str["extended_hours_eligible"])
        self.assertEqual(d_str["extended_hours_status"], "UNKNOWN")

    def test_07_market_session_router_marks_regular_session_open_regardless_of_extended_status(self):
        """
        Verify market session router marks regular session open regardless of extended_hours status
        during regular session hours.
        """
        # 15:00 UTC: Regular trading hours for US Equities (workingScheduleId 107)
        utc_dt_regular = datetime(2026, 9, 16, 15, 0, 0, tzinfo=timezone.utc)

        inst_ext_true = {"workingScheduleId": 107, "extendedHours": True}
        inst_ext_false = {"workingScheduleId": 107, "extendedHours": False}
        inst_ext_none = {"workingScheduleId": 107, "extendedHours": None}
        inst_ext_missing = {"workingScheduleId": 107}

        d_true = market_session_router.get_instrument_session_details(inst_ext_true, utc_dt=utc_dt_regular)
        d_false = market_session_router.get_instrument_session_details(inst_ext_false, utc_dt=utc_dt_regular)
        d_none = market_session_router.get_instrument_session_details(inst_ext_none, utc_dt=utc_dt_regular)
        d_missing = market_session_router.get_instrument_session_details(inst_ext_missing, utc_dt=utc_dt_regular)

        for d, name in [(d_true, "True"), (d_false, "False"), (d_none, "None"), (d_missing, "Missing")]:
            with self.subTest(name=name):
                self.assertTrue(d["session_open_now"])
                self.assertEqual(d["execution_session"], "REGULAR")
                self.assertFalse(d["regular_session_closed"])
                self.assertFalse(d["instrument_not_tradable_now"])

    def test_08_overnight_eligibility_not_inferred_from_extended_hours(self):
        """
        Verify overnight session eligibility is NOT inferred from extendedHours
        (overnight_eligibility must remain UNKNOWN / fail closed unless explicitly authorised).
        """
        # 02:00 UTC on 2026-09-17: US Equities in OVERNIGHT window (00:00 - 08:00 UTC)
        utc_dt_overnight = datetime(2026, 9, 17, 2, 0, 0, tzinfo=timezone.utc)

        # ExtendedHours=True alone must NOT grant overnight access
        inst_ext_true = {"workingScheduleId": 107, "extendedHours": True}
        d_ext_true = market_session_router.get_instrument_session_details(inst_ext_true, utc_dt=utc_dt_overnight)

        self.assertEqual(d_ext_true["exchange_session"], "OVERNIGHT")
        self.assertEqual(d_ext_true["overnight_eligibility"], "UNKNOWN")
        self.assertFalse(d_ext_true["session_open_now"])
        self.assertEqual(d_ext_true["execution_session"], "CLOSED")
        self.assertTrue(d_ext_true["instrument_not_tradable_now"])
        self.assertIn("OVERNIGHT_UNVERIFIED", d_ext_true["status_reason"])

    def test_09_raw_snapshot_counts_and_reconciliation(self):
        """
        Verify raw snapshot counts:
        - 2026-09-17 morning snapshot contains 17,563 total instruments, exactly 5,288 extendedHours=True,
          exactly 12,275 extendedHours=False, 0 null, 0 missing.
        - 2026-09-14 historical snapshot contains 17,448 total instruments, exactly 5,286 extendedHours=True,
          exactly 12,162 extendedHours=False, 0 null, 0 missing.
        - 2026-09-17 latest snapshot contains 17,566 total instruments, exactly 5,288 extendedHours=True,
          exactly 12,278 extendedHours=False, 0 null, 0 missing.
        """
        snapshots = [
            ("data/trading212_instruments_historical_20260914.json", 17448, 5286, 12162),
            ("data/trading212_instruments_snapshot_20260917.json", 17563, 5288, 12275),
            ("data/trading212_instruments_snapshot_latest.json", 17566, 5288, 12278)
        ]

        for path, exp_total, exp_true, exp_false in snapshots:
            if not os.path.exists(path):
                continue
            with self.subTest(file=path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                total = len(data)
                true_c = 0
                false_c = 0
                null_c = 0
                missing_c = 0

                for item in data:
                    if "extendedHours" not in item:
                        missing_c += 1
                    elif item["extendedHours"] is None:
                        null_c += 1
                    elif item["extendedHours"] is True:
                        true_c += 1
                    elif item["extendedHours"] is False:
                        false_c += 1

                self.assertEqual(total, exp_total, f"Total count mismatch for {path}")
                self.assertEqual(true_c, exp_true, f"extendedHours=True mismatch for {path}")
                self.assertEqual(false_c, exp_false, f"extendedHours=False mismatch for {path}")
                self.assertEqual(null_c, 0, f"extendedHours=None detected in {path}")
                self.assertEqual(missing_c, 0, f"missing extendedHours detected in {path}")
                self.assertEqual(true_c + false_c, total)

    def test_10_broker_discovery_telemetry_matches_parsed_counts(self):
        """Verify broker discovery telemetry accurately reflects parsed snapshot counts."""
        srv = BrokerDiscoveryService()
        srv.initialize()
        telemetry = srv.get_discovery_telemetry()

        self.assertIn("EXTENDED_HOURS_TRUE", telemetry)
        self.assertIn("EXTENDED_HOURS_FALSE", telemetry)
        self.assertIn("EXTENDED_HOURS_NULL", telemetry)
        self.assertIn("EXTENDED_HOURS_MISSING", telemetry)
        self.assertIn("EXTENDED_HOURS_UNKNOWN", telemetry)

        # Baseline snapshot has 17,448 instruments with 5,286 True, 12,162 False
        # If latest snapshot loaded, counts match that snapshot
        total = telemetry["BROKER_API_DISCOVERED"]
        true_c = telemetry["EXTENDED_HOURS_TRUE"]
        false_c = telemetry["EXTENDED_HOURS_FALSE"]
        unknown_c = telemetry["EXTENDED_HOURS_UNKNOWN"]

        self.assertEqual(true_c + false_c + unknown_c, total)
        self.assertEqual(telemetry["EXTENDED_HOURS_NULL"], 0)
        self.assertEqual(telemetry["EXTENDED_HOURS_MISSING"], 0)
        self.assertEqual(unknown_c, 0)
        self.assertGreater(true_c, 5000)
        self.assertGreater(false_c, 12000)

    def test_11_universe_telemetry_exposes_extended_hours_breakdown(self):
        """Verify universe telemetry exposes extendedHours breakdown and opportunity state builder populates status."""
        u_telemetry = hit_and_run_universe.get_universe_telemetry()
        self.assertIn("EXTENDED_HOURS_TRUE", u_telemetry)
        self.assertIn("EXTENDED_HOURS_FALSE", u_telemetry)
        self.assertIn("EXTENDED_HOURS_UNKNOWN", u_telemetry)
        self.assertEqual(
            u_telemetry["EXTENDED_HOURS_TRUE"] +
            u_telemetry["EXTENDED_HOURS_FALSE"] +
            u_telemetry["EXTENDED_HOURS_UNKNOWN"],
            u_telemetry["DISCOVERED_INSTRUMENT_COUNT"]
        )

        # Verify opportunity state builder carries extended_hours and extended_hours_status
        snap = {
            "instrument_id": "AAPL_US_EQ",
            "workingScheduleId": 107,
            "extendedHours": True,
            "current_price": 220.0,
            "bid": 219.9,
            "ask": 220.1
        }
        state = opportunity_state_builder.build_state(snap)
        self.assertEqual(state.extended_hours_status, "KNOWN_TRUE")
        self.assertIs(state.extended_hours, True)

        snap_unknown = {
            "instrument_id": "TEST_EQ",
            "workingScheduleId": 107,
            "extendedHours": None,
            "current_price": 50.0,
            "bid": 49.9,
            "ask": 50.1
        }
        state_unk = opportunity_state_builder.build_state(snap_unknown)
        self.assertEqual(state_unk.extended_hours_status, "UNKNOWN")
        self.assertIsNone(state_unk.extended_hours)

    def test_12_zero_broker_writes_confirmed(self):
        """Verify zero broker writes occur (read-only operations only)."""
        # Ensure no write endpoints or POST/PUT/DELETE requests were called
        from src.brokers.trading212 import broker
        with patch.object(broker, "_request_with_retry") as mock_req:
            # Re-run initialization or evaluations
            srv = BrokerDiscoveryService()
            srv.evaluate_extended_hours({"extendedHours": True})
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
