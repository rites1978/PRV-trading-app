"""
Test Trading212 Public API Stop and Stop-Limit Order endpoints in Practice/Demo mode
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from src.brokers.trading212 import broker

print("=== TESTING TRADING212 DEMO BROKER STOP ORDERS ===")

# Test 1: Stop Order on HSBA (UK) or small test
# We test with timeValidity: "GTC" or "DAY"
payload_stop = {
    "ticker": "HSBAl_EQ",
    "quantity": -1.0, # selling 1 share or positive quantity?
    "stopPrice": 14.0,
    "timeValidity": "GTC"
}
# Let's test with positive quantity first as standard T212 API uses positive quantity with side determined or sell endpoint
res_stop = broker._request_with_retry("POST", "equity/orders/stop", json={"ticker": "HSBAl_EQ", "quantity": 1.0, "stopPrice": 14.0, "timeValidity": "GTC"})
print(f"POST equity/orders/stop (GTC, qty=1.0): HTTP {res_stop.status_code} -> {res_stop.text}")

res_stop_neg = broker._request_with_retry("POST", "equity/orders/stop", json={"ticker": "HSBAl_EQ", "quantity": -1.0, "stopPrice": 14.0, "timeValidity": "GTC"})
print(f"POST equity/orders/stop (GTC, qty=-1.0): HTTP {res_stop_neg.status_code} -> {res_stop_neg.text}")

# Test 2: Stop Limit Order
res_stop_limit = broker._request_with_retry("POST", "equity/orders/stop_limit", json={"ticker": "HSBAl_EQ", "quantity": 1.0, "stopPrice": 14.0, "limitPrice": 13.90, "timeValidity": "GTC"})
print(f"POST equity/orders/stop_limit (GTC): HTTP {res_stop_limit.status_code} -> {res_stop_limit.text}")

# Test 3: Check open orders endpoint
res_orders = broker._request_with_retry("GET", "equity/orders")
print(f"GET equity/orders: HTTP {res_orders.status_code} -> {res_orders.text}")
