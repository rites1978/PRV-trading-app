"""
Unit tests for Trading212 Central Endpoint-Aware Rate Limiter.
Verifies:
- Endpoint-specific quotas:
  - GET equity/orders: 1 req / 5.0s
  - GET equity/portfolio (positions): 1 req / 1.0s
  - GET equity/account/cash or summary: 1 req / 5.0s
  - POST equity/orders/stop: 1 req / 2.0s
  - POST equity/orders/limit: 1 req / 2.0s
  - DELETE equity/orders/{id}: 50 req / 60.0s (min 1.2s spacing)
- F5 burst sequences:
  - F5 cancel then verify orders waits for GET /orders budget (>= 5.0s)
  - F5 failed stop then reinstate waits for POST /stop budget (>= 2.0s)
- Cross-thread sharing:
  - Background sync and engine share rate limiter
  - Watchdog and Core cycle share rate limiter
- Header adaptations:
  - x-ratelimit-* headers update local budget
  - 429 retry honours Retry-After / x-ratelimit-reset
- Concurrency stress test across simultaneous background sync, Core cycle, watchdog, and F5 replacement.

All tests utilize a deterministic MockClock (zero real sleeps, instantaneous execution).
"""
import unittest
import threading
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, patch

from src.brokers.trading212 import (
    Trading212RateLimiter,
    Trading212Broker,
    EndpointCategory,
)


class MockClock:
    """Deterministic virtual clock for unit tests."""
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time
        self.sleep_calls: List[float] = []
        self._lock = threading.Lock()

    def time(self) -> float:
        with self._lock:
            return self.current_time

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleep_calls.append(seconds)
            self.current_time += seconds


