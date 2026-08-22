"""
Unit and Integration Tests for Broker Parity Monitor & Data Integrity Gate
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.database.db import db
from src.monitoring.broker_parity_monitor import parity_monitor

class TestBrokerParity(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_broker_parity_verified(self):
        """Verify that default broker parity returns 0.00 variance and VERIFIED status."""
        res = self.client.get("/api/integrity/broker_parity")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertEqual(data["status"], "VERIFIED")
        self.assertEqual(data["broker_nav"], 50000.0)
        self.assertEqual(data["api_nav"], 50000.0)
        self.assertEqual(data["dashboard_nav"], 50000.0)
        self.assertEqual(data["variance"], 0.0)
        self.assertIn("last_broker_sync", data)
        self.assertIn("last_ui_hydration", data)

    def test_02_ui_heartbeat_hydration(self):
        """Verify that POST /api/integrity/heartbeat registers client DOM NAV."""
        res = self.client.post("/api/integrity/heartbeat", json={"dashboard_nav": 50000.0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "recorded")

    def test_03_deliberate_desync_drill_break_generates_alert(self):
        """
        Acceptance Test:
        Deliberately break a value (variance > £0.01).
        Expected:
        - status: MISMATCH_DETECTED
        - variance: > 0.01
        - DATA_INTEGRITY_ALERT stored in database
        - Logged to audit trail
        """
        drill_res = self.client.get("/api/integrity/broker_parity?drill_break=150.00")
        self.assertEqual(drill_res.status_code, 200)
        drill_data = drill_res.json()
        
        self.assertEqual(drill_data["status"], "MISMATCH_DETECTED")
        self.assertEqual(drill_data["variance"], 150.0)
        
        # Verify persistence in data_integrity_alerts table
        alerts_res = self.client.get("/api/integrity/alerts?limit=10")
        self.assertEqual(alerts_res.status_code, 200)
        alerts = alerts_res.json()
        self.assertGreater(len(alerts), 0)
        latest = alerts[0]
        self.assertEqual(latest["alert_type"], "DATA_INTEGRITY_ALERT")
        self.assertEqual(latest["severity"], "P0_CRITICAL")
        self.assertEqual(latest["variance"], 150.0)
        self.assertEqual(latest["status"], "MISMATCH_DETECTED")

    def test_04_audit_logs_contain_integrity_breach(self):
        """Verify audit log captures the integrity alert."""
        # Trigger a deliberate break to ensure an alert exists
        self.client.get("/api/integrity/broker_parity?drill_break=100.00")
        
        audit_res = self.client.get("/audit?limit=20")
        self.assertEqual(audit_res.status_code, 200)
        logs = audit_res.json()
        integrity_logs = [l for l in logs if l.get("event_type") == "DATA_INTEGRITY_ALERT"]
        self.assertGreater(len(integrity_logs), 0)

if __name__ == "__main__":
    unittest.main()
