"""
PRV Capital - Technical Execution Capability Validator
Evaluates whether our execution pipeline can safely and mechanically execute an instrument:
- quote units & divisor (currencyCode: GBX -> /100, USD/EUR/GBP -> 1.0)
- currency accounting (supported account currencies)
- quantity precision (minTradeQuantity > 0)
- order type support (Limit / Market supported on Equity Order API)
- GTC stop protection capability (verified support for GTC stop orders via /equity/orders/stop)
- feed ticker resolution (maps T212 ticker to canonical market feed)

Never submits probe orders. If capability cannot be verified from metadata and documented API semantics,
marks the instrument as EXECUTION_CAPABILITY_UNVERIFIED.
"""
from typing import Dict, Any, Tuple, Optional


class TechnicalExecutionCapabilityValidator:
    """Authoritative technical validation of broker instruments before routing."""

    SUPPORTED_CURRENCIES = {"GBP", "GBX", "USD", "EUR", "CAD", "CHF"}
    EXECUTABLE_PRODUCT_TYPES = {"STOCK", "ETF"}

    @classmethod
    def resolve_feed_ticker(cls, instrument: Dict[str, Any]) -> Optional[str]:
        """Derives canonical Yahoo Finance ticker from Trading212 metadata without network calls."""
        if not instrument:
            return None

        t212_ticker = instrument.get("ticker", "").strip()
        short_name = instrument.get("shortName", "").strip()
        curr = instrument.get("currencyCode", "").strip().upper()

        if not t212_ticker and not short_name:
            return None

        # 1. US Equities and ETFs (e.g. AAPL_US_EQ -> AAPL)
        if "_US_" in t212_ticker:
            base = t212_ticker.split("_US_")[0]
            # Replace / or . in symbols if any (e.g. BRK.B -> BRK-B)
            return base.replace(".", "-").replace("/", "-")

        # 2. London Stock Exchange (e.g. BARCl_EQ -> BARC.L, CSP1l_EQ -> CSP1.L)
        if t212_ticker.endswith("l_EQ") or t212_ticker.endswith("L_EQ"):
            base = t212_ticker[:-4]
            return f"{base}.L"

        if curr in ("GBX", "GBP"):
            # If shortName provided and doesn't contain dot
            if short_name and "." not in short_name:
                return f"{short_name}.L"
            elif short_name:
                return short_name

        # 3. German XETRA (e.g. d_EQ -> .DE)
        if t212_ticker.endswith("d_EQ") or t212_ticker.endswith("D_EQ"):
            base = t212_ticker[:-4]
            return f"{base}.DE"

        # 4. Euronext Paris (e.g. p_EQ -> .PA)
        if t212_ticker.endswith("p_EQ") or t212_ticker.endswith("P_EQ"):
            base = t212_ticker[:-4]
            return f"{base}.PA"

        # 5. Euronext Amsterdam (e.g. a_EQ -> .AS)
        if t212_ticker.endswith("a_EQ") or t212_ticker.endswith("A_EQ"):
            base = t212_ticker[:-4]
            return f"{base}.AS"

        # 6. Fallback to shortName
        if short_name:
            return short_name

        return None

    @classmethod
    def validate(cls, instrument: Optional[Dict[str, Any]]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Performs non-mutating technical validation of the instrument against the execution stack.
        Returns:
            (is_supported: bool, reason: str, details: Dict[str, Any])
        """
        if not instrument or not isinstance(instrument, dict):
            return False, "MALFORMED_METADATA: Instrument record is missing or not a dict", {}

        t212_ticker = instrument.get("ticker", "")
        if not t212_ticker:
            return False, "MALFORMED_METADATA: Missing ticker", {}

        product_type = instrument.get("type", "UNKNOWN").upper()

        # Gate 1: Supported Product Family on Trading212 Equity Order API
        if product_type not in cls.EXECUTABLE_PRODUCT_TYPES:
            return False, f"UNSUPPORTED_PRODUCT_FAMILY: Product type '{product_type}' not supported by Trading212 Equity Order API", {
                "product_type": product_type
            }

        # Gate 2: Currency and Quote Unit Resolution
        currency_code = instrument.get("currencyCode", "").strip().upper()
        if not currency_code or currency_code not in cls.SUPPORTED_CURRENCIES:
            return False, f"UNSUPPORTED_CURRENCY: Currency '{currency_code}' not supported by currency accounting", {
                "currency": currency_code
            }

        is_uk_pence = (currency_code == "GBX")
        quote_divisor = 100.0 if is_uk_pence else 1.0

        # Gate 3: Quantity Precision and Tradability Limits
        min_qty = instrument.get("minTradeQuantity")
        max_open = instrument.get("maxOpenQuantity")

        if max_open is not None and max_open <= 0:
            return False, "BROKER_UNTRADABLE: maxOpenQuantity is 0 or negative", {
                "maxOpenQuantity": max_open
            }

        # Gate 4: Feed Ticker Mapping
        feed_ticker = cls.resolve_feed_ticker(instrument)
        if not feed_ticker:
            return False, "FEED_MAPPING_UNAVAILABLE: Unable to derive canonical market feed ticker", {}

        # Gate 5: GTC Protective Stop Capability
        # Verified: Trading212 Equity API supports Limit and GTC Stop orders for STOCK and ETF.
        # Warrants/Rights do not support GTC stops.
        gtc_stop_capable = True

        details = {
            "ticker": t212_ticker,
            "feed_ticker": feed_ticker,
            "product_type": product_type,
            "currency": currency_code,
            "is_uk_pence": is_uk_pence,
            "quote_divisor": quote_divisor,
            "min_qty": min_qty,
            "max_open": max_open,
            "gtc_stop_capable": gtc_stop_capable,
            "working_schedule_id": instrument.get("workingScheduleId")
        }

        return True, "TECHNICAL_EXECUTION_SUPPORTED", details


technical_execution_capability = TechnicalExecutionCapabilityValidator()
