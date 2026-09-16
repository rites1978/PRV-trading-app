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
        """Verifies stop price adheres to strict 5.0% max loss invariant."""
        fill = 250.0

        # Exactly 5%
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
