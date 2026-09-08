"""
🏛️ PRV CAPITAL | TRADING212 INSTRUMENT DIRECTORY HYDRATION
Fetches full instrument directory from Trading212 Practice API and caches to data/trading212_instruments.json.
Provides validated ticker mappings and fail-closed validation for universe symbols.
"""
import os
import json
import time
from typing import Dict, Any, List, Optional
from src.brokers.trading212 import broker

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trading212_instruments.json")


def hydrate_instrument_directory(force: bool = False) -> List[Dict[str, Any]]:
    """Fetches all instruments from Trading212 metadata API and saves to cache."""
    if not force and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 1000:
                    print(f"Loaded {len(data)} instruments from cache: {CACHE_PATH}")
                    return data
        except Exception:
            pass

    print("Fetching instruments from Trading212 API...")
    res = broker._request_with_retry("GET", "equity/metadata/instruments", timeout=30.0)
    if res.status_code == 200:
        data = res.json()
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(data, f)
        print(f"Successfully cached {len(data)} instruments to {CACHE_PATH}")
        return data
    else:
        print(f"Failed to fetch instruments: HTTP {res.status_code} {res.text}")
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r") as f:
                return json.load(f)
        return []


class Trading212InstrumentRegistry:
    """Authoritative instrument registry providing fast lookup and fail-closed validation."""
    def __init__(self, instruments: Optional[List[Dict[str, Any]]] = None):
        self._instruments = instruments or []
        if not self._instruments:
            self.load()
        self._by_ticker: Dict[str, Dict[str, Any]] = {i["ticker"].upper(): i for i in self._instruments if "ticker" in i}
        self._by_isin: Dict[str, Dict[str, Any]] = {i["isin"].upper(): i for i in self._instruments if "isin" in i}

    def load(self):
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r") as f:
                    self._instruments = json.load(f)
            except Exception:
                self._instruments = []
        else:
            self._instruments = hydrate_instrument_directory()
        self._by_ticker = {i["ticker"].upper(): i for i in self._instruments if "ticker" in i}
        self._by_isin = {i["isin"].upper(): i for i in self._instruments if "isin" in i}

    def is_valid_ticker(self, ticker: str) -> bool:
        """Fail-closed validation: returns True only if broker natively supports the ticker."""
        return ticker.upper() in self._by_ticker

    def get_instrument(self, ticker: str) -> Optional[Dict[str, Any]]:
        return self._by_ticker.get(ticker.upper())

    def find_candidates(self, query: str) -> List[Dict[str, Any]]:
        q = query.upper()
        results = []
        for i in self._instruments:
            tick = i.get("ticker", "").upper()
            name = i.get("name", "").upper()
            short = i.get("shortName", "").upper()
            if q in tick or q in name or q in short:
                results.append(i)
        return results


instrument_registry = Trading212InstrumentRegistry()


if __name__ == "__main__":
    data = hydrate_instrument_directory(force=True)
    reg = Trading212InstrumentRegistry(data)
    print(f"Registry ready with {len(reg._by_ticker)} tickers.")
    
    # Check LSEG and NWG
    print("\nLSEG search:")
    for r in reg.find_candidates("LSEG")[:5]:
        print(f"  {r.get('ticker')} | {r.get('name')} | {r.get('currencyCode')}")
    for r in reg.find_candidates("London Stock Exchange")[:5]:
        print(f"  {r.get('ticker')} | {r.get('name')} | {r.get('currencyCode')}")

    print("\nNWG search:")
    for r in reg.find_candidates("NWG")[:5]:
        print(f"  {r.get('ticker')} | {r.get('name')} | {r.get('currencyCode')}")
    for r in reg.find_candidates("NatWest")[:5]:
        print(f"  {r.get('ticker')} | {r.get('name')} | {r.get('currencyCode')}")
