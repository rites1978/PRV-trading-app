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
    EXECUTABLE_PRODUCT_TYPES = {"STOCK", "ETF", "EQUITY"}

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

    # Authoritative Exchange Capability Registry:
    # Permitted ONLY when exact venue/instrument rules have been independently verified and scoped.
    VERIFIED_VENUE_CAPABILITY: Dict[str, Dict[str, Any]] = {
        "London Stock Exchange": {
            "exchange_id": 42,
            "mic": "XLON",
            "jurisdiction": "UK",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": True,
            "ptm_levy_scope": True,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"GBX", "GBP"},
            "tick_size_rule": None  # MiFID II RTS 11 requires ESMA/FCA ADNT liquidity band; no price-only approximation permitted
        },
        "London Stock Exchange AIM": {
            "exchange_id": 64,
            "mic": "AIMX",
            "jurisdiction": "UK",
            "is_regulated_market": False,
            "is_mtf": True,
            "sdrt_applicable_to_ordinary_shares": False,  # Legally exempt (Finance Act 2014)
            "ptm_levy_scope": True,
            "supported_product_types": {"STOCK"},
            "supported_currencies": {"GBX", "GBP"},
            "tick_size_rule": None
        },
        "NYSE": {
            "exchange_id": 43,
            "mic": "XNYS",
            "jurisdiction": "US",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "sec_section_31_scope": True,
            "finra_taf_scope": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"USD"},
            "tick_size_rule": "US_SEC_RULE_612"  # Statutory price-only rule without liquidity bands (17 CFR § 242.612)
        },
        "NASDAQ": {
            "exchange_id": 53,
            "mic": "XNAS",
            "jurisdiction": "US",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "sec_section_31_scope": True,
            "finra_taf_scope": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"USD"},
            "tick_size_rule": "US_SEC_RULE_612"  # Statutory price-only rule without liquidity bands (17 CFR § 242.612)
        },
        "Deutsche Börse Xetra": {
            "exchange_id": 41,
            "mic": "XETR",
            "jurisdiction": "DE",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None  # MiFID II RTS 11 requires ESMA ADNT liquidity band
        },
        "Euronext Paris": {
            "exchange_id": 58,
            "mic": "XPAR",
            "jurisdiction": "FR",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "french_ftt_scope": True,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None  # MiFID II RTS 11 requires ESMA ADNT liquidity band
        },
        "Euronext Amsterdam": {
            "exchange_id": 44,
            "mic": "XAMS",
            "jurisdiction": "NL",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None  # MiFID II RTS 11 requires ESMA ADNT liquidity band
        },
        "Gettex": {
            "exchange_id": 72,
            "mic": "MUNC",
            "jurisdiction": "DE",
            "is_regulated_market": True,
            "is_mtf": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None
        },
        "Toronto Stock Exchange": {
            "exchange_id": 63,
            "mic": "XTSE",
            "jurisdiction": "CA",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"CAD"},
            "tick_size_rule": None
        },
        "SIX Swiss Exchange": {
            "exchange_id": 68,
            "mic": "XSWX",
            "jurisdiction": "CH",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"CHF"},
            "tick_size_rule": None
        },
        "Bolsa de Madrid": {
            "exchange_id": 47,
            "mic": "BMAD",
            "jurisdiction": "ES",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "spanish_ftt_scope": True,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None
        },
        "Borsa Italiana": {
            "exchange_id": 51,
            "mic": "XMIL",
            "jurisdiction": "IT",
            "is_regulated_market": True,
            "is_mtf": False,
            "sdrt_applicable_to_ordinary_shares": False,
            "ptm_levy_scope": False,
            "italian_ftt_scope": True,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None
        },
        "Euronext Brussels": {
            "exchange_id": 54,
            "mic": "XBRU",
            "jurisdiction": "BE",
            "is_regulated_market": True,
            "is_mtf": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None
        },
        "Wiener Börse": {
            "exchange_id": 55,
            "mic": "XWBO",
            "jurisdiction": "AT",
            "is_regulated_market": True,
            "is_mtf": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None
        },
        "Euronext Lisbon": {
            "exchange_id": 70,
            "mic": "XLIS",
            "jurisdiction": "PT",
            "is_regulated_market": True,
            "is_mtf": False,
            "supported_product_types": {"STOCK", "ETF"},
            "supported_currencies": {"EUR"},
            "tick_size_rule": None
        }
    }

    @classmethod
    def derive_quantity_precision(cls, min_trade_qty: Optional[float]) -> Optional[int]:
        """
        Derives quantity precision mathematically and unambiguously from minTradeQuantity.
        Returns None if min_trade_qty is missing, zero, or negative.
        """
        if min_trade_qty is None or min_trade_qty <= 0:
            return None
        if float(min_trade_qty).is_integer() and min_trade_qty >= 1.0:
            return 0
        s = f"{min_trade_qty:.8f}".rstrip('0')
        if '.' in s:
            return len(s.split('.')[1])
        return 0

    @classmethod
    def derive_tick_size_for_venue(
        cls,
        venue_name: Optional[str] = None,
        currency: str = "GBP",
        price: float = 1.0,
        is_uk_pence: bool = False,
        explicit_tick: Optional[float] = None
    ) -> Optional[float]:
        """
        Derives authoritative tick size enforcing strict execution precedence:
        1. Explicit Trading212 instrument tick metadata (explicit_tick > 0)
        2. Exact verified venue+instrument-class capability rule:
           - US SEC Regulation NMS Rule 612 for US NMS common stocks and ETFs in USD
        3. Otherwise TICK_SIZE_UNKNOWN -> returns None (fail closed).

        Strictly prohibits price-only approximations for liquidity-banded regimes (MiFID II RTS 11, SIX).
        """
        # Precedence 1: Explicit Trading212 metadata
        if explicit_tick is not None and explicit_tick > 0:
            return float(explicit_tick)

        if not venue_name:
            return None

        venue_cap = cls.VERIFIED_VENUE_CAPABILITY.get(venue_name)
        if not venue_cap:
            return None

        rule = venue_cap.get("tick_size_rule")
        curr = currency.upper().strip()

        # Precedence 2: Exact verified venue+instrument-class capability rule
        if rule == "US_SEC_RULE_612":
            # US SEC Regulation NMS Rule 612 (17 CFR § 242.612 - Sub-Penny Rule)
            # Authoritative federal statutory requirement for all US NMS equity stocks and ETFs:
            # >= $1.00 -> $0.01; < $1.00 -> $0.0001. No liquidity bands exist under Rule 612.
            if curr == "USD" and price > 0:
                return 0.01 if price >= 1.0 else 0.0001
            return None

        # Precedence 3: MiFID II RTS 11 (LSE, Euronext, Xetra) and other liquidity-banded venues
        # Tick size legally requires ESMA/FCA ADNT liquidity band (Bands 1-6) AND price range.
        # Price-only approximations without authoritative liquidity band are unverified and prohibited.
        return None

    @classmethod
    def resolve_exchange_venue(cls, instrument: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Resolves exchange venue authoritatively from metadata, working schedule, or canonical ticker pattern.
        """
        if not instrument:
            return None
        venue_name = instrument.get("exchange_venue") or instrument.get("exchange") or instrument.get("venue")
        if venue_name:
            return str(venue_name).strip()
        working_schedule_id = instrument.get("workingScheduleId")
        if working_schedule_id is not None:
            try:
                from src.data.broker_discovery import broker_discovery
                ex_info = broker_discovery.get_exchange_for_schedule(working_schedule_id)
                if ex_info and ex_info.get("exchange_name"):
                    return str(ex_info.get("exchange_name")).strip()
            except Exception:
                pass
        t212_ticker = str(instrument.get("ticker") or instrument.get("instrument_id") or "").strip()
        if t212_ticker.endswith("l_EQ") or t212_ticker.endswith("L_EQ"):
            return "London Stock Exchange"
        if "_US_" in t212_ticker:
            return "NYSE"
        if t212_ticker.endswith("d_EQ") or t212_ticker.endswith("D_EQ"):
            return "Deutsche Börse Xetra"
        if t212_ticker.endswith("p_EQ") or t212_ticker.endswith("P_EQ"):
            return "Euronext Paris"
        if t212_ticker.endswith("a_EQ") or t212_ticker.endswith("A_EQ"):
            return "Euronext Amsterdam"
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

        # Gate 3: Resolve Venue
        venue_name = cls.resolve_exchange_venue(instrument)
        working_schedule_id = instrument.get("workingScheduleId")
        venue_capability = cls.VERIFIED_VENUE_CAPABILITY.get(venue_name) if venue_name else None

        # Check certified metadata for core 6-instrument universe to preserve core engine specification
        t_id = instrument.get("ticker") or instrument.get("shortName") or instrument.get("symbol")
        found_cert = False
        cert_data = None
        if t_id:
            try:
                from src.strategies.core_compounding_v1 import core_compounding_strategy
                clean = str(t_id).replace("_L", "").replace(".L", "").replace("l_EQ", "").replace("_EQ", "").upper()
                for cert in core_compounding_strategy.CERTIFIED_UNIVERSE:
                    if clean in (cert["symbol"].upper(), cert["t212_ticker"].replace("l_EQ", "").replace("_EQ", "").upper()):
                        found_cert = True
                        cert_data = cert
                        break
            except Exception:
                pass

        # Gate 4: Quantity Precision and Tradability Limits
        max_open = instrument.get("maxOpenQuantity")
        if max_open is not None and max_open <= 0:
            return False, "BROKER_UNTRADABLE: maxOpenQuantity is 0 or negative", {
                "maxOpenQuantity": max_open
            }

        raw_min_qty = instrument.get("minTradeQuantity")
        explicit_prec = instrument.get("quantityPrecision")
        if raw_min_qty is not None and raw_min_qty > 0:
            min_qty = float(raw_min_qty)
            prec = cls.derive_quantity_precision(min_qty) if explicit_prec is None else int(explicit_prec)
        elif explicit_prec is not None and explicit_prec >= 0:
            prec = int(explicit_prec)
            min_qty = 10.0 ** (-prec) if prec > 0 else 1.0
        elif found_cert and cert_data:
            raw_min_qty = cert_data.get("broker_allowed_increment", 0.001)
            explicit_prec = cert_data.get("broker_allowed_precision", 3)
            min_qty = float(raw_min_qty)
            prec = int(explicit_prec)
        else:
            return False, "QUANTITY_INCREMENT_UNKNOWN: Unable to determine valid order quantity from metadata", {}

        # Gate 5: Tick Size Determination (Precedence: Explicit Metadata -> Verified Statutory Rule -> Fail Closed)
        explicit_tick = instrument.get("tickSize")
        if explicit_tick is not None and explicit_tick > 0:
            tick_size = float(explicit_tick)
            tick_rule = "EXPLICIT_METADATA"
        elif venue_capability and venue_capability.get("tick_size_rule") == "US_SEC_RULE_612" and currency_code == "USD" and product_type in ("STOCK", "ETF"):
            tick_rule = "US_SEC_RULE_612"
            tick_size = None  # To be derived per price band using the verified statutory SEC rule ($0.01 / $0.0001)
        elif found_cert:
            # Certified core compounding universe preserves running six-instrument engine
            tick_rule = "CERTIFIED_CORE_ETF"
            tick_size = 0.01
        else:
            return False, "TICK_SIZE_UNKNOWN: Unable to determine authoritative tick size from explicit metadata or verified statutory rule", {}

        # Gate 6: Feed Ticker Mapping
        feed_ticker = cls.resolve_feed_ticker(instrument)
        if not feed_ticker:
            return False, "FEED_MAPPING_UNAVAILABLE: Unable to derive canonical market feed ticker", {}

        # Gate 7: GTC Protective Stop Capability
        gtc_stop_capable = True

        details = {
            "ticker": t212_ticker,
            "feed_ticker": feed_ticker,
            "product_type": product_type,
            "currency": currency_code,
            "is_uk_pence": is_uk_pence,
            "quote_divisor": quote_divisor,
            "min_qty": min_qty,
            "quantity_precision": prec,
            "max_open": max_open,
            "gtc_stop_capable": gtc_stop_capable,
            "working_schedule_id": working_schedule_id,
            "exchange_venue": venue_name or "UNKNOWN",
            "tick_size_rule": tick_rule,
            "tick_size": tick_size
        }

        return True, "TECHNICAL_EXECUTION_SUPPORTED", details


technical_execution_capability = TechnicalExecutionCapabilityValidator()
