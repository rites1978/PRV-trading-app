"""
PRV CAPITAL | EXTERNAL NETWORK ISOLATION SUITE

A test run must touch nothing outside this machine. Reaching Supabase mutates real
telemetry (POST /rest/v1/risk_telemetry was observed 28 times per suite run);
reaching Yahoo Finance makes results depend on a third party and stalls the suite on
their latency.

The guard is armed for every run by tests/__init__.py and fails closed: any
unapproved outbound connection raises ExternalNetworkBlocked. Loopback stays
allowed so a test may run a local server.
"""
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.runtime_guard import is_test_runtime
from src.core import test_network_guard as guard


class TestExternalNetworkGuard(unittest.TestCase):

    def test_GUARD_IS_ARMED_FOR_EVERY_TEST_RUN(self):
        """tests/__init__.py arms the guard on import of the tests package."""
        self.assertTrue(is_test_runtime())
        self.assertTrue(guard.is_installed(),
                        "the external network guard must be armed for every suite run")

    def test_GUARD_REFUSES_TO_ARM_OUTSIDE_TEST_RUNTIME(self):
        """Production must be unaffected: install() declines when not under test."""
        import inspect
        src = inspect.getsource(guard.install)
        self.assertIn("if not is_test_runtime():", src)
        self.assertIn("not a test runtime", src)

    def test_TEST_SUPABASE_HTTP_READ_AND_WRITE_BLOCKED(self):
        """Any Supabase connection is refused and classified."""
        before = guard.counts()["SUPABASE"]
        with self.assertRaises(guard.ExternalNetworkBlocked):
            socket.socket().connect(("ntehqyguamgqfgrgivjh.supabase.co", 443))
        self.assertEqual(guard.counts()["SUPABASE"], before + 1)

    def test_TEST_YFINANCE_HTTP_BLOCKED(self):
        """Yahoo Finance is refused at the curl_cffi boundary and at the socket."""
        before = guard.counts()["YFINANCE"]
        with self.assertRaises(guard.ExternalNetworkBlocked):
            socket.socket().connect(("query1.finance.yahoo.com", 443))
        self.assertEqual(guard.counts()["YFINANCE"], before + 1)

    def test_CURL_CFFI_TRANSPORT_IS_INTERCEPTED(self):
        """yfinance drives libcurl, which bypasses Python sockets entirely."""
        try:
            from curl_cffi import requests as curl_requests
        except Exception:
            self.skipTest("curl_cffi not installed")
        with self.assertRaises(guard.ExternalNetworkBlocked):
            curl_requests.Session().request("GET", "https://query1.finance.yahoo.com/v8/finance/chart/EMIM.L")

    def test_LOOPBACK_REMAINS_PERMITTED(self):
        """A local server must still be reachable; only external hosts are refused."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        try:
            client = socket.socket()
            client.connect(srv.getsockname())   # must not raise
            client.close()
        finally:
            srv.close()

    def test_ARBITRARY_EXTERNAL_HOST_FAILS_CLOSED(self):
        """Unknown hosts are refused too -- the guard is a deny-list of nothing."""
        with self.assertRaises(guard.ExternalNetworkBlocked):
            socket.socket().connect(("example.com", 80))

    def test_BLOCKED_CALL_NAMES_THE_DEPENDENCY(self):
        """The failure must tell a developer what to stub."""
        try:
            socket.socket().connect(("api.example-vendor.com", 443))
            self.fail("expected the guard to refuse")
        except guard.ExternalNetworkBlocked as e:
            self.assertIn("EXTERNAL_NETWORK_BLOCKED", str(e))
            self.assertIn("Stub or mock this dependency", str(e))


if __name__ == "__main__":
    unittest.main()
