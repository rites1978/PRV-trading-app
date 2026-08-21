import time
import requests
from typing import Dict, Any, List, Optional
from src.config.settings import settings

class Trading212Broker:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, env: Optional[str] = None):
        self.api_key = api_key or settings.TRADING212_API_KEY
        self.api_secret = api_secret or settings.TRADING212_API_SECRET
        self.env = env or settings.TRADING_ENV
        
        if self.env == "live":
            self.base_url = "https://live.trading212.com/api/v0"
        else:
            self.base_url = "https://demo.trading212.com/api/v0"
            
        self.last_request_time = 0.0
        self.min_request_interval = 0.15  # Rate limit: max ~6-7 requests per second

    @property
    def auth(self):
        return (self.api_key, self.api_secret)

    def _rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()

    def get_account_summary(self) -> Dict[str, Any]:
        """Fetch live account cash and portfolio value."""
        self._rate_limit()
        try:
            url = f"{self.base_url}/equity/account/summary"
            response = requests.get(url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "available_cash": float(data.get("cash", {}).get("availableToTrade", 0.0)),
                    "total_value": float(data.get("totalValue", 0.0)),
                    "free_cash": float(data.get("cash", {}).get("free", 0.0)),
                    "invested": float(data.get("totalValue", 0.0)) - float(data.get("cash", {}).get("availableToTrade", 0.0)),
                    "currency": data.get("currency", "GBP"),
                    "raw": data
                }
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Fetch all active positions."""
        self._rate_limit()
        try:
            url = f"{self.base_url}/equity/portfolio"
            response = requests.get(url, auth=self.auth, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception:
            return []

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get position details for a specific instrument."""
        self._rate_limit()
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
        Execute market order.
        quantity > 0: BUY
        quantity < 0: SELL
        """
        self._rate_limit()
        try:
            url = f"{self.base_url}/equity/orders/market"
            payload = {"ticker": ticker, "quantity": quantity}
            response = requests.post(url, auth=self.auth, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return {"success": True, "data": response.json()}
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def place_limit_order(self, ticker: str, quantity: float, limit_price: float, time_validity: str = "DAY") -> Dict[str, Any]:
        """Execute limit order."""
        self._rate_limit()
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

    def get_instruments(self) -> List[Dict[str, Any]]:
        """Download complete instrument metadata."""
        self._rate_limit()
        try:
            url = f"{self.base_url}/equity/metadata/instruments"
            response = requests.get(url, auth=self.auth, timeout=15)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception:
            return []

broker = Trading212Broker()
