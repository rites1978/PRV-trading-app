"""
Unit tests for Stop Protection Architecture, Frozen Manifest Integrity, and Daemon Watchdog.
"""
import unittest
from src.config.settings import settings
from src.core.engine import quant_engine
from src.brokers.trading212 import broker


class TestStopProtectionAndWatchdog(unittest.TestCase):

    def test_frozen_manifest_exit_parameters(self):
        """Verify immutable parameter manifest values for stop and take-profit."""
        manifest = settings.generate_parameter_manifest()
        self.assertEqual(manifest["default_stop_loss_pct"], 0.025) # -2.5%
        self.assertEqual(manifest["default_take_profit_pct"], 0.075) # +7.5%
        self.assertEqual(manifest["min_gross_reward_risk_ratio"], 3.0)
        self.assertEqual(manifest["min_net_reward_risk_ratio"], 2.0)
        self.assertEqual(manifest["max_expected_holding_period_days"], 14)
        self.assertEqual(manifest["configuration_version"], "CONFIG_V3.0_PRACTICE_30DAY_CHALLENGE_20260902")

    def test_watchdog_status_and_health(self):
        """Verify daemon watchdog reports health, heartbeat, and process resilience."""
        status = quant_engine.get_watchdog_status()
        self.assertIn("execution_health", status)
        self.assertIn("last_heartbeat_timestamp", status)
        self.assertIn("restart_recovery_ready", status)
        self.assertTrue(status["restart_recovery_ready"])
        self.assertEqual(status["protection_resilience"], "PROCESS_DEPENDENT (PRV DAEMON MONITORED)")

    def test_restart_recovery_hydrates_positions(self):
        """Verify position recovery re-arms trailing stop peaks for all active holdings."""
        quant_engine._recover_positions_on_restart()
        self.assertEqual(len(quant_engine.position_peaks), 11)
        for sym in ["HSBAl_EQ", "V_US_EQ", "WFC_US_EQ", "JNJ_US_EQ", "ULVRl_EQ", "MRK_US_EQ", "NOW_US_EQ", "SLB_US_EQ", "GLENl_EQ", "TSLA_US_EQ", "AALl_EQ"]:
            self.assertIn(sym, quant_engine.position_peaks)
            self.assertGreater(quant_engine.position_peaks[sym], 0.0)

    def test_broker_has_native_stop_order_methods(self):
        """Verify broker client implements place_stop_order, place_stop_limit_order, and cancel_order."""
        self.assertTrue(callable(getattr(broker, "place_stop_order", None)))
        self.assertTrue(callable(getattr(broker, "place_stop_limit_order", None)))
        self.assertTrue(callable(getattr(broker, "cancel_order", None)))
        self.assertTrue(broker.is_authenticated())


if __name__ == "__main__":
    unittest.main()
