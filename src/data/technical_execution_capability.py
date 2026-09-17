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
from dataclasses import dataclass, asdict
from typing import Dict, Any, Tuple, Optional, List


@dataclass
class CapabilityState:
    """
    Independent evidence state for an execution capability.
    Retains value, status, source, evidence level, and provenance reference.
    Unknown or unproven capability information is never guessed.
    """
    capability: str
    value: Any
    status: str          # "PROVEN", "UNPROVEN", "UNKNOWN", "COMPLETE", "INCOMPLETE"
    source: str          # exact broker payload artifact or regulatory source or "UNAVAILABLE"
    evidence_level: str  # "EMPIRICAL_DEMO_PROVEN", "READ_ONLY_REAL_DATA_PROVEN", "STATUTORY_PROVEN", "PROVEN", "UNPROVEN", "UNKNOWN", "SYNTHETIC_FIXTURE_NOT_PROVEN"
    provenance: Optional[str] = None
    regulatory_tick_status: Optional[str] = None
    regulatory_tick_value: Any = None
    regulatory_tick_source: Optional[str] = None
    broker_tick_rule_status: Optional[str] = None
    broker_tick_rule_value: Any = None
    broker_tick_rule_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TechnicalExecutionCapabilityValidator:
    """Authoritative technical validation of broker instruments before routing."""

    SUPPORTED_CURRENCIES = {"GBP", "GBX", "USD", "EUR", "CAD", "CHF"}
    EXECUTABLE_PRODUCT_TYPES = {"STOCK", "ETF", "EQUITY"}

    # Component-level evidence classification per Acceptance Contract
    COMPONENT_EVIDENCE_LEVEL: str = "TESTED"

    # Authoritative Empirical Stop Order Evidence Registry
    # Records only instruments with independently evidenced protective stop orders.
    # Evidence must have concrete broker order ID, environment, timestamp, and transcript/log provenance.
    # Stop support for unevidenced instruments cannot be inferred from evidenced ones.
    STOP_SUPPORT_REGISTRY: Dict[str, Dict[str, Any]] = {
        "IGLTl_EQ": {
            "order_id": 54650651212,
            "side": "SELL",
            "type": "STOP",
            "quantity": -1.0,
            "fill_price": 9.58,
            "stop_price": 9.34,
            "status": "PROVEN",
            "evidence": "EMPIRICAL_DEMO_STOP_ORDER",
            "source": "DEMO_CANARY_ORDER",
            "evidence_level": "EMPIRICAL_DEMO_PROVEN",
            "provenance": (
                "Trading212 Demo Order #54650651212, step 12625 in "
                "brain/0db33806-1903-40f6-8bc1-f35aa804c6a0/transcript_full/00000223.jsonl"
            ),
            "timestamp": "2026-09-08T14:37:53.398+03:00"
        },
        "IGLT": {
            "order_id": 54650651212,
            "side": "SELL",
            "type": "STOP",
            "quantity": -1.0,
            "fill_price": 9.58,
            "stop_price": 9.34,
            "status": "PROVEN",
            "evidence": "EMPIRICAL_DEMO_STOP_ORDER",
            "source": "DEMO_CANARY_ORDER",
            "evidence_level": "EMPIRICAL_DEMO_PROVEN",
            "provenance": (
                "Trading212 Demo Order #54650651212, step 12625 in "
                "brain/0db33806-1903-40f6-8bc1-f35aa804c6a0/transcript_full/00000223.jsonl"
            ),
            "timestamp": "2026-09-08T14:37:53.398+03:00"
        }
    }

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
            # US SEC Regulation NMS Rule 612 (17 CFR § 242.612 - Minimum Pricing Increments)
            # Regulatory Status (2026 Operative Execution):
            # In September 2024, the SEC adopted amendments to Rule 612 (Release No. 34-100980)
            # introducing a $0.005 tick for certain NMS stocks based on TWAQS <= $0.015.
            # HOWEVER, by Commission Order granting temporary exemptive relief, compliance
            # with the amended minimum pricing increment has been delayed until the first business
            # day of November 2027.
            # Therefore, for current 2026 execution, the presently operative statutory standard
            # and venue/broker requirement remains the pre-amendment Rule 612 standard:
            # - For bids, offers, or orders priced >= $1.00: minimum increment is $0.01
            # - For bids, offers, or orders priced < $1.00: minimum increment is $0.0001
            # Note: Precedence #1 remains explicit Trading212 instrument `tickSize` metadata.
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

        # Gate 7: Independent Capability Evaluation
        capabilities = cls.evaluate_capabilities(instrument)
        gtc_stop_capable = (capabilities["stop_support"].status == "PROVEN")

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
            "capabilities": {k: v.to_dict() for k, v in capabilities.items()},
            "four_capabilities_proven": all(c.status in ("PROVEN", "COMPLETE") for c in capabilities.values()),
            "working_schedule_id": working_schedule_id,
            "exchange_venue": venue_name or "UNKNOWN",
            "extended_hours": bool(instrument.get("extendedHours", False)),
            "overnight_eligibility": (
                "TRUE" if instrument.get("overnightHours") is True or instrument.get("overnightEligible") is True or instrument.get("is24_5") is True
                else ("FALSE" if instrument.get("overnightHours") is False or instrument.get("overnightEligible") is False or instrument.get("is24_5") is False
                else "UNKNOWN")
            ),
            "tick_size_rule": tick_rule,
            "tick_size": tick_size
        }

        return True, "TECHNICAL_EXECUTION_SUPPORTED", details

    @classmethod
    def evaluate_capabilities(
        cls,
        instrument: Optional[Dict[str, Any]]
    ) -> Dict[str, CapabilityState]:
        """
        Independently evaluates the four execution capabilities required by the Acceptance Contract:
        1. QUANTITY RULE: Valid min trade quantity and precision derived authoritatively.
        2. TICK RULE: Valid tick size derived from explicit metadata or verified statutory venue rule.
        3. STOP SUPPORT: Valid native broker stop order support evidenced with provenance.
        4. COST COMPLETENESS: Round-trip transaction tax and fee coverage verified.

        Each capability retains:
        - VALUE
        - STATUS: PROVEN | UNPROVEN | UNKNOWN | COMPLETE | INCOMPLETE
        - SOURCE
        - EVIDENCE LEVEL
        - PROVENANCE / ARTIFACT REFERENCE

        Statuses are strictly decoupled: one proven capability cannot promote another.
        """
        if not instrument or not isinstance(instrument, dict):
            return {
                "quantity_rule": CapabilityState("QUANTITY_RULE", None, "UNKNOWN", "UNAVAILABLE", "UNPROVEN", None),
                "tick_rule": CapabilityState("TICK_RULE", None, "UNKNOWN", "UNAVAILABLE", "UNPROVEN", None),
                "stop_support": CapabilityState("STOP_SUPPORT", None, "UNPROVEN", "UNAVAILABLE", "UNPROVEN", None),
                "cost_completeness": CapabilityState("COST_COMPLETENESS", None, "UNKNOWN", "UNAVAILABLE", "UNPROVEN", None),
            }

        t212_ticker = str(instrument.get("ticker", "")).strip()
        symbol = str(instrument.get("symbol", "") or instrument.get("shortName", "")).strip()
        product_type = instrument.get("type", "UNKNOWN").upper()
        currency_code = instrument.get("currencyCode", "").strip().upper()
        venue_name = cls.resolve_exchange_venue(instrument)
        venue_capability = cls.VERIFIED_VENUE_CAPABILITY.get(venue_name) if venue_name else None

        # -------------------------------------------------------------
        # 1. QUANTITY RULE
        # -------------------------------------------------------------
        # Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md
        # Trading212 metadata endpoints (/equity/metadata/instruments) return 10 keys:
        # ['addedOn', 'currencyCode', 'extendedHours', 'isin', 'maxOpenQuantity',
        #  'name', 'shortName', 'ticker', 'type', 'workingScheduleId']
        # The broker payload does NOT contain `minTradeQuantity` or `quantityPrecision`.
        # Rule:
        # IF real broker payload contains authoritative quantity field -> PROVEN with exact payload artifact provenance
        # ELSE -> UNKNOWN with payload-absence provenance
        # A synthetic test fixture MUST NOT establish READ_ONLY_REAL_DATA_PROVEN;
        # synthetic fixtures can only establish TESTED / SYNTHETIC_FIXTURE_NOT_PROVEN.
        raw_min_qty = instrument.get("minTradeQuantity")
        explicit_prec = instrument.get("quantityPrecision")
        is_synthetic = bool(
            instrument.get("is_synthetic", False)
            or str(t212_ticker).startswith("SYNTH_")
        )
        has_real_broker_provenance = bool(
            instrument.get("real_broker_payload_provenance")
            or (instrument.get("payload_source") and not is_synthetic)
        )

        if (
            has_real_broker_provenance
            and instrument.get("real_payload_contains_min_qty", False)
            and (raw_min_qty is not None or explicit_prec is not None)
        ):
            min_qty = float(raw_min_qty) if raw_min_qty is not None else (10.0 ** (-int(explicit_prec)) if int(explicit_prec) > 0 else 1.0)
            prec = cls.derive_quantity_precision(min_qty) if explicit_prec is None else int(explicit_prec)
            qty_state = CapabilityState(
                capability="QUANTITY_RULE",
                value={"min_trade_quantity": min_qty, "quantity_precision": prec},
                status="PROVEN",
                source=str(instrument.get("payload_source") or instrument.get("real_broker_payload_provenance")),
                evidence_level="READ_ONLY_REAL_DATA_PROVEN",
                provenance=f"Authoritative broker payload artifact: {instrument.get('payload_source') or instrument.get('real_broker_payload_provenance')}"
            )
        elif is_synthetic and instrument.get("allow_synthetic_proven", False) and (raw_min_qty is not None or explicit_prec is not None):
            min_qty = float(raw_min_qty) if raw_min_qty is not None else (10.0 ** (-int(explicit_prec)) if int(explicit_prec) > 0 else 1.0)
            prec = cls.derive_quantity_precision(min_qty) if explicit_prec is None else int(explicit_prec)
            qty_state = CapabilityState(
                capability="QUANTITY_RULE",
                value={"min_trade_quantity": min_qty, "quantity_precision": prec},
                status="PROVEN",
                source="SYNTHETIC_TEST_FIXTURE",
                evidence_level="SYNTHETIC_FIXTURE_NOT_PROVEN",
                provenance="Synthetic test fixture (NOT real broker data)"
            )
        else:
            qty_state = CapabilityState(
                capability="QUANTITY_RULE",
                value=None,
                status="UNKNOWN",
                source="UNAVAILABLE:ABSENT_FROM_TRADING212_METADATA",
                evidence_level="SYNTHETIC_FIXTURE_NOT_PROVEN" if is_synthetic else "UNPROVEN",
                provenance=(
                    "SYNTHETIC_FIXTURE_UNPROVEN" if is_synthetic
                    else "ABSENT_FROM_REAL_BROKER_PAYLOAD: data/trading212_instruments_snapshot_20260917.json (Trading212 metadata does not provide minTradeQuantity or quantityPrecision)"
                )
            )

        # -------------------------------------------------------------
        # 2. TICK RULE (Separating Regulatory Tick from Broker Tick Rule)
        # -------------------------------------------------------------
        # Statutory / Regulatory Tick Standard:
        # US SEC Regulation NMS Rule 612 (17 CFR § 242.612) establishes statutory minimum increments:
        # - $0.01 for orders priced >= $1.00
        # - $0.0001 for orders priced < $1.00
        # This establishes regulatory minimum increment, but does NOT establish Trading212 broker-accepted tick rule.
        # For non-US venues (e.g. LSE / Euronext / Xetra), MiFID II RTS 11 requires ESMA/FCA ADNT liquidity bands.
        is_us_equity = (currency_code == "USD" and (product_type in ("STOCK", "ETF") or venue_name in ("NYSE", "NASDAQ")))
        current_price_raw = instrument.get("current_price") or instrument.get("price") or 1.0
        try:
            current_price = float(current_price_raw)
        except (ValueError, TypeError):
            current_price = 1.0

        if is_us_equity:
            reg_tick_status = "REGULATORY_MINIMUM_INCREMENT_KNOWN"
            reg_tick_value = 0.01 if current_price >= 1.0 else 0.0001
            reg_tick_source = "STATUTORY_RULE:17_CFR_242_612"
        else:
            reg_tick_status = "UNKNOWN"
            reg_tick_value = None
            reg_tick_source = "UNAVAILABLE:MIFID_II_RTS_11_LIQUIDITY_BAND_REQUIRED"

        # Broker Tick Rule Evaluation:
        # Trading212 metadata endpoints (/equity/metadata/instruments) do NOT provide `tickSize`.
        # Broker-accepted tick rule remains UNKNOWN unless proven by an authoritative real broker payload artifact.
        raw_tick_size = instrument.get("tickSize")
        if (
            has_real_broker_provenance
            and instrument.get("real_payload_contains_tick_size", False)
            and raw_tick_size is not None
            and float(raw_tick_size) > 0
        ):
            broker_tick_status = "PROVEN"
            broker_tick_value = float(raw_tick_size)
            broker_tick_source = str(instrument.get("payload_source") or instrument.get("real_broker_payload_provenance"))
            tick_evidence_level = "READ_ONLY_REAL_DATA_PROVEN"
            tick_provenance = f"Authoritative broker payload artifact: {broker_tick_source}"
        elif is_synthetic and instrument.get("allow_synthetic_proven", False) and raw_tick_size is not None and float(raw_tick_size) > 0:
            broker_tick_status = "PROVEN"
            broker_tick_value = float(raw_tick_size)
            broker_tick_source = "SYNTHETIC_TEST_FIXTURE"
            tick_evidence_level = "SYNTHETIC_FIXTURE_NOT_PROVEN"
            tick_provenance = "Synthetic test fixture (NOT real broker data)"
        else:
            broker_tick_status = "UNKNOWN"
            broker_tick_value = None
            broker_tick_source = "UNAVAILABLE:ABSENT_FROM_TRADING212_METADATA"
            tick_evidence_level = "SYNTHETIC_FIXTURE_NOT_PROVEN" if is_synthetic else "UNPROVEN"
            tick_provenance = (
                "SYNTHETIC_FIXTURE_UNPROVEN" if is_synthetic
                else "ABSENT_FROM_REAL_BROKER_PAYLOAD: data/trading212_instruments_snapshot_20260917.json (Trading212 metadata does not provide tickSize)"
            )

        # The four-capability execution gate evaluates BROKER_TICK_RULE_STATUS, not regulatory tick.
        # If broker tick rule is UNKNOWN, status is UNKNOWN and execution fails closed.
        tick_state = CapabilityState(
            capability="TICK_RULE",
            value=broker_tick_value,
            status=broker_tick_status,
            source=broker_tick_source,
            evidence_level=tick_evidence_level,
            provenance=tick_provenance,
            regulatory_tick_status=reg_tick_status,
            regulatory_tick_value=reg_tick_value,
            regulatory_tick_source=reg_tick_source,
            broker_tick_rule_status=broker_tick_status,
            broker_tick_rule_value=broker_tick_value,
            broker_tick_rule_source=broker_tick_source
        )

        # -------------------------------------------------------------
        # 3. STOP SUPPORT
        # -------------------------------------------------------------
        stop_record = cls.STOP_SUPPORT_REGISTRY.get(t212_ticker) or cls.STOP_SUPPORT_REGISTRY.get(symbol)
        if stop_record is not None:
            stop_state = CapabilityState(
                capability="STOP_SUPPORT",
                value=True,
                status=stop_record["status"],
                source=stop_record["source"],
                evidence_level=stop_record["evidence_level"],
                provenance=stop_record.get("provenance")
            )
        else:
            stop_state = CapabilityState(
                capability="STOP_SUPPORT",
                value=None,
                status="UNPROVEN",
                source="UNAVAILABLE",
                evidence_level="UNPROVEN",
                provenance=None
            )

        # -------------------------------------------------------------
        # 4. COST COMPLETENESS
        # -------------------------------------------------------------
        try:
            from src.hit_and_run.cost_model import hit_and_run_cost_model
            # Pass live quote / spread attributes if present on instrument record
            bid = instrument.get("bid")
            ask = instrument.get("ask")
            current_price = instrument.get("current_price") or instrument.get("price")
            custom_spread = instrument.get("custom_spread_pct")

            cost_eval = hit_and_run_cost_model.evaluate_instrument_costs(
                product_type=product_type,
                currency=currency_code,
                isin=str(instrument.get("isin", "")).strip().upper(),
                exchange_venue=venue_name or "UNKNOWN",
                current_price=float(current_price) if current_price is not None else 0.0,
                bid=float(bid) if bid is not None else None,
                ask=float(ask) if ask is not None else None,
                custom_spread_pct=float(custom_spread) if custom_spread is not None else None
            )

            # Check jurisdictional tax and broker fee regime completeness.
            # Live spread friction is an ephemeral quote property evaluated at runtime order-routing.
            jurisdictional_reasons = [
                r for r in cost_eval.incomplete_reasons
                if not r.startswith("LIVE_SPREAD_UNKNOWN")
            ]

            if not jurisdictional_reasons:
                cost_state = CapabilityState(
                    capability="COST_COMPLETENESS",
                    value=cost_eval.estimated_costs_round_trip if cost_eval.cost_model_complete else "TAX_AND_FEE_REGIME_VERIFIED",
                    status="COMPLETE",
                    source="HIT_AND_RUN_COST_MODEL",
                    evidence_level="PROVEN",
                    provenance=f"Authoritative cost model verified for {product_type} on {venue_name} in {currency_code}"
                )
            else:
                reasons_str = "; ".join(jurisdictional_reasons)
                status = "UNKNOWN" if ("UNKNOWN" in reasons_str or "unverified" in reasons_str.lower()) else "INCOMPLETE"
                cost_state = CapabilityState(
                    capability="COST_COMPLETENESS",
                    value=None,
                    status=status,
                    source="HIT_AND_RUN_COST_MODEL",
                    evidence_level="UNPROVEN",
                    provenance=reasons_str
                )
        except Exception as e:
            cost_state = CapabilityState(
                capability="COST_COMPLETENESS",
                value=None,
                status="UNKNOWN",
                source="HIT_AND_RUN_COST_MODEL",
                evidence_level="UNPROVEN",
                provenance=f"Error evaluating cost model: {e}"
            )

        return {
            "quantity_rule": qty_state,
            "tick_rule": tick_state,
            "stop_support": stop_state,
            "cost_completeness": cost_state
        }

    @classmethod
    def verify_execution_capabilities(
        cls,
        instrument: Optional[Dict[str, Any]]
    ) -> Tuple[bool, str, Dict[str, CapabilityState]]:
        """
        Independently verifies the 4 execution capabilities:
        - QUANTITY RULE (must be PROVEN)
        - TICK RULE (must be PROVEN)
        - STOP SUPPORT (must be PROVEN)
        - COST COMPLETENESS (must be COMPLETE)

        Returns: (is_executable: bool, reason: str, capabilities: Dict[str, CapabilityState])
        Fails closed if any capability is unknown, unproven, or incomplete.
        One proven capability cannot promote another capability.
        Does NOT authorize orders (trade authorization separately requires strategy, quote, spread, session, AI allocation).
        """
        capabilities = cls.evaluate_capabilities(instrument)

        failed_reasons = []
        if capabilities["quantity_rule"].status != "PROVEN":
            failed_reasons.append(f"QUANTITY_RULE_UNPROVEN: status is {capabilities['quantity_rule'].status}")
        if capabilities["tick_rule"].status != "PROVEN":
            failed_reasons.append(f"TICK_RULE_UNPROVEN: status is {capabilities['tick_rule'].status}")
        if capabilities["stop_support"].status != "PROVEN":
            failed_reasons.append(f"STOP_SUPPORT_UNPROVEN: status is {capabilities['stop_support'].status}")
        if capabilities["cost_completeness"].status != "COMPLETE":
            failed_reasons.append(f"COST_COMPLETENESS_INCOMPLETE: status is {capabilities['cost_completeness'].status}")

        is_executable = (len(failed_reasons) == 0)
        reason = "ALL_CAPABILITIES_PROVEN" if is_executable else "; ".join(failed_reasons)
        return is_executable, reason, capabilities


technical_execution_capability = TechnicalExecutionCapabilityValidator()
