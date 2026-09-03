"""
Unit tests for Autonomous Execution Monitor Telemetry, Status Rules, and Health Watchdog.
"""
import unittest
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from src.core.engine import PRVQuantEngine
from src.api.routes import get_portfolio_summary_fast, get_engine_execution_monitor

class TestExecutionMonitor(unittest.TestCase):

    def setUp(self):
        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine.is_running = False

    def test_telemetry_contains_all_required_keys(self):
        """Verify get_execution_monitor_telemetry() contains all 13 mandatory fields."""
        telemetry = self.engine.get_execution_monitor_telemetry()
        required_keys = [
            "engine_running",
            "engine_heartbeat",
            "heartbeat_age_sec",
            "last_scan_started",
            "last_scan_completed",
            "next_scan",
            "scan_cycles_today",
            "securities_scanned_last_cycle",
            "raw_candidates_last_cycle",
            "final_approvals_last_cycle",
            "orders_submitted_today",
            "last_decision",
            "last_no_trade_reason",
            "status_color",
            "status_text",
            "rejection_breakdown",
            "top_rejected_candidates"
        ]
        for key in required_keys:
            self.assertIn(key, telemetry, f"Missing required telemetry key: {key}")

    def test_status_color_rules(self):
        """Verify GREEN / AMBER / RED rules based on engine state and heartbeat age."""
        # 1. Stopped engine must be RED
        self.engine.is_running = False
        t_stopped = self.engine.get_execution_monitor_telemetry()
        self.assertEqual(t_stopped["status_color"], "RED")
        self.assertEqual(t_stopped["status_text"], "ENGINE STOPPED")

        # 2. Running with fresh heartbeat must be GREEN
        self.engine.is_running = True
        self.engine.last_heartbeat_time = time.time()
        self.engine.last_execution_error = None
        t_green = self.engine.get_execution_monitor_telemetry()
        self.assertEqual(t_green["status_color"], "GREEN")
        self.assertEqual(t_green["status_text"], "ENGINE HEALTHY")

        # 3. Running with heartbeat > 60s must be AMBER
        self.engine.last_heartbeat_time = time.time() - 75.0
        t_amber = self.engine.get_execution_monitor_telemetry()
        self.assertEqual(t_amber["status_color"], "AMBER")
        self.assertEqual(t_amber["status_text"], "HEARTBEAT / SCAN OVERDUE")

        # 4. Running with heartbeat > 180s must be RED
        self.engine.last_heartbeat_time = time.time() - 200.0
        t_red = self.engine.get_execution_monitor_telemetry()
        self.assertEqual(t_red["status_color"], "RED")
        self.assertIn("DEAD", t_red["status_text"])

        # 5. Pipeline exception must be RED
        self.engine.last_heartbeat_time = time.time()
        self.engine.last_execution_error = "BrokerNetworkTimeout"
        t_err = self.engine.get_execution_monitor_telemetry()
        self.assertEqual(t_err["status_color"], "RED")
        self.assertEqual(t_err["status_text"], "EXECUTION PIPELINE FAILURE")

    def test_zero_approvals_decision_format(self):
        """Verify that zero approvals sets NO TRADE — SCAN COMPLETED SUCCESSFULLY."""
        self.engine.is_running = True
        self.engine.securities_scanned_last_cycle = 103
        self.engine.raw_candidates_last_cycle = 7
        self.engine.final_approvals_last_cycle = 0
        self.engine.rejection_breakdown = {
            "failed_net_rr": 4,
            "failed_technical_gate": 2,
            "failed_cost_gate": 1,
            "failed_risk_gate": 0,
            "failed_compliance": 0
        }
        self.engine.last_decision = "NO TRADE — SCAN COMPLETED SUCCESSFULLY"
        self.engine.last_no_trade_reason = "7 candidates evaluated: 4 failed net R:R, 2 failed technical gate, 1 failed cost gate."

        t = self.engine.get_execution_monitor_telemetry()
        self.assertEqual(t["last_decision"], "NO TRADE — SCAN COMPLETED SUCCESSFULLY")
        self.assertIn("4 failed net R:R", t["last_no_trade_reason"])
        self.assertEqual(t["rejection_breakdown"]["failed_net_rr"], 4)
        self.assertEqual(t["rejection_breakdown"]["failed_technical_gate"], 2)
        self.assertEqual(t["rejection_breakdown"]["failed_cost_gate"], 1)

    def test_api_routes_expose_telemetry(self):
        """Verify that both /api/engine/execution_monitor and summary_fast expose execution_monitor."""
        dedicated = get_engine_execution_monitor()
        self.assertIsInstance(dedicated, dict)
        self.assertIn("status_color", dedicated)
        self.assertIn("engine_running", dedicated)

        fast = get_portfolio_summary_fast()
        self.assertIn("execution_monitor", fast)
        self.assertIsInstance(fast["execution_monitor"], dict)
        self.assertEqual(fast["execution_monitor"]["status_color"], dedicated["status_color"])

if __name__ == "__main__":
    unittest.main()
