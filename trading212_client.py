import os
import requests
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional

load_dotenv()

class Trading212Client:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, env: Optional[str] = None):
        self.api_key = api_key or os.getenv("TRADING212_API_KEY")
        self.api_secret = api_secret or os.getenv("TRADING212_API_SECRET")
        self.env = (env or os.getenv("TRADING_ENV", "demo")).lower()
        
        if self.env == "live":
            self.base_url = "https://live.trading212.com/api/v0"
        else:
            self.base_url = "https://demo.trading212.com/api/v0"

    @property
    def auth(self):
        return (self.api_key, self.api_secret)

    def get_account_summary(self) -> Dict[str, Any]:
        """Fetch account cash and total portfolio valuation."""
        try:
            url = f"{self.base_url}/equity/account/summary"
            response = requests.get(url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "available_cash": float(data.get("cash", {}).get("availableToTrade", 0.0)),
                    "total_value": float(data.get("totalValue", 0.0)),
                    "currency": data.get("currency", "GBP"),
                    "raw": data
                }
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Fetch all currently open equity positions."""
        try:
            url = f"{self.base_url}/equity/portfolio"
            response = requests.get(url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception:
            return []

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get open position details for a specific ticker."""
        try:
            url = f"{self.base_url}/equity/portfolio/{ticker}"
            response = requests.get(url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    def place_market_order(self, ticker: str, quantity: float) -> Dict[str, Any]:
        """
        Place a market order on Trading 212.
        quantity > 0: BUY
        quantity < 0: SELL
        """
        try:
            url = f"{self.base_url}/equity/orders/market"
            payload = {
                "ticker": ticker,
                "quantity": quantity
            }
            response = requests.post(url, auth=self.auth, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def place_limit_order(self, ticker: str, quantity: float, limit_price: float, time_validity: str = "DAY") -> Dict[str, Any]:
        """Place a limit order."""
        try:
            url = f"{self.base_url}/equity/orders/limit"
            payload = {
                "ticker": ticker,
                "quantity": quantity,
                "limitPrice": limit_price,
                "timeValidity": time_validity
            }
            response = requests.post(url, auth=self.auth, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an existing pending order."""
        try:
            url = f"{self.base_url}/equity/orders/{order_id}"
            response = requests.delete(url, auth=self.auth, timeout=10)
            if response.status_code in [200, 204]:
                return {"success": True}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_order_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch historical orders."""
        try:
            url = f"{self.base_url}/equity/history/orders?limit={limit}"
            response = requests.get(url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("items", data) if isinstance(data, dict) else data
            return []
        except Exception:
            return []

    def get_instruments(self) -> List[Dict[str, Any]]:
        """Download list of available instruments."""
        try:
            url = f"{self.base_url}/equity/metadata/instruments"
            response = requests.get(url, auth=self.auth, timeout=15)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception:
            return []
