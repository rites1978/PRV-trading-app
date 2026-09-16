"""
TDD Tests: Hit-and-Run Risk Manager and 5% Max-Loss Invariant
Verifies:
1. Stop loss derivation strictly enforces <= 5.0% loss from authoritative fill price.
2. Any stop loss wider than 5.0% is rejected immediately.
3. Stop price above or equal to fill price is rejected.
4. Native broker protection verification confirms active stop order with exact quantity.
5. If broker stop is unconfirmed, flags PROTECTION_UNCONFIRMED_FAIL_CLOSED.
"""
import unittest


class TestHitAndRunRiskManager(unittest.TestCase):

    def setUp(self):
        from src.hit_and_run.risk import HitAndRunRiskManager
        self.risk = HitAndRunRiskManager()

    def test_calculate_protective_stop_enforces_5pct_ceiling(self):
        """Calculates protective stop clamped to 5% maximum loss."""
        fill_price = 100.0

        # Requesting 3% -> permitted
        stop_3pct = self.risk.calculate_protective_stop(fill_price, requested_risk_pct=0.03)
        self.assertEqual(stop_3pct, 97.0)

        # Requesting 7% -> clamped to 5%
        stop_7pct = self.risk.calculate_protective_stop(fill_price, requested_risk_pct=0.07)
        self.assertEqual(stop_7pct, 95.0)

        # Default (no risk requested) -> 5%
        stop_default = self.risk.calculate_protective_stop(fill_price)
        self.assertEqual(stop_default, 95.0)

    def test_verify_protective_stop_invariant(self):
        """Verifies stop price adheres to strict 5.0% max loss invariant: stop_price >= fill_price * 0.95."""
        self.assertEqual(self.risk.MAXIMUM_AUTHORISED_LOSS_PCT, 0.05)
        fill = 250.0

        # Exactly 5%: stop_price = fill * 0.95 = 237.50
        valid_5pct, reason = self.risk.verify_protective_stop_invariant(fill, 237.50)
        self.assertTrue(valid_5pct)

        # Tighter 2% stop
        valid_2pct, reason = self.risk.verify_protective_stop_invariant(fill, 245.00)
        self.assertTrue(valid_2pct)

        # 5.1% loss -> REJECTED
        invalid_wide, reason = self.risk.verify_protective_stop_invariant(fill, 237.00)
        self.assertFalse(invalid_wide)
        self.assertIn("EXCEEDS_5PCT_MAX_LOSS", reason)

        # Stop >= fill -> REJECTED
        invalid_high, reason = self.risk.verify_protective_stop_invariant(fill, 255.00)
        self.assertFalse(invalid_high)
        self.assertIn("MUST_BE_BELOW_FILL", reason)

    def test_five_percent_invariant_boundary_conditions(self):
        """Tests strict 5% floor: stop_price >= fill_price * 0.95 with zero relaxation."""
        fill = 100.0
        # Exactly 0.95 * 100.0 = 95.0
        valid, _ = self.risk.verify_protective_stop_invariant(fill, 95.0, tick_size=0.01)
        self.assertTrue(valid)

        # Even 0.001 below 95.0 -> REJECTED (no epsilon, no tick_size*0.5 relaxation)
        invalid, reason = self.risk.verify_protective_stop_invariant(fill, 94.999, tick_size=0.01)
        self.assertFalse(invalid)
        self.assertIn("EXCEEDS_5PCT_MAX_LOSS", reason)

    def test_five_percent_stop_rounding_example_gbx(self):
        """
        GBX Example:
        fill_price = 100.35 GBX, tick_size = 0.1 GBX
        theoretical_floor = 100.35 * 0.95 = 95.3325 GBX
        Rounding down to 95.3 gives 5.032% loss (VIOLATION).
        Rounding UP to next valid tick gives 95.4 GBX, planned loss 4.933% <= 5%.
        """
        fill_price = 100.35
        tick_size = 0.1
        theoretical_floor = fill_price * 0.95  # 95.3325

        # Downward rounding fails
        downward_stop = 95.3
        valid_down, reason_down = self.risk.verify_protective_stop_invariant(fill_price, downward_stop, tick_size)
        self.assertFalse(valid_down)
        self.assertIn("EXCEEDS_5PCT_MAX_LOSS", reason_down)

        # Rounding UP to next valid broker tick succeeds
        upward_stop = self.risk.round_stop_up_to_tick(theoretical_floor, tick_size)
        self.assertEqual(upward_stop, 95.4)
        self.assertGreaterEqual(upward_stop, theoretical_floor)
        valid_up, _ = self.risk.verify_protective_stop_invariant(fill_price, upward_stop, tick_size)
        self.assertTrue(valid_up)
        planned_loss_pct = (fill_price - upward_stop) / fill_price
        self.assertLessEqual(planned_loss_pct, 0.05)

    def test_five_percent_stop_rounding_example_gbp(self):
        """
        GBP Example:
        fill_price = 15.23 GBP, tick_size = 0.01 GBP
        theoretical_floor = 15.23 * 0.95 = 14.4685 GBP
        Rounding down to 14.46 gives 5.056% loss (VIOLATION).
        Rounding UP to next valid tick gives 14.47 GBP, planned loss 4.990% <= 5%.
        """
        fill_price = 15.23
        tick_size = 0.01
        theoretical_floor = fill_price * 0.95  # 14.4685

        # Downward rounding fails
        downward_stop = 14.46
        valid_down, reason_down = self.risk.verify_protective_stop_invariant(fill_price, downward_stop, tick_size)
        self.assertFalse(valid_down)
        self.assertIn("EXCEEDS_5PCT_MAX_LOSS", reason_down)

        # Rounding UP to next valid broker tick succeeds
        upward_stop = self.risk.round_stop_up_to_tick(theoretical_floor, tick_size)
        self.assertEqual(upward_stop, 14.47)
        self.assertGreaterEqual(upward_stop, theoretical_floor)
        valid_up, _ = self.risk.verify_protective_stop_invariant(fill_price, upward_stop, tick_size)
        self.assertTrue(valid_up)
        planned_loss_pct = (fill_price - upward_stop) / fill_price
        self.assertLessEqual(planned_loss_pct, 0.05)

    def test_broker_native_stop_verification_confirmed(self):
        """Confirmed when broker open orders has active STOP with exact quantity."""
        orders = [
            {
                "id": "ORD_STOP_1",
                "ticker": "AAPL_US_EQ",
                "type": "STOP",
                "quantity": -50.0,
                "stopPrice": 95.0,
                "status": "WORKING"
            }
        ]

        confirmed, reason, details = self.risk.verify_broker_stop_protection(
            ticker="AAPL_US_EQ",
            held_quantity=50.0,
            expected_stop_price=95.0,
            open_orders=orders
        )

        self.assertTrue(confirmed)
        self.assertEqual(reason, "PROTECTION_CONFIRMED")
        self.assertIsNotNone(details)

    def test_broker_native_stop_verification_unconfirmed_fails_closed(self):
        """Fails closed when broker stop is absent or mismatched in quantity/price."""
        orders = [
            {
                "id": "ORD_LIMIT_1",
                "ticker": "AAPL_US_EQ",
                "type": "LIMIT",
                "quantity": 50.0,
                "status": "WORKING"
            }
        ]

        confirmed, reason, details = self.risk.verify_broker_stop_protection(
            ticker="AAPL_US_EQ",
            held_quantity=50.0,
            expected_stop_price=95.0,
            open_orders=orders
        )

        self.assertFalse(confirmed)
        self.assertEqual(reason, "PROTECTION_UNCONFIRMED_FAIL_CLOSED")


if __name__ == "__main__":
    unittest.main()
