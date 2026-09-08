"""
Unit & Integration Tests for Broker Source of Truth & Parity Verification
"""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from src.brokers.trading212 import broker

class TestBrokerSourceOfTruth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.mock_summary = {"total_value": 50000.0, "free_cash": 50000.0, "invested": 0.0}
        self.mock_pos = []

    def test_01_verify_broker_truth_method(self):
        """Verify that broker.verify_broker_truth reconciles counts and NAV."""
        with patch.object(broker, "get_account_summary", return_value=self.mock_summary), \
             patch.object(broker, "get_open_positions", return_value=self.mock_pos):
            res = broker.verify_broker_truth()
            self.assertTrue(res.get("broker_is_source_of_truth"))
            self.assertIn("status", res)
            self.assertIn("broker_holdings_count", res)
            self.assertIn("prv_holdings_count", res)
            self.assertIn("reconciliation", res)
            
            # Mismatch must be false
            self.assertFalse(res.get("mismatch_detected"))
            self.assertEqual(res["broker_holdings_count"], res["prv_holdings_count"])

    def test_02_api_broker_parity_check(self):
        """Verify GET /api/broker/parity_check endpoint returns parity status."""
        with patch.object(broker, "get_account_summary", return_value=self.mock_summary), \
             patch.object(broker, "get_open_positions", return_value=self.mock_pos):
            res = self.client.get("/api/broker/parity_check")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "VERIFIED_PARITY")
            self.assertGreaterEqual(data.get("broker_holdings_count"), 0)
            self.assertEqual(data.get("broker_holdings_count"), data.get("prv_holdings_count"))

if __name__ == "__main__":
    unittest.main()
