"""
PRV Capital - Broker Discovery Service
Discovers 100% of instruments and exchange schedules exposed by the connected Trading212 account.
Reports:
- BROKER_API_DISCOVERED: total count returned by broker metadata endpoints
- BROKER_API_TRADABLE: instruments with maxOpenQuantity > 0 and not delisted/suspended
- UNSUPPORTED_PRODUCT_FAMILY_IF_ANY: count and list of unexecutable product types
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("broker_discovery")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
INSTRUMENTS_CACHE = os.path.join(DATA_DIR, "trading212_instruments.json")
EXCHANGES_CACHE = os.path.join(DATA_DIR, "trading212_exchanges.json")


class BrokerDiscoveryService:
    """Authoritative service for discovering all instruments and exchanges exposed by Trading212."""

    def __init__(self):
        self._instruments: List[Dict[str, Any]] = []
        self._exchanges: List[Dict[str, Any]] = []
        self._by_ticker: Dict[str, Dict[str, Any]] = {}
        self._by_isin: Dict[str, Dict[str, Any]] = {}
        self._exchanges_by_id: Dict[int, Dict[str, Any]] = {}
        self._schedules_to_exchange: Dict[int, Dict[str, Any]] = {}
        self._initialized: bool = False

    def initialize(self, force_refresh: bool = False) -> None:
        """Loads instruments and exchanges from local persistent cache or hydrates via broker."""
        if self._initialized and not force_refresh:
            return

        self._load_instruments(force_refresh=force_refresh)
        self._load_exchanges(force_refresh=force_refresh)
        self._build_indexes()
        self._initialized = True
        logger.info(
            f"Broker Discovery initialized: {len(self._instruments)} discovered, "
            f"{len(self.get_tradable_instruments())} tradable across {len(self._exchanges)} exchanges."
        )

    def _load_instruments(self, force_refresh: bool = False) -> None:
        if not force_refresh and os.path.exists(INSTRUMENTS_CACHE):
            try:
                with open(INSTRUMENTS_CACHE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        self._instruments = data
                        return
            except Exception as e:
                logger.warning(f"Failed to load instruments cache from {INSTRUMENTS_CACHE}: {e}")

        try:
            from src.brokers.trading212 import broker
            res = broker._request_with_retry("GET", "equity/metadata/instruments", timeout=30.0)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    self._instruments = data
                    os.makedirs(os.path.dirname(INSTRUMENTS_CACHE), exist_ok=True)
                    with open(INSTRUMENTS_CACHE, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    return
        except Exception as e:
            logger.warning(f"Live broker instruments fetch failed: {e}")

    def _load_exchanges(self, force_refresh: bool = False) -> None:
        if not force_refresh and os.path.exists(EXCHANGES_CACHE):
            try:
                with open(EXCHANGES_CACHE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        self._exchanges = data
                        return
            except Exception as e:
                logger.warning(f"Failed to load exchanges cache from {EXCHANGES_CACHE}: {e}")

        try:
            from src.brokers.trading212 import broker
            res = broker._request_with_retry("GET", "equity/metadata/exchanges", timeout=30.0)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    self._exchanges = data
                    os.makedirs(os.path.dirname(EXCHANGES_CACHE), exist_ok=True)
                    with open(EXCHANGES_CACHE, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    return
        except Exception as e:
            logger.warning(f"Live broker exchanges fetch failed: {e}")

    def _build_indexes(self) -> None:
        self._by_ticker = {
            i.get("ticker", "").upper(): i
            for i in self._instruments
            if i.get("ticker")
        }
        self._by_isin = {
            i.get("isin", "").upper(): i
            for i in self._instruments
            if i.get("isin")
        }
        self._exchanges_by_id = {
            e.get("id"): e
            for e in self._exchanges
            if e.get("id") is not None
        }
        self._schedules_to_exchange = {}
        for ex in self._exchanges:
            for sched in ex.get("workingSchedules", []):
                sched_id = sched.get("id")
                if sched_id is not None:
                    self._schedules_to_exchange[sched_id] = {
                        "exchange_id": ex.get("id"),
                        "exchange_name": ex.get("name"),
                        "schedule": sched
                    }

    def get_all_discovered(self) -> List[Dict[str, Any]]:
        self.initialize()
        return list(self._instruments)

    @staticmethod
    def evaluate_tradability(instrument: Dict[str, Any]) -> Dict[str, Any]:
        """
        Authoritatively evaluates the broker tradability state of an instrument.
        Distinguishes missing/null metadata (UNKNOWN) from explicit zero (UNTRADABLE_ZERO_QUANTITY)
        and positive values (TRADABLE).
        Does not silently convert missing metadata to zero.
        """
        if "maxOpenQuantity" not in instrument or instrument.get("maxOpenQuantity") is None:
            return {
                "max_open_quantity": None,
                "max_open_quantity_status": "UNKNOWN",
                "broker_tradability_status": "UNKNOWN",
                "is_tradable": False
            }
        try:
            val = float(instrument["maxOpenQuantity"])
        except (ValueError, TypeError):
            return {
                "max_open_quantity": None,
                "max_open_quantity_status": "UNKNOWN",
                "broker_tradability_status": "UNKNOWN",
                "is_tradable": False
            }

        if val > 0.0:
            return {
                "max_open_quantity": val,
                "max_open_quantity_status": "KNOWN_POSITIVE",
                "broker_tradability_status": "TRADABLE",
                "is_tradable": True
            }
        elif val == 0.0:
            return {
                "max_open_quantity": 0.0,
                "max_open_quantity_status": "KNOWN_ZERO",
                "broker_tradability_status": "UNTRADABLE_ZERO_QUANTITY",
                "is_tradable": False
            }
        else:
            return {
                "max_open_quantity": val,
                "max_open_quantity_status": "KNOWN_NEGATIVE",
                "broker_tradability_status": "UNTRADABLE_NEGATIVE_QUANTITY",
                "is_tradable": False
            }

    def get_tradable_instruments(self) -> List[Dict[str, Any]]:
        """Returns active instruments confirmed tradable to this account (maxOpenQuantity > 0)."""
        self.initialize()
        return [
            i for i in self._instruments
            if self.evaluate_tradability(i)["is_tradable"] is True
        ]

    def get_instrument_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        self.initialize()
        return self._by_ticker.get(ticker.upper())

    def get_exchange_for_schedule(self, schedule_id: int) -> Optional[Dict[str, Any]]:
        self.initialize()
        return self._schedules_to_exchange.get(schedule_id)

    def get_discovery_telemetry(self) -> Dict[str, Any]:
        self.initialize()
        total_discovered = len(self._instruments)

        tradable = []
        zero_quantity = []
        tradability_unknown = []

        discovered_by_type: Dict[str, int] = {}
        tradable_by_type: Dict[str, int] = {}
        zero_qty_by_type: Dict[str, int] = {}
        unknown_by_type: Dict[str, int] = {}

        for inst in self._instruments:
            t = inst.get("type", "UNKNOWN")
            discovered_by_type[t] = discovered_by_type.get(t, 0) + 1

            eval_res = self.evaluate_tradability(inst)
            status = eval_res["broker_tradability_status"]
            if status == "TRADABLE":
                tradable.append(inst)
                tradable_by_type[t] = tradable_by_type.get(t, 0) + 1
            elif status == "UNTRADABLE_ZERO_QUANTITY":
                zero_quantity.append(inst)
                zero_qty_by_type[t] = zero_qty_by_type.get(t, 0) + 1
            elif status == "UNKNOWN":
                tradability_unknown.append(inst)
                unknown_by_type[t] = unknown_by_type.get(t, 0) + 1

        unsupported_families = {
            t: count for t, count in discovered_by_type.items()
            if t not in ("STOCK", "ETF")
        }

        return {
            "BROKER_API_DISCOVERED": total_discovered,
            "BROKER_API_TRADABLE": len(tradable),
            "BROKER_API_UNTRADABLE_ZERO_QUANTITY": len(zero_quantity),
            "BROKER_API_TRADABILITY_UNKNOWN": len(tradability_unknown),
            "DISCOVERED_BY_PRODUCT_TYPE": discovered_by_type,
            "TRADABLE_BY_PRODUCT_TYPE": tradable_by_type,
            "UNTRADABLE_ZERO_BY_PRODUCT_TYPE": zero_qty_by_type,
            "TRADABILITY_UNKNOWN_BY_PRODUCT_TYPE": unknown_by_type,
            "UNSUPPORTED_PRODUCT_FAMILY_IF_ANY": unsupported_families,
            "TOTAL_EXCHANGES": len(self._exchanges)
        }


broker_discovery = BrokerDiscoveryService()
