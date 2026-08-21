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
        self.min_request_interval = 0.35  # Conservative rate limit

    @property
    def auth(self):
        return (self.api_key, self.api_secret)

    def _rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()

    def _request_with_retry(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        max_retries = 3
        backoff = 1.5

        for attempt in range(max_retries):
            self._rate_limit()
            try:
                if method.upper() == "GET":
                    res = requests.get(url, auth=self.auth, timeout=10, **kwargs)
                elif method.upper() == "POST":
                    res = requests.post(url, auth=self.auth, timeout=10, **kwargs)
                elif method.upper() == "DELETE":
                    res = requests.delete(url, auth=self.auth, timeout=10, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method {method}")

                if res.status_code == 429:
                    time.sleep(backoff * (attempt + 1))
                    continue
                return res
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(backoff)
        return res

    def get_account_summary(self) -> Dict[str, Any]:
        """Fetch live account cash and portfolio value with retry protection."""
        try:
            res = self._request_with_retry("GET", "equity/account/summary")
            if res.status_code == 200:
                data = res.json()
                return {
                    "success": True,
                    "available_cash": float(data.get("cash", {}).get("availableToTrade", 0.0)),
                    "total_value": float(data.get("totalValue", 0.0)),
                    "free_cash": float(data.get("cash", {}).get("free", 0.0)),
                    "invested": float(data.get("totalValue", 0.0)) - float(data.get("cash", {}).get("availableToTrade", 0.0)),
                    "currency": data.get("currency", "GBP"),
                    "raw": data
                }
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Fetch all active positions with retry protection."""
        try:
            res = self._request_with_retry("GET", "equity/portfolio")
            if res.status_code == 200:
                return res.json()
            return []
        except Exception:
            return []

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get position details for a specific instrument."""
        try:
            res = self._request_with_retry("GET", f"equity/portfolio/{ticker}")
            if res.status_code == 200:
                return res.json()
            return None
        except Exception:
            return None

    def place_market_order(self, ticker: str, quantity: float) -> Dict[str, Any]:
        """Execute market order."""
        try:
            payload = {"ticker": ticker, "quantity": quantity}
            res = self._request_with_retry("POST", "equity/orders/market", json=payload)
            if res.status_code in [200, 201]:
                return {"success": True, "data": res.json()}
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_instruments(self) -> List[Dict[str, Any]]:
        """Download complete instrument metadata."""
        try:
            res = self._request_with_retry("GET", "equity/metadata/instruments")
            if res.status_code == 200:
                return res.json()
            return []
        except Exception:
            return []

broker = Trading212Broker()
