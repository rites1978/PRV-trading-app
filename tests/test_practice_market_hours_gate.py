"""
Unit Tests for Practice & Live Account Market-Hours Entry Gating.
Validates the complete truth table:
1. practice + UK closed -> entry DENIED
2. practice + US closed -> entry DENIED
3. practice + UK open -> routing permitted
4. practice + US open -> routing permitted
5. live + closed -> entry DENIED
"""
import unittest
from unittest.mock import patch
from src.execution.order_router import order_router


class TestPracticeMarketHoursGate(unittest.TestCase):

    def setUp(self):
        self.uk_params = {
            "symbol": "HSBA",
            "t212_ticker": "HSBAl_EQ",
            "quantity": 100.0,
            "price": 15.0,
            "target_price": 16.5,
            "stop_loss_price": 14.5,
            "sector": "Financials",
            "confidence_score": 85.0,
            "market_regime": "BULL",
            "agent_votes": {"Trend": "BUY"},
            "risk_approved": True
        }
        self.us_params = {
            "symbol": "CRM",
            "t212_ticker": "CRM_US_EQ",
            "quantity": 10.0,
            "price": 280.0,
            "target_price": 305.0,
            "stop_loss_price": 272.0,
            "sector": "Technology",
            "confidence_score": 85.0,
            "market_regime": "BULL",
            "agent_votes": {"Trend": "BUY"},
            "risk_approved": True
        }
        self.daily_patch = patch("src.portfolio.daily_objective_service.daily_objective_service.get_daily_status", return_value={"new_discretionary_entries_allowed": True, "gate_reason": "CLEAR", "sizing_multiplier": 1.0, "emergency_risk_mode": False})
        self.daily_patch.start()

    def tearDown(self):
        self.daily_patch.stop()

    @patch("src.data.market_hours.market_hours.is_asset_market_open")
    def test_practice_uk_closed_entry_denied(self, mock_is_open):
        """Test: practice (is_paper=True) + UK closed -> entry DENIED."""
        mock_is_open.return_value = False
        success, msg, data = order_router.route_entry_order(**self.uk_params, is_paper=True)
        self.assertFalse(success)
        self.assertIn("MARKET CLOSED", msg)
        self.assertIn("LSE_MARKET_CLOSED", data.get("rejection_reasons", []))

    @patch("src.data.market_hours.market_hours.is_asset_market_open")
    def test_practice_us_closed_entry_denied(self, mock_is_open):
        """Test: practice (is_paper=True) + US closed -> entry DENIED."""
        mock_is_open.return_value = False
        success, msg, data = order_router.route_entry_order(**self.us_params, is_paper=True)
        self.assertFalse(success)
        self.assertIn("MARKET CLOSED", msg)
        self.assertIn("NYSE/NASDAQ_MARKET_CLOSED", data.get("rejection_reasons", []))

    @patch("src.data.market_hours.market_hours.is_asset_market_open")
    def test_practice_uk_open_routing_permitted(self, mock_is_open):
        """Test: practice (is_paper=True) + UK open -> routing permitted."""
        mock_is_open.return_value = True
        success, msg, data = order_router.route_entry_order(**self.uk_params, is_paper=True)
        self.assertTrue(success)
        self.assertIn("PAPER BUY", msg)

    @patch("src.data.market_hours.market_hours.is_asset_market_open")
    def test_practice_us_open_routing_permitted(self, mock_is_open):
        """Test: practice (is_paper=True) + US open -> routing permitted."""
        mock_is_open.return_value = True
        success, msg, data = order_router.route_entry_order(**self.us_params, is_paper=True)
        self.assertTrue(success)
        self.assertIn("PAPER BUY", msg)

    @patch("src.data.market_hours.market_hours.is_asset_market_open")
    def test_live_closed_entry_denied(self, mock_is_open):
        """Test: live (is_paper=False) + closed -> entry DENIED."""
        mock_is_open.return_value = False
        success, msg, data = order_router.route_entry_order(**self.us_params, is_paper=False)
        self.assertFalse(success)
        self.assertIn("MARKET CLOSED", msg)
        self.assertIn("NYSE/NASDAQ_MARKET_CLOSED", data.get("rejection_reasons", []))


if __name__ == "__main__":
    unittest.main()
