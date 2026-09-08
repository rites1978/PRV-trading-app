"""
🏛️ PRV CAPITAL | VERSIONED COST-SCHEDULE CONTRACT
Explicit, auditable, point-in-time transaction cost schedules.

No hardcoded timeless fee constants.
All regulatory, tax, broker, and market-friction parameters are versioned
with effective date intervals [effective_from, effective_to], calculation bases,
and source attribution.

Simulations query the schedule active on the simulated trade date.
Production fails closed if a required cost schedule is missing or expired.
"""
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import json
import logging

logger = logging.getLogger(__name__)


class FeeType(str, Enum):
    FX_CONVERSION = "FX_CONVERSION"
    SDRT = "SDRT"
    PTM_LEVY = "PTM_LEVY"
    SEC_SECTION_31 = "SEC_SECTION_31"
    FINRA_TAF = "FINRA_TAF"
    SPREAD = "SPREAD"
    SLIPPAGE = "SLIPPAGE"


class Jurisdiction(str, Enum):
    US = "US"
    UK = "UK"
    GLOBAL = "GLOBAL"


class InstrumentClass(str, Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    ALL = "ALL"


class CalculationBasis(str, Enum):
    NOTIONAL_BUY = "NOTIONAL_BUY"               # Rate * Buy Consideration
    NOTIONAL_SELL = "NOTIONAL_SELL"             # Rate * Sell Consideration
    NOTIONAL_BOTH = "NOTIONAL_BOTH"             # Rate * Order Consideration (applied to both buy and sell)
    PER_SHARE_SOLD = "PER_SHARE_SOLD"           # Rate * Quantity Sold
    FIXED_PER_LEG_IF_THRESHOLD = "FIXED_PER_LEG_IF_THRESHOLD" # Fixed amount per buy/sell if notional > threshold


@dataclass(frozen=True)
class CostScheduleEntry:
    fee_type: FeeType
    jurisdiction: Jurisdiction
    instrument_class: InstrumentClass
    rate: float                                 # Decimal rate (e.g. 0.0015 for 0.15%, 0.0000206 for SEC)
    calculation_basis: CalculationBasis
    threshold: float = 0.0                      # Qualifying threshold (e.g. £10,000 for PTM levy)
    minimum: float = 0.0                        # Min fee in fee_currency (e.g. $0.01 for FINRA TAF)
    maximum: Optional[float] = None             # Max fee in fee_currency (e.g. $9.79 for FINRA TAF)
    fee_currency: str = "GBP"                   # Currency of the fee calculation (GBP or USD)
    effective_from: str = "2020-01-01"          # ISO date YYYY-MM-DD
    effective_to: Optional[str] = None          # ISO date YYYY-MM-DD or None if currently active
    source: str = ""                            # Official regulatory/broker publication
    source_retrieved_at: str = ""               # ISO timestamp YYYY-MM-DDTHH:MM:SSZ

    def is_active_on(self, trade_date: date) -> bool:
        """Verify whether this cost schedule is effective on trade_date."""
        dt_str = trade_date.isoformat()
        if dt_str < self.effective_from:
            return False
        if self.effective_to and dt_str > self.effective_to:
            return False
        return True


# Master Registry of Authoritative, Versioned Cost Schedules
VERSIONED_COST_REGISTRY: List[CostScheduleEntry] = [
    # 1. Trading 212 FX Conversion Fee (0.15% each side on non-base currency)
    CostScheduleEntry(
        fee_type=FeeType.FX_CONVERSION,
        jurisdiction=Jurisdiction.GLOBAL,
        instrument_class=InstrumentClass.ALL,
        rate=0.0015,
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="GBP",
        effective_from="2020-01-01",
        effective_to=None,
        source="Trading 212 UK Terms of Business & Fee Schedule",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 2. UK Stamp Duty Reserve Tax (SDRT) - 0.50% on UK equity BUY
    CostScheduleEntry(
        fee_type=FeeType.SDRT,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.EQUITY,
        rate=0.0050,
        calculation_basis=CalculationBasis.NOTIONAL_BUY,
        fee_currency="GBP",
        effective_from="1986-10-27",
        effective_to=None,
        source="UK Finance Act 1986 Section 86-90 / HMRC Stamp Taxes on Shares",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 3. UK SDRT Exemption for Qualifying Collective Investment Schemes & ETFs (0.00%)
    CostScheduleEntry(
        fee_type=FeeType.SDRT,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ETF,
        rate=0.0000,
        calculation_basis=CalculationBasis.NOTIONAL_BUY,
        fee_currency="GBP",
        effective_from="2014-03-30",
        effective_to=None,
        source="UK Finance Act 2014 Section 114 (Abolition of SDRT on UK ETF/CIS)",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 4. UK PTM Levy - Current Schedule: £1.50 Buy + £1.50 Sell for qualifying trades > £10,000
    CostScheduleEntry(
        fee_type=FeeType.PTM_LEVY,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.EQUITY,
        rate=1.50,                             # £1.50 per leg
        calculation_basis=CalculationBasis.FIXED_PER_LEG_IF_THRESHOLD,
        threshold=10000.0,                     # Trades > £10,000
        fee_currency="GBP",
        effective_from="2024-04-01",
        effective_to=None,
        source="Panel on Takeovers and Mergers (PTM) Code on Takeovers and Mergers",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 5. UK PTM Levy Exemption for ETFs/ETPs (£0.00)
    CostScheduleEntry(
        fee_type=FeeType.PTM_LEVY,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ETF,
        rate=0.00,
        calculation_basis=CalculationBasis.FIXED_PER_LEG_IF_THRESHOLD,
        threshold=10000.0,
        fee_currency="GBP",
        effective_from="2000-01-01",
        effective_to=None,
        source="Panel on Takeovers and Mergers Exempt Securities List (ETFs exempt)",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 6a. US SEC Section 31 Transaction Fee (Historical 2020-2025 rate: $8.00 per $1M)
    CostScheduleEntry(
        fee_type=FeeType.SEC_SECTION_31,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.ALL,
        rate=0.0000080,                        # $8.00 per $1,000,000
        calculation_basis=CalculationBasis.NOTIONAL_SELL,
        fee_currency="USD",
        effective_from="2020-01-01",
        effective_to="2025-05-21",
        source="SEC Fee Rate Advisory FY2020-FY2024",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 6b. US SEC Section 31 Transaction Fee (Prior Rate: $27.80 per $1M until 2026-04-03)
    CostScheduleEntry(
        fee_type=FeeType.SEC_SECTION_31,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.ALL,
        rate=0.0000278,                        # $27.80 per $1,000,000
        calculation_basis=CalculationBasis.NOTIONAL_SELL,
        fee_currency="USD",
        effective_from="2025-05-22",
        effective_to="2026-04-03",
        source="SEC Fee Rate Advisory #1 FY2025",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 7. US SEC Section 31 Transaction Fee (Current Rate: $20.60 per $1M effective 2026-04-04)
    CostScheduleEntry(
        fee_type=FeeType.SEC_SECTION_31,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.ALL,
        rate=0.0000206,                        # $20.60 per $1,000,000
        calculation_basis=CalculationBasis.NOTIONAL_SELL,
        fee_currency="USD",
        effective_from="2026-04-04",
        effective_to=None,
        source="SEC Fee Rate Advisory FY2026 / Release No. 34-XXXXX",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 8. US FINRA Trading Activity Fee (TAF) (Prior Rate: $0.000166/share, max $8.30 until 2025-12-31)
    CostScheduleEntry(
        fee_type=FeeType.FINRA_TAF,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.EQUITY,
        rate=0.000166,
        calculation_basis=CalculationBasis.PER_SHARE_SOLD,
        minimum=0.01,
        maximum=8.30,
        fee_currency="USD",
        effective_from="2020-01-01",
        effective_to="2025-12-31",
        source="FINRA By-Laws Schedule A Section 1(b) (Pre-2026 schedule)",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 9. US FINRA Trading Activity Fee (TAF) (Current Rate: $0.000195/share, max $9.79 effective 2026-01-01)
    CostScheduleEntry(
        fee_type=FeeType.FINRA_TAF,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.EQUITY,
        rate=0.000195,
        calculation_basis=CalculationBasis.PER_SHARE_SOLD,
        minimum=0.01,
        maximum=9.79,
        fee_currency="USD",
        effective_from="2026-01-01",
        effective_to=None,
        source="FINRA Regulatory Notice 2026 Fee Revision / Trading 212 Regulatory Schedule",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),

    # 10. Empirical Baseline Market Spreads & Slippage (Versioned by regime)
    CostScheduleEntry(
        fee_type=FeeType.SPREAD,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.EQUITY,
        rate=0.0003,                           # 3.0 bps round-trip for large-cap US equities
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="USD",
        effective_from="2020-01-01",
        effective_to=None,
        source="Empirical NBBO Liquid Universe Observation",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),
    CostScheduleEntry(
        fee_type=FeeType.SPREAD,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ETF,
        rate=0.0005,                           # 5.0 bps round-trip for LSE Index ETFs
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="GBP",
        effective_from="2020-01-01",
        effective_to=None,
        source="LSE Market Maker Tight Spreads Observation",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),
    CostScheduleEntry(
        fee_type=FeeType.SPREAD,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.EQUITY,
        rate=0.0008,                           # 8.0 bps round-trip for FTSE 100 constituents
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="GBP",
        effective_from="2020-01-01",
        effective_to=None,
        source="LSE Equity Order Book Observation",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),
    CostScheduleEntry(
        fee_type=FeeType.SLIPPAGE,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.EQUITY,
        rate=0.0002,                           # 2.0 bps market impact / execution slippage for US mega-caps
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="USD",
        effective_from="2020-01-01",
        effective_to=None,
        source="PRV US Liquid Execution Benchmark",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),
    CostScheduleEntry(
        fee_type=FeeType.SLIPPAGE,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ALL,
        rate=0.0003,                           # 3.0 bps market impact / execution slippage for UK instruments
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="GBP",
        effective_from="2020-01-01",
        effective_to=None,
        source="PRV UK Execution Benchmark",
        source_retrieved_at="2026-09-08T00:00:00Z"
    ),
    CostScheduleEntry(
        fee_type=FeeType.SLIPPAGE,
        jurisdiction=Jurisdiction.GLOBAL,
        instrument_class=InstrumentClass.ALL,
        rate=0.0002,                           # 2.0 bps default market impact
        calculation_basis=CalculationBasis.NOTIONAL_BOTH,
        fee_currency="GBP",
        effective_from="2020-01-01",
        effective_to=None,
        source="PRV Global Execution Default",
        source_retrieved_at="2026-09-08T00:00:00Z"
    )
]


class CostScheduleRepository:
    """
    Query engine for versioned cost schedules.
    Enforces strict point-in-time lookup and fails closed if a required
    fee schedule is missing, invalid, or expired.
    """
    def __init__(self, registry: Optional[List[CostScheduleEntry]] = None):
        self._registry = registry or VERSIONED_COST_REGISTRY

    def get_entry(
        self,
        fee_type: FeeType,
        jurisdiction: Jurisdiction,
        instrument_class: InstrumentClass,
        trade_date: date
    ) -> CostScheduleEntry:
        """
        Point-in-time fee lookup.
        Returns the single active entry matching the criteria on trade_date.
        Raises LookupError (Fail-Closed) if missing.
        """
        matches = []
        for entry in self._registry:
            if entry.fee_type != fee_type:
                continue
            # Jurisdiction match (exact or GLOBAL)
            if entry.jurisdiction != jurisdiction and entry.jurisdiction != Jurisdiction.GLOBAL:
                continue
            # Instrument class match (exact or ALL)
            if entry.instrument_class != instrument_class and entry.instrument_class != InstrumentClass.ALL:
                continue
            # Date active check
            if entry.is_active_on(trade_date):
                matches.append(entry)

        if not matches:
            raise LookupError(
                f"FAIL-CLOSED: No active cost schedule found for "
                f"fee_type={fee_type.value}, jurisdiction={jurisdiction.value}, "
                f"instrument_class={instrument_class.value} on trade_date={trade_date}"
            )
        
        # If multiple matches, sort by specificity: exact jurisdiction & class > GLOBAL / ALL
        def specificity(e: CostScheduleEntry) -> int:
            score = 0
            if e.jurisdiction == jurisdiction:
                score += 2
            if e.instrument_class == instrument_class:
                score += 1
            return score

        matches.sort(key=specificity, reverse=True)
        return matches[0]

    def validate_production_health(self, check_date: date) -> Dict[str, Any]:
        """
        Production health check.
        Ensures that every required fee component for operational universes
        is currently active and verifiable on check_date.
        """
        required_checks = [
            (FeeType.FX_CONVERSION, Jurisdiction.GLOBAL, InstrumentClass.ALL),
            (FeeType.SDRT, Jurisdiction.UK, InstrumentClass.EQUITY),
            (FeeType.SDRT, Jurisdiction.UK, InstrumentClass.ETF),
            (FeeType.PTM_LEVY, Jurisdiction.UK, InstrumentClass.EQUITY),
            (FeeType.PTM_LEVY, Jurisdiction.UK, InstrumentClass.ETF),
            (FeeType.SEC_SECTION_31, Jurisdiction.US, InstrumentClass.ALL),
            (FeeType.FINRA_TAF, Jurisdiction.US, InstrumentClass.EQUITY),
        ]
        
        results = {}
        all_passed = True
        for ft, jur, ic in required_checks:
            key = f"{ft.value}_{jur.value}_{ic.value}"
            try:
                entry = self.get_entry(ft, jur, ic, check_date)
                results[key] = {
                    "status": "VALID",
                    "rate": entry.rate,
                    "basis": entry.calculation_basis.value,
                    "source": entry.source,
                    "effective_from": entry.effective_from,
                    "effective_to": entry.effective_to
                }
            except Exception as e:
                results[key] = {"status": "FAIL_CLOSED", "error": str(e)}
                all_passed = False

        return {
            "all_passed": all_passed,
            "check_date": check_date.isoformat(),
            "details": results
        }

    def calculate_trade_costs(
        self,
        trade_date: date,
        jurisdiction: Jurisdiction,
        instrument_class: InstrumentClass,
        buy_notional_gbp: float,
        sell_notional_gbp: float,
        shares: float,
        gbpusd_rate: float = 1.30,
        spread_bps_override: Optional[float] = None,
        slippage_bps_override: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Authoritative transaction cost calculation for a round-trip trade.
        All calculations strictly adhere to versioned schedules effective on trade_date.
        All output values are normalized into GBP.
        """
        costs: Dict[str, float] = {}

        # 1. FX Fee (if US or foreign currency)
        if jurisdiction == Jurisdiction.US:
            fx_entry = self.get_entry(FeeType.FX_CONVERSION, jurisdiction, instrument_class, trade_date)
            costs["buy_fx_gbp"] = round(buy_notional_gbp * fx_entry.rate, 4)
            costs["sell_fx_gbp"] = round(sell_notional_gbp * fx_entry.rate, 4)
            costs["total_fx_gbp"] = round(costs["buy_fx_gbp"] + costs["sell_fx_gbp"], 2)
        else:
            costs["buy_fx_gbp"] = 0.0
            costs["sell_fx_gbp"] = 0.0
            costs["total_fx_gbp"] = 0.0

        # 2. SDRT (UK only, on BUY)
        if jurisdiction == Jurisdiction.UK:
            sdrt_entry = self.get_entry(FeeType.SDRT, jurisdiction, instrument_class, trade_date)
            costs["sdrt_gbp"] = round(buy_notional_gbp * sdrt_entry.rate, 2)
        else:
            costs["sdrt_gbp"] = 0.0

        # 3. PTM Levy (UK only, fixed per leg if notional > threshold)
        if jurisdiction == Jurisdiction.UK:
            ptm_entry = self.get_entry(FeeType.PTM_LEVY, jurisdiction, instrument_class, trade_date)
            buy_ptm = ptm_entry.rate if buy_notional_gbp > ptm_entry.threshold else 0.0
            sell_ptm = ptm_entry.rate if sell_notional_gbp > ptm_entry.threshold else 0.0
            costs["ptm_levy_gbp"] = round(buy_ptm + sell_ptm, 2)
        else:
            costs["ptm_levy_gbp"] = 0.0

        # 4. US SEC Section 31 Fee (US only, on SELL)
        if jurisdiction == Jurisdiction.US:
            sec_entry = self.get_entry(FeeType.SEC_SECTION_31, jurisdiction, instrument_class, trade_date)
            sell_usd = sell_notional_gbp * gbpusd_rate
            sec_usd = sell_usd * sec_entry.rate
            costs["sec_fee_usd"] = round(sec_usd, 4)
            costs["sec_fee_gbp"] = round(sec_usd / gbpusd_rate, 4)
        else:
            costs["sec_fee_usd"] = 0.0
            costs["sec_fee_gbp"] = 0.0

        # 5. US FINRA TAF (US only, on SELL per share)
        if jurisdiction == Jurisdiction.US:
            finra_entry = self.get_entry(FeeType.FINRA_TAF, jurisdiction, instrument_class, trade_date)
            raw_taf = shares * finra_entry.rate
            capped_taf = max(finra_entry.minimum, raw_taf)
            if finra_entry.maximum is not None:
                capped_taf = min(finra_entry.maximum, capped_taf)
            costs["finra_taf_usd"] = round(capped_taf, 4)
            costs["finra_taf_gbp"] = round(capped_taf / gbpusd_rate, 4)
        else:
            costs["finra_taf_usd"] = 0.0
            costs["finra_taf_gbp"] = 0.0

        # 6. Bid/Ask Spread
        if spread_bps_override is not None:
            spread_rate = spread_bps_override / 10000.0
        else:
            spread_entry = self.get_entry(FeeType.SPREAD, jurisdiction, instrument_class, trade_date)
            spread_rate = spread_entry.rate
        half_spread = spread_rate / 2.0
        costs["buy_spread_gbp"] = round(buy_notional_gbp * half_spread, 4)
        costs["sell_spread_gbp"] = round(sell_notional_gbp * half_spread, 4)
        costs["total_spread_gbp"] = round(costs["buy_spread_gbp"] + costs["sell_spread_gbp"], 2)

        # 7. Slippage
        if slippage_bps_override is not None:
            slip_rate = slippage_bps_override / 10000.0
        else:
            slip_entry = self.get_entry(FeeType.SLIPPAGE, jurisdiction, instrument_class, trade_date)
            slip_rate = slip_entry.rate
        half_slip = slip_rate / 2.0
        costs["buy_slippage_gbp"] = round(buy_notional_gbp * half_slip, 4)
        costs["sell_slippage_gbp"] = round(sell_notional_gbp * half_slip, 4)
        costs["total_slippage_gbp"] = round(costs["buy_slippage_gbp"] + costs["sell_slippage_gbp"], 2)

        # Sum total round-trip friction in GBP
        total_friction = (
            costs["total_fx_gbp"] +
            costs["sdrt_gbp"] +
            costs["ptm_levy_gbp"] +
            costs["sec_fee_gbp"] +
            costs["finra_taf_gbp"] +
            costs["total_spread_gbp"] +
            costs["total_slippage_gbp"]
        )
        costs["total_friction_gbp"] = round(total_friction, 2)
        denom = buy_notional_gbp if buy_notional_gbp > 0 else (sell_notional_gbp if sell_notional_gbp > 0 else 1.0)
        costs["friction_pct"] = round((total_friction / denom) * 100, 4)

        return costs
