"""
PRV CAPITAL | F5 REGRESSION SUITE — PROTECTIVE-STOP LIFECYCLE
Remediation for F5: Protective-Stop Lifecycle State Machine

Defect & Broker Reality:
Trading212 does NOT allow overlapping full-position protective stops because an
existing stop reserves the held shares (triggers 'selling-equity-not-owned', owned: 0.0).
F5 establishes an explicit cancel-first lifecycle with authoritative broker confirmation,
deterministic reinstatement on replacement failure, restart safety across every
transition, and enforcement that partial-fill/window-close states cannot become
terminal without confirmed protection (TERMINAL_PARTIAL_STATE_REQUIRES_CONFIRMED_STOP = TRUE).

Mock-only. Hermetic. No live broker read or write.
"""
import copy
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import broker
from src.core.engine import PRVQuantEngine
from src.database.db import db
from tests._provenance_mocks import provenance_aware, stale


class TestF5ProtectiveStopLifecycle(unittest.TestCase):
    """
    Comprehensive regression suite for F5: Protective-Stop Lifecycle.
    Covers all 36 test cases and institutional invariants.
    """

    def setUp(self):
        self.ticker = "EMIMl_EQ"
        self.held_qty = 100.0
        self.target_stop_price = 4062.10

    # =========================================================================
    # TEST CASE 01: Already-correct stop -> keep, 0 broker write
    # =========================================================================
    def test_case_01_already_correct_stop_kept_zero_broker_writes(self):
        """Case 1: Exactly matching stop already exists. Keep it with 0 broker mutations."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = [{
            "id": "STOP_VALID_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "KEPT_EXISTING")
            self.assertEqual(res.get("order_id"), "STOP_VALID_1")
            self.assertEqual(mock_place.call_count, 0, "Zero stop placements when stop already correct")
            self.assertEqual(mock_cancel.call_count, 0, "Zero cancellations when stop already correct")

    # =========================================================================
    # TEST CASE 02: Wrong stop price -> cancel & replace
    # =========================================================================
    def test_case_02_wrong_stop_price_cancels_and_replaces(self):
        """Case 2: Existing stop has wrong stop price -> cancel old & place replacement."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,  # Wrong price
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_NEW_1",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(mock_cancel.call_count, 1)
            mock_cancel.assert_called_with("STOP_OLD_1")
            self.assertEqual(mock_place.call_count, 1)
            self.assertEqual(res.get("order_id"), "STOP_NEW_1")

    # =========================================================================
    # TEST CASE 03: Wrong quantity too small -> cancel & replace
    # =========================================================================
    def test_case_03_wrong_quantity_too_small_cancels_and_replaces(self):
        """Case 3: Existing stop quantity too small -> cancel & replace with full quantity."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_SMALL",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -50.0,  # Too small (50 < 100)
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_NEW_FULL",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(res.get("quantity"), self.held_qty)
            mock_cancel.assert_called_once_with("STOP_OLD_SMALL")

    # =========================================================================
    # TEST CASE 04: Wrong quantity too large -> cancel & replace
    # =========================================================================
    def test_case_04_wrong_quantity_too_large_cancels_and_replaces(self):
        """Case 4: Existing stop quantity too large -> cancel & replace with exact held quantity."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_LARGE",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -200.0,  # Too large
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_NEW_CORRECT",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(res.get("quantity"), self.held_qty)

    # =========================================================================
    # TEST CASE 05: DAY stop instead of GTC -> cancel & replace with GTC
    # =========================================================================
    def test_case_05_day_stop_instead_of_gtc_cancels_and_replaces(self):
        """Case 5: Existing stop has DAY validity -> cancel & replace with GOOD_TILL_CANCEL."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_DAY",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",  # Invalid validity
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_GTC",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(res.get("timeValidity"), "GOOD_TILL_CANCEL")
            mock_cancel.assert_called_once_with("STOP_DAY")

    # =========================================================================
    # TEST CASE 06: Duplicate stops -> cancel all & replace with single valid stop
    # =========================================================================
    def test_case_06_duplicate_stops_cancelled_and_replaced_with_single_valid_stop(self):
        """Case 6: Duplicate stops exist -> cancel all duplicates and place 1 valid stop."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [
            {
                "id": "STOP_DUP_1",
                "ticker": self.ticker,
                "type": "STOP",
                "stopPrice": self.target_stop_price,
                "quantity": -self.held_qty,
                "timeValidity": "GOOD_TILL_CANCEL",
                "side": "SELL"
            },
            {
                "id": "STOP_DUP_2",
                "ticker": self.ticker,
                "type": "STOP",
                "stopPrice": self.target_stop_price,
                "quantity": -self.held_qty,
                "timeValidity": "GOOD_TILL_CANCEL",
                "side": "SELL"
            }
        ]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_SINGLE_NEW",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(mock_cancel.call_count, 2, "Must cancel both duplicate stops")
            self.assertEqual(len(live_orders), 1, "Exactly one stop remains on book")

    # =========================================================================
    # TEST CASE 07: No stop -> place new stop
    # =========================================================================
    def test_case_07_no_stop_places_new_stop(self):
        """Case 7: Position held but zero stops -> place new GTC protective stop."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = []

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_FIRST_NEW",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order") as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(mock_cancel.call_count, 0)
            self.assertEqual(mock_place.call_count, 1)

    # =========================================================================
    # TEST CASE 08: Authoritative positions unavailable -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_08_authoritative_positions_unavailable_fails_closed(self):
        """Case 8: Position read is stale/non-authoritative -> fail closed to PENDING_RECONCILIATION."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = []

        with patch.object(broker, "get_open_positions", side_effect=stale(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("pending_reconciliation"))
            self.assertEqual(mock_place.call_count, 0)
            self.assertEqual(mock_cancel.call_count, 0)

    # =========================================================================
    # TEST CASE 09: Authoritative orders unavailable -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_09_authoritative_orders_unavailable_fails_closed(self):
        """Case 9: Orders read is stale/non-authoritative -> fail closed to PENDING_RECONCILIATION."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = []

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=stale(orders)), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("pending_reconciliation"))
            self.assertEqual(mock_place.call_count, 0)
            self.assertEqual(mock_cancel.call_count, 0)

    # =========================================================================
    # TEST CASE 10: Cancel 500 error -> PENDING_RECONCILIATION, do not proceed
    # =========================================================================
    def test_case_10_cancel_500_error_fails_closed(self):
        """Case 10: Cancel returns HTTP 500 -> fail closed to PENDING_RECONCILIATION, old stop preserved."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = [{
            "id": "STOP_OLD_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "cancel_order", return_value={"success": False, "error": "HTTP 500 Server Error"}) as mock_cancel, \
             patch.object(broker, "place_stop_order") as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("old_stop_present"))
            self.assertEqual(mock_place.call_count, 0, "Do NOT place replacement if cancel fails")

    # =========================================================================
    # TEST CASE 11: Cancel timeout -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_11_cancel_timeout_fails_closed(self):
        """Case 11: Cancel raises Timeout -> fail closed to PENDING_RECONCILIATION, do not place."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = [{
            "id": "STOP_OLD_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "cancel_order", side_effect=TimeoutError("Request timed out")) as mock_cancel, \
             patch.object(broker, "place_stop_order") as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("old_stop_present"))
            self.assertEqual(mock_place.call_count, 0)

    # =========================================================================
    # TEST CASE 12: Cancel UNKNOWN -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_12_cancel_unknown_response_fails_closed(self):
        """Case 12: Cancel returns non-dict or unparseable response -> fail closed."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = [{
            "id": "STOP_OLD_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "cancel_order", return_value="INVALID_RETURN") as mock_cancel, \
             patch.object(broker, "place_stop_order") as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("old_stop_present"))
            self.assertEqual(mock_place.call_count, 0)

    # =========================================================================
    # TEST CASE 13: Cancel says success but stop still present -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_13_cancel_success_but_stop_still_present_fails_closed(self):
        """Case 13: Cancel returned success, but post-cancel read shows stop still present."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        old_stop = {
            "id": "STOP_GHOST_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }
        live_orders = [old_stop]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", return_value={"success": True}) as mock_cancel, \
             patch.object(broker, "place_stop_order") as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("old_stop_present"))
            self.assertEqual(mock_place.call_count, 0, "Do NOT proceed to place if old stop is still present")

    # =========================================================================
    # TEST CASE 14: Cancel success + authoritative absence -> proceeds to placement
    # =========================================================================
    def test_case_14_cancel_success_and_authoritative_absence_proceeds_to_place(self):
        """Case 14: Cancel reports success AND authoritative post-cancel read confirms absence."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", return_value={"success": False, "error": "test abort"}) as mock_place:

            broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            mock_cancel.assert_called_once_with("STOP_OLD_1")
            self.assertTrue(mock_place.called, "Proceeded to place replacement once absence confirmed")

    # =========================================================================
    # TEST CASE 15: Replacement 500 -> triggers reinstatement
    # =========================================================================
    def test_case_15_replacement_500_triggers_reinstatement(self):
        """Case 15: Replacement returns HTTP 500 -> triggers reinstatement of previous stop."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_ORIG_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return {"success": False, "error": "HTTP 500 Server Error"}
            # Reinstatement call
            reinstated_ord = {
                "id": "STOP_REINSTATED_1",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated_ord)
            return {"success": True, "data": reinstated_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertEqual(len(place_calls), 2, "1 replacement attempt + 1 reinstatement attempt")
            self.assertEqual(place_calls[0]["price"], self.target_stop_price)
            self.assertEqual(place_calls[1]["price"], self.target_stop_price, "Reinstated original stop price")
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "REINSTATED_ORIGINAL")
            self.assertTrue(res.get("protection_active"))

    # =========================================================================
    # TEST CASE 16: Replacement timeout -> triggers reinstatement
    # =========================================================================
    def test_case_16_replacement_timeout_triggers_reinstatement(self):
        """Case 16: Replacement times out -> triggers reinstatement of previous stop."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_ORIG_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                raise TimeoutError("Network timeout on placement")
            reinstated_ord = {
                "id": "STOP_REINSTATED_1",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated_ord)
            return {"success": True, "data": reinstated_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertEqual(len(place_calls), 2)
            self.assertEqual(res.get("action"), "REINSTATED_ORIGINAL")
            self.assertTrue(res.get("protection_active"))

    # =========================================================================
    # TEST CASE 17: Replacement UNKNOWN -> triggers reinstatement
    # =========================================================================
    def test_case_17_replacement_unknown_triggers_reinstatement(self):
        """Case 17: Replacement returns unknown response -> triggers reinstatement."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_ORIG_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return "UNEXPECTED_STRING_RESPONSE"
            reinstated_ord = {
                "id": "STOP_REINSTATED_1",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated_ord)
            return {"success": True, "data": reinstated_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertEqual(len(place_calls), 2)
            self.assertEqual(res.get("action"), "REINSTATED_ORIGINAL")
            self.assertTrue(res.get("protection_active"))

    # =========================================================================
    # TEST CASE 18: Replacement success but post-place state non-authoritative -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_18_replacement_success_but_post_place_non_authoritative_fails_closed(self):
        """Case 18: Placement returned success, but post-place verification read is stale."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = []

        read_count = [0]
        def _orders(*a, **k):
            read_count[0] += 1
            fresh = (read_count[0] == 1)
            data = list(live_orders)
            return (data, fresh) if k.get("return_provenance") else data

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders), \
             patch.object(broker, "place_stop_order", return_value={"success": True, "data": {"id": "123"}}):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("pending_reconciliation"))

    # =========================================================================
    # TEST CASE 19: Replacement success but stop qty wrong -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_19_replacement_success_but_stop_qty_wrong_fails_closed(self):
        """Case 19: Placement returned success, but post-place stop qty does not match position."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        placed_stop = {
            "id": "STOP_WRONG_QTY",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -50.0,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }

        read_count = [0]
        def _orders(*a, **k):
            read_count[0] += 1
            data = [] if read_count[0] == 1 else [placed_stop]
            return (data, True) if k.get("return_provenance") else data

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders), \
             patch.object(broker, "place_stop_order", return_value={"success": True, "data": placed_stop}):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")

    # =========================================================================
    # TEST CASE 20: Replacement success but stop price wrong -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_20_replacement_success_but_stop_price_wrong_fails_closed(self):
        """Case 20: Placement returned success, but post-place stop price does not match target."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        placed_stop = {
            "id": "STOP_WRONG_PRICE",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3800.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }

        read_count = [0]
        def _orders(*a, **k):
            read_count[0] += 1
            data = [] if read_count[0] == 1 else [placed_stop]
            return (data, True) if k.get("return_provenance") else data

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders), \
             patch.object(broker, "place_stop_order", return_value={"success": True, "data": placed_stop}):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")

    # =========================================================================
    # TEST CASE 21: Replacement success but DAY validity -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_21_replacement_success_but_day_validity_fails_closed(self):
        """Case 21: Placement returned success, but post-place stop has DAY validity instead of GTC."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        placed_stop = {
            "id": "STOP_DAY_RETURNED",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }

        read_count = [0]
        def _orders(*a, **k):
            read_count[0] += 1
            data = [] if read_count[0] == 1 else [placed_stop]
            return (data, True) if k.get("return_provenance") else data

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders), \
             patch.object(broker, "place_stop_order", return_value={"success": True, "data": placed_stop}):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")

    # =========================================================================
    # TEST CASE 22: Replacement success but duplicate remains -> PENDING_RECONCILIATION
    # =========================================================================
    def test_case_22_replacement_success_but_duplicate_remains_fails_closed(self):
        """Case 22: Placement returned success, but post-place verification finds multiple stops."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        stops = [
            {
                "id": "STOP_DUP_A",
                "ticker": self.ticker,
                "type": "STOP",
                "stopPrice": self.target_stop_price,
                "quantity": -self.held_qty,
                "timeValidity": "GOOD_TILL_CANCEL",
                "side": "SELL"
            },
            {
                "id": "STOP_DUP_B",
                "ticker": self.ticker,
                "type": "STOP",
                "stopPrice": self.target_stop_price,
                "quantity": -self.held_qty,
                "timeValidity": "GOOD_TILL_CANCEL",
                "side": "SELL"
            }
        ]

        read_count = [0]
        def _orders(*a, **k):
            read_count[0] += 1
            data = [] if read_count[0] == 1 else stops
            return (data, True) if k.get("return_provenance") else data

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders), \
             patch.object(broker, "place_stop_order", return_value={"success": True, "data": stops[0]}):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")

    # =========================================================================
    # TEST CASE 23: Replacement success + exactly one valid stop -> PLACED_NEW
    # =========================================================================
    def test_case_23_replacement_success_and_authoritatively_verified_returns_placed_new(self):
        """Case 23: Clean replacement flow: cancel old, verify absence, place new, verify post-place -> PLACED_NEW."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_NEW_VERIFIED",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(res.get("order_id"), "STOP_NEW_VERIFIED")
            self.assertEqual(res.get("timeValidity"), "GOOD_TILL_CANCEL")
            self.assertEqual(res.get("stopPrice"), self.target_stop_price)
            self.assertEqual(res.get("quantity"), self.held_qty)

    # =========================================================================
    # TEST CASE 24: Reinstatement success -> REINSTATED_ORIGINAL, protection_active=True
    # =========================================================================
    def test_case_24_reinstatement_success_reports_reinstated_original(self):
        """Case 24: Replacement fails, original stop successfully reinstated and verified."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orig_stop = {
            "id": "STOP_ORIG_SAFE",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }
        live_orders = [orig_stop]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_count = [0]
        def _place(ticker, quantity, stop_price, time_validity):
            place_count[0] += 1
            if place_count[0] == 1:
                return {"success": False, "error": "Broker rejected new stop"}
            reinstated = {
                "id": "STOP_REINSTATED_OK",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"), "Must report success=False because replacement failed")
            self.assertEqual(res.get("action"), "REINSTATED_ORIGINAL")
            self.assertTrue(res.get("protection_active"), "Protection must remain active via reinstated stop")
            self.assertEqual(res.get("order_id"), "STOP_REINSTATED_OK")
            self.assertEqual(res.get("stopPrice"), self.target_stop_price)

    # =========================================================================
    # TEST CASE 25: Reinstatement failure -> EMERGENCY_UNPROTECTED, naked_position_hazard=True
    # =========================================================================
    def test_case_25_reinstatement_failure_reports_emergency_unprotected(self):
        """Case 25: Replacement fails AND reinstatement fails -> EMERGENCY_UNPROTECTED."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orig_stop = {
            "id": "STOP_ORIG",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3950.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }
        live_orders = [orig_stop]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", return_value={"success": False, "error": "Hard Broker Reject"}):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "EMERGENCY_UNPROTECTED")
            self.assertTrue(res.get("naked_position_hazard"), "Must set naked_position_hazard=True")
            self.assertFalse(res.get("protection_active"))

    # =========================================================================
    # TEST CASE 26: Restart safety: restart before cancel
    # =========================================================================
    def test_case_26_restart_before_cancel_discovers_existing_stop(self):
        """Case 26: Restart before cancel -> fresh process discovers existing stop cleanly."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_PRE_RESTART",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_POST_RESTART",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            mock_cancel.assert_called_once_with("STOP_PRE_RESTART")

    # =========================================================================
    # TEST CASE 27: Restart safety: restart after cancel request
    # =========================================================================
    def test_case_27_restart_after_cancel_request_pending_until_absence_confirmed(self):
        """Case 27: Restart after cancel request sent: if stop still visible, fails closed to pending reconciliation."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_CANCELLING",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(live_orders)), \
             patch.object(broker, "cancel_order", return_value={"success": False, "error": "Order already pending cancel"}), \
             patch.object(broker, "place_stop_order") as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertEqual(mock_place.call_count, 0)

    # =========================================================================
    # TEST CASE 28: Restart safety: restart after confirmed cancel
    # =========================================================================
    def test_case_28_restart_after_confirmed_cancel_places_replacement(self):
        """Case 28: Restart after cancel confirmed absent: sees held position with 0 stops -> places new stop."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = []

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_FRESH_AFTER_RESTART",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order") as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(mock_cancel.call_count, 0)
            self.assertEqual(mock_place.call_count, 1)

    # =========================================================================
    # TEST CASE 29: Restart safety: restart after replacement submit
    # =========================================================================
    def test_case_29_restart_after_replacement_submit_recovers_submitted_stop(self):
        """Case 29: Restart occurred right after replacement submission -> next run finds the submitted stop and keeps it."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = [{
            "id": "STOP_SUBMITTED_PRE_RESTART",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "KEPT_EXISTING")
            self.assertEqual(res.get("order_id"), "STOP_SUBMITTED_PRE_RESTART")
            self.assertEqual(mock_place.call_count, 0)
            self.assertEqual(mock_cancel.call_count, 0)

    # =========================================================================
    # TEST CASE 30: Restart safety: restart after replacement accepted
    # =========================================================================
    def test_case_30_restart_after_replacement_accepted_authoritative_verification_succeeds(self):
        """Case 30: Restart after replacement accepted -> authoritative verification succeeds, zero churn."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = [{
            "id": "STOP_ACCEPTED_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "KEPT_EXISTING")
            self.assertEqual(mock_place.call_count, 0)
            self.assertEqual(mock_cancel.call_count, 0)

    # =========================================================================
    # TEST CASE 31: Restart safety: restart during pending reconciliation
    # =========================================================================
    def test_case_31_restart_during_pending_reconciliation_stays_pending(self):
        """Case 31: Restart occurs while broker state is degraded -> stays in pending reconciliation."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = []

        with patch.object(broker, "get_open_positions", side_effect=stale(positions)), \
             patch.object(broker, "get_open_orders", side_effect=stale(orders)):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertTrue(res.get("pending_reconciliation"))

    # =========================================================================
    # TEST CASE 32: Partial fill 400 shares -> stop exactly 400
    # =========================================================================
    def test_case_32_partial_fill_400_shares_sets_stop_exactly_400(self):
        """Case 32: Partial fill of 400 shares -> places stop of exactly 400 shares."""
        partial_qty = 400.0
        positions = [{"ticker": self.ticker, "quantity": partial_qty, "averagePrice": 4145.0}]
        live_orders = []

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_PARTIAL_400",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, partial_qty, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(res.get("quantity"), 400.0)
            mock_place.assert_called_once_with(
                ticker=self.ticker,
                quantity=-400.0,
                stop_price=self.target_stop_price,
                time_validity="GOOD_TILL_CANCEL"
            )

    # =========================================================================
    # TEST CASE 33: Later additional fill -> stop expands to final held qty
    # =========================================================================
    def test_case_33_additional_fill_expands_stop_to_final_held_qty(self):
        """Case 33: Position expands from 400 to 600 -> cancel 400 stop, place 600 stop."""
        positions = [{"ticker": self.ticker, "quantity": 600.0, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_400",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -400.0,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        def _place(ticker, quantity, stop_price, time_validity):
            new_ord = {
                "id": "STOP_EXPANDED_600",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(new_ord)
            return {"success": True, "data": new_ord}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel) as mock_cancel, \
             patch.object(broker, "place_stop_order", side_effect=_place) as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, 600.0, self.target_stop_price)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "PLACED_NEW")
            self.assertEqual(res.get("quantity"), 600.0)
            mock_cancel.assert_called_once_with("STOP_OLD_400")
            mock_place.assert_called_once_with(
                ticker=self.ticker,
                quantity=-600.0,
                stop_price=self.target_stop_price,
                time_validity="GOOD_TILL_CANCEL"
            )

    # =========================================================================
    # TEST CASE 34: Window close cannot become terminal without confirmed stop
    # =========================================================================
    def test_case_34_window_close_cannot_become_terminal_without_confirmed_stop(self):
        """Case 34: In engine reconciliation, partial fill cannot become PARTIALLY_FILLED_WINDOW_CLOSED without confirmed stop."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        engine = PRVQuantEngine()
        engine.paper_mode = False

        working_decision = {
            "dedup_key": "core_compounding_test_key",
            "target_instrument": "EMIMl_EQ",
            "broker_order_id": "112233",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "limit_price": 41.45,
            "units": 100
        }

        pos_match = [{"ticker": "EMIMl_EQ", "quantity": 50.0, "averagePrice": 4145.0}]
        orders = []

        # Friday at 08:10:00 BST (past window)
        past_window_dt = datetime(2026, 9, 11, 8, 10, 0, tzinfo=ZoneInfo("Europe/London"))

        # SUB-CASE A: Stop sync fails -> must stay WINDOW_CLOSE_PENDING_RECONCILIATION
        with patch.object(db, "get_pending_reconciliation_decision", return_value=working_decision), \
             patch.object(db, "update_core_compounding_decision_status") as mock_db_update, \
             patch.object(broker, "sync_broker_stop_order", return_value={"success": False, "action": "PENDING_RECONCILIATION"}):

            result_msg = engine.reconcile_unknown_submissions(
                open_positions=pos_match,
                open_orders=orders,
                positions_authoritative=True,
                orders_authoritative=True,
                current_time=past_window_dt,
                bypass_execution_window=False
            )

            self.assertTrue(mock_db_update.called)
            call_kwargs = mock_db_update.call_args[1]
            self.assertEqual(
                call_kwargs.get("status"),
                "WINDOW_CLOSE_PENDING_RECONCILIATION",
                "TERMINAL_PARTIAL_STATE_REQUIRES_CONFIRMED_STOP invariant violated!"
            )
            self.assertIn("WINDOW_CLOSE_PENDING_RECONCILIATION", result_msg)

        # SUB-CASE B: Stop sync succeeds -> can transition to PARTIALLY_FILLED_WINDOW_CLOSED
        with patch.object(db, "get_pending_reconciliation_decision", return_value=working_decision), \
             patch.object(db, "update_core_compounding_decision_status") as mock_db_update, \
             patch.object(broker, "sync_broker_stop_order", return_value={"success": True, "action": "PLACED_NEW"}):

            result_msg = engine.reconcile_unknown_submissions(
                open_positions=pos_match,
                open_orders=orders,
                positions_authoritative=True,
                orders_authoritative=True,
                current_time=past_window_dt,
                bypass_execution_window=False
            )

            self.assertTrue(mock_db_update.called)
            call_kwargs = mock_db_update.call_args[1]
            self.assertEqual(
                call_kwargs.get("status"),
                "PARTIALLY_FILLED_WINDOW_CLOSED",
                "Should transition to PARTIALLY_FILLED_WINDOW_CLOSED when stop is confirmed"
            )
            self.assertIn("PARTIALLY_FILLED_WINDOW_CLOSED", result_msg)

    # =========================================================================
    # TEST CASE 35: Cached stale orders cannot count as confirmation
    # =========================================================================
    def test_case_35_cached_stale_orders_cannot_count_as_confirmation(self):
        """Case 35: Bare list returned without provenance -> treated as stale -> fails closed."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders_bare_list = [{
            "id": "STOP_BARE_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _orders_no_provenance(*args, **kwargs):
            return list(orders_bare_list)

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders_no_provenance), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertEqual(mock_place.call_count, 0)
            self.assertEqual(mock_cancel.call_count, 0)

    # =========================================================================
    # TEST CASE 36: Cached stale positions cannot count as confirmation
    # =========================================================================
    def test_case_36_cached_stale_positions_cannot_count_as_confirmation(self):
        """Case 36: Bare list returned for positions without provenance -> treated as stale -> fails closed."""
        positions_bare_list = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        orders = []

        def _positions_no_provenance(*args, **kwargs):
            return list(positions_bare_list)

        with patch.object(broker, "get_open_positions", side_effect=_positions_no_provenance), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)), \
             patch.object(broker, "place_stop_order") as mock_place, \
             patch.object(broker, "cancel_order") as mock_cancel:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertEqual(mock_place.call_count, 0)
            self.assertEqual(mock_cancel.call_count, 0)

    # =========================================================================
    # MUTATION ASSERTIONS ON GUARDS
    # =========================================================================
    def test_mutation_guard_no_position_returns_no_position_action(self):
        """Guard mutation: When positions has 0 qty or missing ticker, returns action NO_POSITION."""
        positions = [{"ticker": "OTHERl_EQ", "quantity": 100.0, "averagePrice": 100.0}]
        orders = []

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(orders)):

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "NO_POSITION")

    def test_mutation_guard_cancel_absence_verification_raises_exception(self):
        """Guard mutation: If post-cancel order read raises an exception, fail closed to PENDING_RECONCILIATION."""
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_1",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3900.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        read_count = [0]
        def _orders(*a, **k):
            read_count[0] += 1
            if read_count[0] == 2:
                raise ConnectionResetError("Broker socket dropped")
            return (list(live_orders), True) if k.get("return_provenance") else list(live_orders)

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=_orders), \
             patch.object(broker, "cancel_order", return_value={"success": True}), \
             patch.object(broker, "place_stop_order") as mock_place:

            res = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("action"), "PENDING_RECONCILIATION")
            self.assertEqual(mock_place.call_count, 0)

    # =========================================================================
    # BLOCKER 2 REQUIRED TESTS:
    # REINSTATEMENT ONLY COUNTS AS PROTECTION IF VALID FOR CURRENT POSITION
    # Invariant: REINSTATED_STOP_COUNTS_AS_PROTECTION_ONLY_IF_VALID_FOR_CURRENT_POSITION = TRUE
    # =========================================================================

    def test_f5_reinstate_old_qty_smaller_than_current_position_is_not_full_protection(self):
        """
        F5_REINSTATE_OLD_QTY_SMALLER_THAN_CURRENT_POSITION_IS_NOT_FULL_PROTECTION
        Holding expanded to 600 shares, but reinstated stop has old quantity of 400 shares.
        Leaves 200 shares unprotected -> MUST NOT mark protection_active=True.
        Must return EMERGENCY_PARTIALLY_PROTECTED, naked_position_hazard=True, underprotected_position_hazard=True.
        """
        current_held = 600.0
        old_stop_qty = 400.0
        target_price = 4062.10

        positions = [{"ticker": self.ticker, "quantity": current_held, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_400",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": target_price,
            "quantity": -old_stop_qty,
            "timeValidity": "DAY",  # trigger replacement
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return {"success": False, "error": "Replacement 600 stop failed"}
            reinstated = {
                "id": "STOP_REINSTATED_400",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,  # -400.0
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, current_held, target_price)

            self.assertFalse(res.get("success"), "Replacement failed")
            self.assertFalse(res.get("protection_active"), "Reinstated 400 stop does not protect 600 holding")
            self.assertEqual(res.get("action"), "EMERGENCY_PARTIALLY_PROTECTED")
            self.assertTrue(res.get("naked_position_hazard"))
            self.assertTrue(res.get("underprotected_position_hazard"))
            self.assertEqual(res.get("quantity"), 400.0)

    def test_f5_reinstate_old_qty_larger_than_current_position_is_not_full_protection(self):
        """
        F5_REINSTATE_OLD_QTY_LARGER_THAN_CURRENT_POSITION_IS_NOT_FULL_PROTECTION
        Holding reduced to 400 shares, but reinstated stop has old quantity of 600 shares.
        Over-allocated stop exceeds held equity -> MUST NOT mark protection_active=True.
        Must return EMERGENCY_PARTIALLY_PROTECTED, naked_position_hazard=True, underprotected_position_hazard=True.
        """
        current_held = 400.0
        old_stop_qty = 600.0
        target_price = 4062.10

        positions = [{"ticker": self.ticker, "quantity": current_held, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_600",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": target_price,
            "quantity": -old_stop_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return {"success": False, "error": "Replacement 400 stop failed"}
            reinstated = {
                "id": "STOP_REINSTATED_600",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,  # -600.0
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, current_held, target_price)

            self.assertFalse(res.get("success"), "Replacement failed")
            self.assertFalse(res.get("protection_active"), "Reinstated 600 stop exceeds 400 holding")
            self.assertEqual(res.get("action"), "EMERGENCY_PARTIALLY_PROTECTED")
            self.assertTrue(res.get("naked_position_hazard"))
            self.assertTrue(res.get("underprotected_position_hazard"))
            self.assertEqual(res.get("quantity"), 600.0)

    def test_f5_reinstate_old_price_wrong_for_current_risk_rule_is_not_full_protection(self):
        """
        F5_REINSTATE_OLD_PRICE_WRONG_FOR_CURRENT_RISK_RULE_IS_NOT_FULL_PROTECTION
        Holding is 400 shares. Current required Core risk rule requires stop at 800.00.
        Reinstated stop has old price 750.00 -> does NOT satisfy Core risk rule.
        Must return EMERGENCY_PARTIALLY_PROTECTED, naked_position_hazard=True, underprotected_position_hazard=True.
        """
        current_held = 400.0
        target_price = 800.00
        old_price = 750.00

        positions = [{"ticker": self.ticker, "quantity": current_held, "averagePrice": 820.0}]
        live_orders = [{
            "id": "STOP_OLD_PRICE",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": old_price,
            "quantity": -current_held,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return {"success": False, "error": "Replacement stop at 800.00 failed"}
            reinstated = {
                "id": "STOP_REINSTATED_750",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, current_held, target_price)

            self.assertFalse(res.get("success"))
            self.assertFalse(res.get("protection_active"), "Reinstated stop at 750.00 violates risk rule (required 800.00)")
            self.assertEqual(res.get("action"), "EMERGENCY_PARTIALLY_PROTECTED")
            self.assertTrue(res.get("naked_position_hazard"))
            self.assertTrue(res.get("underprotected_position_hazard"))
            self.assertEqual(res.get("stopPrice"), 750.00)

    def test_f5_reinstate_only_counts_protected_if_matches_current_held_qty(self):
        """
        F5_REINSTATE_ONLY_COUNTS_PROTECTED_IF_MATCHES_CURRENT_HELD_QTY
        Proves that when reinstated stop matches current held quantity exactly (500 == 500)
        AND satisfies current risk price rule, protection_active=True and action=REINSTATED_ORIGINAL.
        """
        current_held = 500.0
        target_price = 4062.10

        positions = [{"ticker": self.ticker, "quantity": current_held, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_500",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": target_price,
            "quantity": -current_held,
            "timeValidity": "DAY",  # trigger replacement to GTC
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return {"success": False, "error": "New GTC stop placement failed"}
            reinstated = {
                "id": "STOP_REINSTATED_500",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            res = broker.sync_broker_stop_order(self.ticker, current_held, target_price)

            self.assertFalse(res.get("success"), "Replacement failed")
            self.assertTrue(res.get("protection_active"), "Reinstated stop exactly matches held qty (500) and risk price")
            self.assertEqual(res.get("action"), "REINSTATED_ORIGINAL")
            self.assertFalse(res.get("naked_position_hazard", False))
            self.assertFalse(res.get("underprotected_position_hazard", False))
            self.assertEqual(res.get("quantity"), 500.0)

    def test_f5_reinstate_only_counts_protected_if_price_matches_current_risk_rule(self):
        """
        F5_REINSTATE_ONLY_COUNTS_PROTECTED_IF_PRICE_MATCHES_CURRENT_RISK_RULE
        Contrasts two scenarios:
        1. When reinstated stop price does NOT match risk rule (target 4062.10, old 3950.00):
           returns EMERGENCY_PARTIALLY_PROTECTED, protection_active=False.
        2. When reinstated stop price DOES match risk rule (target 4062.10, old 4062.10):
           returns REINSTATED_ORIGINAL, protection_active=True.
        """
        # Part 1: Price does NOT match
        positions = [{"ticker": self.ticker, "quantity": self.held_qty, "averagePrice": 4145.0}]
        live_orders_1 = [{
            "id": "STOP_WRONG_PRICE",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": 3950.00,
            "quantity": -self.held_qty,
            "timeValidity": "GOOD_TILL_CANCEL",
            "side": "SELL"
        }]

        def _cancel_1(order_id):
            live_orders_1[:] = [o for o in live_orders_1 if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls_1 = []
        def _place_1(ticker, quantity, stop_price, time_validity):
            place_calls_1.append(stop_price)
            if len(place_calls_1) == 1:
                return {"success": False, "error": "Replacement failed"}
            reinstated = {
                "id": "STOP_REINSTATED_1",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders_1.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders_1)), \
             patch.object(broker, "cancel_order", side_effect=_cancel_1), \
             patch.object(broker, "place_stop_order", side_effect=_place_1):

            res1 = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)
            self.assertFalse(res1.get("protection_active"))
            self.assertEqual(res1.get("action"), "EMERGENCY_PARTIALLY_PROTECTED")

        # Part 2: Price DOES match
        live_orders_2 = [{
            "id": "STOP_RIGHT_PRICE",
            "ticker": self.ticker,
            "type": "STOP",
            "stopPrice": self.target_stop_price,
            "quantity": -self.held_qty,
            "timeValidity": "DAY",
            "side": "SELL"
        }]

        def _cancel_2(order_id):
            live_orders_2[:] = [o for o in live_orders_2 if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls_2 = []
        def _place_2(ticker, quantity, stop_price, time_validity):
            place_calls_2.append(stop_price)
            if len(place_calls_2) == 1:
                return {"success": False, "error": "Replacement failed"}
            reinstated = {
                "id": "STOP_REINSTATED_2",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders_2.append(reinstated)
            return {"success": True, "data": reinstated}

        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders_2)), \
             patch.object(broker, "cancel_order", side_effect=_cancel_2), \
             patch.object(broker, "place_stop_order", side_effect=_place_2):

            res2 = broker.sync_broker_stop_order(self.ticker, self.held_qty, self.target_stop_price)
            self.assertTrue(res2.get("protection_active"))
            self.assertEqual(res2.get("action"), "REINSTATED_ORIGINAL")

    def test_f5_partial_fill_expands_400_to_600_replacement_fails_old_400_reinstated_remains_pending_or_emergency(self):
        """
        F5_PARTIAL_FILL_EXPANDS_400_TO_600_REPLACEMENT_FAILS_OLD_400_REINSTATED_REMAINS_PENDING_OR_EMERGENCY
        End-to-end window-close & partial fill protection:
        - Holding expanded from 400 to 600 shares on broker.
        - Window closes (08:05:00 BST).
        - sync_broker_stop_order attempts to place stop for 600 shares, but replacement fails.
        - Old 400-share stop is reinstated.
        - sync_broker_stop_order returns EMERGENCY_PARTIALLY_PROTECTED (success=False, protection_active=False).
        - Engine must NOT transition to PARTIALLY_FILLED_WINDOW_CLOSED.
        - Engine must fail closed to WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        engine = PRVQuantEngine()
        engine.paper_mode = False
        ticker = "EMIMl_EQ"

        # Mock broker returning 600 position and order cancelled at window close
        pos_600 = [{"ticker": ticker, "quantity": 600.0, "averagePrice": 4145.0}]
        live_orders = [{
            "id": "STOP_OLD_400",
            "ticker": ticker,
            "type": "STOP",
            "stopPrice": 4062.10,
            "quantity": -400.0,
            "timeValidity": "DAY",
            "side": "SELL"
        }]

        def _cancel(order_id):
            live_orders[:] = [o for o in live_orders if str(o["id"]) != str(order_id)]
            return {"success": True}

        place_calls = []
        def _place(ticker, quantity, stop_price, time_validity):
            place_calls.append({"price": stop_price, "qty": quantity})
            if len(place_calls) == 1:
                return {"success": False, "error": "Replacement 600 stop rejected"}
            reinstated = {
                "id": "STOP_REINSTATED_400",
                "ticker": ticker,
                "type": "STOP",
                "stopPrice": stop_price,
                "quantity": quantity,
                "timeValidity": time_validity,
                "side": "SELL"
            }
            live_orders.append(reinstated)
            return {"success": True, "data": reinstated}

        # 1. Verify sync_broker_stop_order directly returns EMERGENCY_PARTIALLY_PROTECTED
        with patch.object(broker, "get_open_positions", side_effect=provenance_aware(pos_600)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: live_orders)), \
             patch.object(broker, "cancel_order", side_effect=_cancel), \
             patch.object(broker, "place_stop_order", side_effect=_place):

            sync_res = broker.sync_broker_stop_order(ticker, 600.0, 4062.10)
            self.assertFalse(sync_res.get("success"))
            self.assertFalse(sync_res.get("protection_active"))
            self.assertEqual(sync_res.get("action"), "EMERGENCY_PARTIALLY_PROTECTED")
            self.assertTrue(sync_res.get("underprotected_position_hazard"))

        # 2. Verify engine window-close state machine fails closed to WINDOW_CLOSE_PENDING_RECONCILIATION
        working_decision = {
            "dedup_key": "2026-09-11_CORE_EMIMl_EQ",
            "target_instrument": ticker,
            "broker_order_id": "112233",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "limit_price": 41.45,
            "units": 600
        }
        past_window_dt = datetime(2026, 9, 11, 8, 10, 0, tzinfo=ZoneInfo("Europe/London"))

        with patch.object(db, "get_pending_reconciliation_decision", return_value=working_decision), \
             patch.object(db, "update_core_compounding_decision_status") as mock_db_update, \
             patch.object(broker, "sync_broker_stop_order", return_value=sync_res):

            result_msg = engine.reconcile_unknown_submissions(
                open_positions=pos_600,
                open_orders=[],
                positions_authoritative=True,
                orders_authoritative=True,
                current_time=past_window_dt,
                bypass_execution_window=False
            )

            self.assertTrue(mock_db_update.called)
            call_kwargs = mock_db_update.call_args[1]
            self.assertEqual(
                call_kwargs.get("status"),
                "WINDOW_CLOSE_PENDING_RECONCILIATION",
                "Must NOT transition to PARTIALLY_FILLED_WINDOW_CLOSED when stop is underprotected!"
            )
            self.assertIn("WINDOW_CLOSE_PENDING_RECONCILIATION", result_msg)


if __name__ == "__main__":
    unittest.main()
