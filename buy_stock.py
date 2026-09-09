"""
Manual one-off Trading212 market-order helper.

SAFETY HISTORY: this module previously executed a LIVE market order at module scope,
so merely importing it placed a real order. Executable behaviour is now confined to
main() behind an explicit __main__ guard, with the central runtime guard retained as
defence-in-depth at the actual write boundary.
"""
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.core.runtime_guard import assert_live_broker_write_allowed

BASE_URL = "https://demo.trading212.com/api/v0/equity/orders/market"


def place_market_order(ticker: str, quantity: float) -> dict:
    """Place a single market order. Refuses unless live broker writes are authorised."""
    assert_live_broker_write_allowed("POST", "equity/orders/market")

    load_dotenv()
    api_key = os.getenv("TRADING212_API_KEY")
    api_secret = os.getenv("TRADING212_API_SECRET")

    response = requests.post(
        BASE_URL,
        auth=(api_key, api_secret),
        json={"ticker": ticker, "quantity": quantity},
        timeout=10,
    )
    if response.status_code in (200, 201):
        return {"success": True, "data": response.json()}
    return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if len(argv) < 2:
        print("usage: python buy_stock.py <TICKER> <QUANTITY>")
        return 2
    ticker, quantity = argv[0], float(argv[1])
    print(f"Placing market order: {quantity} x {ticker}")
    result = place_market_order(ticker, quantity)
    if result.get("success"):
        data = result["data"]
        print(f"Order accepted. id={data.get('id')} status={data.get('status')}")
        return 0
    print(f"Order failed: {result.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
