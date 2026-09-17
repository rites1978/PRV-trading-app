"""
PRV Capital - Hit-and-Run Full Universe Discovery Service
Discovers 100% of instruments exposed by Trading212 and validates technical execution capability.
Enforces strict separation between:
1. BROKER DISCOVERY (every instrument Trading212 metadata returns)
2. TECHNICAL EXECUTION CAPABILITY (supported currencies, precision, order types, stops)
3. STRATEGY QUALIFICATION (hit-and-run momentum & reward/risk qualification)
"""
import logging
from typing import Dict, Any, List, Optional
from src.data.broker_discovery import broker_discovery
from src.data.technical_execution_capability import technical_execution_capability

logger = logging.getLogger("hit_and_run.universe")


class HitAndRunUniverseDiscovery:
    """
    Authoritative discovery engine for the Hit-and-Run trading system.
    Considers the entire universe of instruments exposed by the connected Trading212 account.
    """

    def __init__(self):
        self._executable_universe_cache: Optional[List[Dict[str, Any]]] = None

    def get_universe_telemetry(self) -> Dict[str, Any]:
        """Returns comprehensive telemetry of the entire Trading212 exposed universe."""
        raw_telemetry = broker_discovery.get_discovery_telemetry()

        discovered_count = raw_telemetry.get("BROKER_API_DISCOVERED", 0)
        tradable_count = raw_telemetry.get("BROKER_API_TRADABLE", 0)
        product_families = raw_telemetry.get("DISCOVERED_BY_PRODUCT_TYPE", {})
        tradable_families = raw_telemetry.get("TRADABLE_BY_PRODUCT_TYPE", {})
        unsupported = raw_telemetry.get("UNSUPPORTED_PRODUCT_FAMILY_IF_ANY", {})

        executable = self.get_executable_universe()

        return {
            "DISCOVERED_INSTRUMENT_COUNT": discovered_count,
            "TRADABLE_INSTRUMENT_COUNT": tradable_count,
            "UNTRADABLE_ZERO_QUANTITY_COUNT": raw_telemetry.get("BROKER_API_UNTRADABLE_ZERO_QUANTITY", 0),
            "TRADABILITY_UNKNOWN_COUNT": raw_telemetry.get("BROKER_API_TRADABILITY_UNKNOWN", 0),
            "TECHNICAL_SUPPORTED_COUNT": len(executable),
            "EXTENDED_HOURS_TRUE": raw_telemetry.get("EXTENDED_HOURS_TRUE", 0),
            "EXTENDED_HOURS_FALSE": raw_telemetry.get("EXTENDED_HOURS_FALSE", 0),
            "EXTENDED_HOURS_NULL": raw_telemetry.get("EXTENDED_HOURS_NULL", 0),
            "EXTENDED_HOURS_MISSING": raw_telemetry.get("EXTENDED_HOURS_MISSING", 0),
            "EXTENDED_HOURS_UNKNOWN": raw_telemetry.get("EXTENDED_HOURS_UNKNOWN", 0),
            "PRODUCT_FAMILIES": product_families,
            "TRADABLE_PRODUCT_FAMILIES": tradable_families,
            "UNSUPPORTED_PRODUCT_FAMILIES": unsupported,
            "TOTAL_EXCHANGES": raw_telemetry.get("TOTAL_EXCHANGES", 0)
        }

    def get_executable_universe(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Filters the full broker discovery down to instruments that pass Technical Execution Capability.
        Does NOT apply any investment strategy filters (no ETF-only, no UK-only, no market-cap rules).
        """
        if self._executable_universe_cache is not None and not force_refresh:
            return list(self._executable_universe_cache)

        tradable_instruments = broker_discovery.get_tradable_instruments()
        executable_list = []

        for inst in tradable_instruments:
            is_supported, reason, details = technical_execution_capability.validate(inst)
            if is_supported:
                ext_eval = broker_discovery.evaluate_extended_hours(inst)
                executable_list.append({
                    "instrument_id": details["ticker"],
                    "symbol": inst.get("shortName") or inst.get("ticker"),
                    "short_name": inst.get("shortName", ""),
                    "isin": inst.get("isin", ""),
                    "feed_ticker": details["feed_ticker"],
                    "product_type": details["product_type"],
                    "currency": details["currency"],
                    "is_uk_pence": details["is_uk_pence"],
                    "quote_divisor": details["quote_divisor"],
                    "min_trade_quantity": details["min_qty"],
                    "max_open_quantity": details["max_open"],
                    "working_schedule_id": details.get("working_schedule_id"),
                    "extended_hours": ext_eval["extended_hours"],
                    "extended_hours_status": ext_eval["extended_hours_status"]
                })

        self._executable_universe_cache = executable_list
        logger.info(f"HitAndRunUniverseDiscovery: {len(executable_list)} instruments verified as technically executable.")
        return list(self._executable_universe_cache)


hit_and_run_universe = HitAndRunUniverseDiscovery()