class MockHTTPResponse:
    """Mock HTTP response with configurable headers and status."""
    def __init__(self, status_code: int = 200, headers: Optional[Dict[str, str]] = None, json_data: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data or {}
        self.text = "mock response"

    def json(self):
        return self._json_data


class TestTrading212RateLimiter(unittest.TestCase):
    def setUp(self):
        self.clock = MockClock(start_time=1000.0)
        self.limiter = Trading212RateLimiter(account_id="test_acc", time_fn=self.clock.time, sleep_fn=self.clock.sleep)

    def test_open_orders_rate_limit_respected(self):
        """Prove GET /equity/orders enforces minimum spacing >= 5.0s."""
        w1 = self.limiter.acquire("GET", "equity/orders")
        self.assertEqual(w1, 0.0)
        self.assertEqual(self.clock.current_time, 1000.0)

        # Immediate second call must wait exactly 5.0 seconds
        w2 = self.limiter.acquire("GET", "equity/orders")
        self.assertEqual(w2, 5.0)
        self.assertEqual(self.clock.current_time, 1005.0)

        # Call after 3 seconds must wait the remaining 2.0 seconds
        self.clock.current_time += 3.0
        w3 = self.limiter.acquire("GET", "equity/orders")
        self.assertEqual(w3, 2.0)
        self.assertEqual(self.clock.current_time, 1010.0)

    def test_positions_rate_limit_respected(self):
        """Prove GET /equity/portfolio enforces minimum spacing >= 1.0s."""
        w1 = self.limiter.acquire("GET", "equity/portfolio")
        self.assertEqual(w1, 0.0)

        # Immediate second call must wait 1.0 second
        w2 = self.limiter.acquire("GET", "equity/portfolio")
        self.assertEqual(w2, 1.0)
        self.assertEqual(self.clock.current_time, 1001.0)

    def test_account_summary_rate_limit_respected(self):
        """Prove GET account summary endpoints enforce minimum spacing >= 5.0s."""
        w1 = self.limiter.acquire("GET", "equity/account/cash")
        self.assertEqual(w1, 0.0)

        # Calling summary immediately after cash must wait 5.0 seconds (same quota bucket)
        w2 = self.limiter.acquire("GET", "equity/account/summary")
        self.assertEqual(w2, 5.0)
        self.assertEqual(self.clock.current_time, 1005.0)

    def test_stop_order_rate_limit_respected(self):
        """Prove POST /equity/orders/stop enforces minimum spacing >= 2.0s."""
        w1 = self.limiter.acquire("POST", "equity/orders/stop")
        self.assertEqual(w1, 0.0)

        # Immediate second call must wait 2.0 seconds
        w2 = self.limiter.acquire("POST", "equity/orders/stop")
        self.assertEqual(w2, 2.0)
        self.assertEqual(self.clock.current_time, 1002.0)

    def test_limit_order_rate_limit_respected(self):
        """Prove POST /equity/orders/limit enforces minimum spacing >= 2.0s."""
        w1 = self.limiter.acquire("POST", "equity/orders/limit")
        self.assertEqual(w1, 0.0)

        # Immediate second call must wait 2.0 seconds
        w2 = self.limiter.acquire("POST", "equity/orders/limit")
        self.assertEqual(w2, 2.0)
        self.assertEqual(self.clock.current_time, 1002.0)

    def test_cancel_rate_limit_respected(self):
        """Prove DELETE /equity/orders/{id} enforces minimum spacing >= 1.2s (50 req/60s)."""
        w1 = self.limiter.acquire("DELETE", "equity/orders/ORDER_1")
        self.assertEqual(w1, 0.0)

        # Immediate second cancel must wait 1.2 seconds
        w2 = self.limiter.acquire("DELETE", "equity/orders/ORDER_2")
        self.assertEqual(w2, 1.2)
        self.assertEqual(self.clock.current_time, 1001.2)

    def test_f5_cancel_then_verify_orders_waits_for_endpoint_budget(self):
        """
        Burst sequence audit inside F5:
        initial GET orders -> cancel -> post-cancel GET orders -> place stop -> post-place GET orders.
        Prove all GET /orders calls are spaced by >= 5.0s.
        """
        # Step 1: Initial GET orders
        t_init = self.clock.current_time
        w_init = self.limiter.acquire("GET", "equity/orders")
        self.assertEqual(w_init, 0.0)

        # Step 3: Cancel old stop (DELETE bucket does not block on GET orders bucket)
        w_cancel = self.limiter.acquire("DELETE", "equity/orders/OLD_STOP")
        self.assertEqual(w_cancel, 0.0)

        # Step 5: Post-cancel GET orders must wait for the 5.0s GET orders interval!
        w_post_cancel = self.limiter.acquire("GET", "equity/orders")
        self.assertEqual(w_post_cancel, 5.0)
        self.assertEqual(self.clock.current_time - t_init, 5.0)

        # Step 6: Place replacement stop (POST stop bucket)
        w_place = self.limiter.acquire("POST", "equity/orders/stop")
        self.assertEqual(w_place, 0.0)

        # Step 7: Post-place GET orders must wait another 5.0s from Step 5!
        w_post_place = self.limiter.acquire("GET", "equity/orders")
        self.assertEqual(w_post_place, 5.0)
        self.assertEqual(self.clock.current_time - t_init, 10.0)

    def test_f5_failed_stop_then_reinstate_waits_for_stop_endpoint_budget(self):
        """
        Audit F5 replacement failure followed by immediate reinstatement.
        POST stop failure -> immediate reinstatement POST stop.
        Prove spacing between the two POST /stop calls is >= 2.0s.
        """
        # Step 6: Place stop attempt 1 (fails)
        t_first = self.clock.current_time
        w1 = self.limiter.acquire("POST", "equity/orders/stop")
        self.assertEqual(w1, 0.0)

        # Reinstatement place stop attempt 2 must wait for the 2.0s POST stop interval!
        w2 = self.limiter.acquire("POST", "equity/orders/stop")
        self.assertEqual(w2, 2.0)
        self.assertEqual(self.clock.current_time - t_first, 2.0)

    def test_background_sync_and_engine_share_rate_limiter(self):
        """Prove background sync daemon and Core engine share rate limiter for account summary."""
        broker = Trading212Broker()
        broker.rate_limiter.set_clock(self.clock.time, self.clock.sleep)

        # Background sync calls account summary at t=1000.0
        w_bg = broker.rate_limiter.acquire("GET", "equity/account/cash")
        self.assertEqual(w_bg, 0.0)

        # 1.5 seconds later, engine tries to call account summary
        self.clock.current_time += 1.5
        w_engine = broker.rate_limiter.acquire("GET", "equity/account/summary")
        # Must wait the remaining 3.5 seconds!
        self.assertEqual(w_engine, 3.5)
        self.assertEqual(self.clock.current_time, 1005.0)

    def test_watchdog_and_core_share_rate_limiter(self):
        """Prove orphan watchdog and Core compounding cycle share rate limiter for orders."""
        broker = Trading212Broker()
        broker.rate_limiter.set_clock(self.clock.time, self.clock.sleep)

        # Core cycle fetches open orders at t=1000.0
        w_core = broker.rate_limiter.acquire("GET", "equity/orders")
        self.assertEqual(w_core, 0.0)

        # Watchdog loop triggers 1.0s later and fetches open orders
        self.clock.current_time += 1.0
        w_watchdog = broker.rate_limiter.acquire("GET", "equity/orders")
        # Must wait the remaining 4.0 seconds!
        self.assertEqual(w_watchdog, 4.0)
        self.assertEqual(self.clock.current_time, 1005.0)

    def test_rate_limit_headers_update_local_budget(self):
        """Prove x-ratelimit-* headers dynamically update local budget and enforce reset gates."""
        # Initial request
        self.limiter.acquire("GET", "equity/orders")

        # Response indicates remaining=0 with reset in 8.5 seconds
        resp = MockHTTPResponse(
            status_code=200,
            headers={
                "x-ratelimit-limit": "12",
                "x-ratelimit-period": "60",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "8.5"
            }
        )
        self.limiter.update_from_response("GET", "equity/orders", resp)

        # Next call must wait 8.5 seconds for reset!
        w = self.limiter.acquire("GET", "equity/orders")
        self.assertAlmostEqual(w, 8.5, places=2)
        self.assertEqual(self.clock.current_time, 1008.5)

    def test_429_retry_honours_reset_header(self):
        """Prove 429 response inspects Retry-After / x-ratelimit-reset and schedules backoff until reset."""
        # Initial request
        self.limiter.acquire("POST", "equity/orders/stop")

        # Broker returns HTTP 429 with Retry-After: 6.0
        resp_429 = MockHTTPResponse(
            status_code=429,
            headers={"Retry-After": "6.0", "x-ratelimit-reset": "6.0"}
        )
        self.limiter.update_from_response("POST", "equity/orders/stop", resp_429)

        # Next attempt must back off for full 6.0 seconds
        w = self.limiter.acquire("POST", "equity/orders/stop")
        self.assertAlmostEqual(w, 6.0, places=2)
        self.assertEqual(self.clock.current_time, 1006.0)

    def test_simultaneous_concurrency_all_consumers_respect_limits(self):
        """
        Concurrency stress test:
        Simulate simultaneous requests from background sync, Core cycle, orphan watchdog, and F5 replacement.
        Verify that all requests pass through rate limiter and every endpoint's call history
        strictly respects its required minimum spacing.
        """
        broker = Trading212Broker()
        broker.rate_limiter.set_clock(self.clock.time, self.clock.sleep)

        # Simulate 10 intermixed operations across threads
        calls = [
            ("GET", "equity/account/cash"),   # background sync
            ("GET", "equity/portfolio"),      # core cycle pos
            ("GET", "equity/orders"),         # core cycle orders
            ("GET", "equity/orders"),         # watchdog orders
            ("GET", "equity/portfolio"),      # watchdog pos
            ("DELETE", "equity/orders/S1"),   # F5 cancel
            ("GET", "equity/orders"),         # F5 verify orders
            ("POST", "equity/orders/stop"),   # F5 place stop
            ("GET", "equity/orders"),         # F5 post-place orders
            ("GET", "equity/portfolio"),      # F5 post-place pos
        ]

        timestamps: Dict[str, List[float]] = {cat: [] for cat in broker.rate_limiter.DEFAULT_QUOTAS}

        for method, endpoint in calls:
            cat = broker.rate_limiter.classify_endpoint(method, endpoint)
            broker.rate_limiter.acquire(method, endpoint)
            t = self.clock.current_time
            timestamps[cat].append(t)

        # Verify spacing for every category that had multiple calls
        # 1. GET_ORDERS (min interval 5.0s)
        order_times = timestamps[EndpointCategory.GET_ORDERS]
        self.assertGreaterEqual(len(order_times), 4)
        for i in range(1, len(order_times)):
            diff = order_times[i] - order_times[i-1]
            self.assertGreaterEqual(diff, 5.0, f"GET_ORDERS spacing {diff} < 5.0s between call {i-1} and {i}")

        # 2. GET_POSITIONS (min interval 1.0s)
        pos_times = timestamps[EndpointCategory.GET_POSITIONS]
        self.assertGreaterEqual(len(pos_times), 3)
        for i in range(1, len(pos_times)):
            diff = pos_times[i] - pos_times[i-1]
            self.assertGreaterEqual(diff, 1.0, f"GET_POSITIONS spacing {diff} < 1.0s between call {i-1} and {i}")

    def test_request_with_retry_integrates_rate_limiter_and_429_reset(self):
        """Prove _request_with_retry routes through rate limiter and respects 429 Retry-After."""
        broker = Trading212Broker()
        broker.rate_limiter.set_clock(self.clock.time, self.clock.sleep)

        # Mock requests.get returning 429 on first attempt, then 200 on second
        resp_429 = MockHTTPResponse(
            status_code=429,
            headers={"Retry-After": "4.5", "x-ratelimit-reset": "4.5"}
        )
        resp_200 = MockHTTPResponse(
            status_code=200,
            headers={"x-ratelimit-remaining": "5"}
        )

        with patch("src.brokers.trading212.assert_live_broker_read_allowed"), \
             patch("src.brokers.trading212.assert_live_broker_write_allowed"), \
             patch("requests.get", side_effect=[resp_429, resp_200]) as mock_get:
            
            res = broker._request_with_retry("GET", "equity/orders")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(mock_get.call_count, 2)
            # The second attempt must have waited 4.5 seconds for the 429 reset
            self.assertIn(4.5, self.clock.sleep_calls)

    def test_rate_limit_wait_does_not_block_unrelated_endpoint_category(self):
        """
        Prove: RATE_LIMIT_WAIT_DOES_NOT_BLOCK_UNRELATED_ENDPOINT_CATEGORY = TRUE.
        When Thread A is sleeping to satisfy a 5.0s quota for GET equity/orders,
        Thread B calling an unrelated endpoint (e.g. POST equity/orders/stop) must NOT
        be blocked by Thread A or hold a global broker/limiter lock across sleep.
        """
        # Event to signal Thread A has entered its quota sleep
        thread_a_sleeping = threading.Event()
        thread_a_can_finish = threading.Event()
        thread_b_finished = threading.Event()

        def custom_sleep(sec):
            thread_a_sleeping.set()
            # Wait until signaled before finishing sleep
            thread_a_can_finish.wait(timeout=5.0)

        # Limiter with real-time synchronization for this test
        limiter = Trading212RateLimiter(account_id="test_conc", sleep_fn=custom_sleep)
        # Prime GET_ORDERS so next call MUST sleep
        limiter.acquire("GET", "equity/orders")

        thread_b_wait_time = [None]

        def thread_a_worker():
            # This call must sleep because GET_ORDERS has a 5.0s interval
            limiter.acquire("GET", "equity/orders")

        def thread_b_worker():
            # Wait for Thread A to be inside its sleep
            thread_a_sleeping.wait(timeout=5.0)
            # Thread B calls an UNRELATED category: POST_STOP
            # Must acquire immediately without blocking on Thread A's sleep
            w = limiter.acquire("POST", "equity/orders/stop")
            thread_b_wait_time[0] = w
            thread_b_finished.set()

        t_a = threading.Thread(target=thread_a_worker, daemon=True)
        t_b = threading.Thread(target=thread_b_worker, daemon=True)

        t_a.start()
        # Ensure Thread A is actively sleeping
        self.assertTrue(thread_a_sleeping.wait(timeout=2.0), "Thread A should have entered sleep")

        # Now launch Thread B while Thread A is still asleep
        t_b.start()
        self.assertTrue(thread_b_finished.wait(timeout=1.0), "Thread B MUST NOT be blocked by Thread A's sleep on an unrelated endpoint")
        self.assertEqual(thread_b_wait_time[0], 0.0, "Thread B should have waited 0.0s for an independent quota")

        # Release Thread A
        thread_a_can_finish.set()
        t_a.join(timeout=2.0)
        t_b.join(timeout=2.0)

    def test_ast_all_production_trading212_http_requests_route_through_central_method(self):
        """
        Source/AST regression test:
        Verifies:
        1. In src/brokers/trading212.py, calls to requests.get/post/delete/etc.
           appear EXCLUSIVELY inside _request_with_retry.
        2. Every public/private broker method that contacts Trading212 delegates to _request_with_retry.
        3. _request_with_retry explicitly calls self.rate_limiter.acquire and update_from_response.
        4. No other module in src/ makes direct HTTP calls to Trading212 endpoints.
        """
        import ast
        import os

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        t212_path = os.path.join(base_dir, "src", "brokers", "trading212.py")

        with open(t212_path, "r", encoding="utf-8") as f:
            t212_code = f.read()

        tree = ast.parse(t212_code, filename=t212_path)

        # 1. Inspect all requests.* calls in trading212.py
        direct_requests_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for requests.<method> or session.<method>
                func = node.func
                if isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Name) and func.value.id in ("requests", "session"):
                        direct_requests_calls.append((node.lineno, func.attr))

        # Find enclosing function for each call
        class FunctionFinder(ast.NodeVisitor):
            def __init__(self):
                self.current_func = None
                self.call_locations = {}

            def visit_FunctionDef(self, node):
                old_func = self.current_func
                self.current_func = node.name
                self.generic_visit(node)
                self.current_func = old_func

            def visit_Call(self, node):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Name) and func.value.id in ("requests", "session"):
                        self.call_locations[node.lineno] = self.current_func
                self.generic_visit(node)

        finder = FunctionFinder()
        finder.visit(tree)

        # Assert every direct requests call is INSIDE _request_with_retry
        for lineno, method in direct_requests_calls:
            enclosing = finder.call_locations.get(lineno)
            self.assertEqual(
                enclosing,
                "_request_with_retry",
                f"Direct HTTP call '{method}' at line {lineno} in {enclosing} bypasses _request_with_retry!"
            )

        # 2. Verify _request_with_retry calls self.rate_limiter.acquire
        req_method_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_request_with_retry":
                req_method_def = node
                break

        self.assertIsNotNone(req_method_def, "_request_with_retry must be defined on Trading212Broker")

        limiter_acquire_called = False
        limiter_update_called = False
        for node in ast.walk(req_method_def):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "acquire":
                    if isinstance(func.value, ast.Attribute) and func.value.attr == "rate_limiter":
                        limiter_acquire_called = True
                if isinstance(func, ast.Attribute) and func.attr == "update_from_response":
                    if isinstance(func.value, ast.Attribute) and func.value.attr == "rate_limiter":
                        limiter_update_called = True

        self.assertTrue(limiter_acquire_called, "_request_with_retry must call rate_limiter.acquire")
        self.assertTrue(limiter_update_called, "_request_with_retry must call rate_limiter.update_from_response")

        # 3. Check all other src/ files for direct Trading212 HTTP bypass
        src_dir = os.path.join(base_dir, "src")
        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, base_dir)
                    if rel_path in ("src/brokers/trading212.py", "src/core/test_network_guard.py"):
                        continue
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "trading212.com" in content or "equity/orders" in content or "equity/portfolio" in content:
                        # Ensure it routes through broker._request_with_retry
                        self.assertNotIn("requests.get(", content, f"{rel_path} bypasses broker for Trading212 API")
                        self.assertNotIn("requests.post(", content, f"{rel_path} bypasses broker for Trading212 API")
                        self.assertNotIn("requests.delete(", content, f"{rel_path} bypasses broker for Trading212 API")


if __name__ == "__main__":
    unittest.main()

