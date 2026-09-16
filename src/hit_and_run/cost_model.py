"""
PRV Capital - Hit-and-Run Authoritative Transaction Cost & Regulatory Tax Model
Evaluates true Net P&L transaction friction with instrument/venue-specific rules:
1. Trading212 FX Fee (0.15% per leg on non-GBP/GBX transactions)
2. UK Stamp Duty Reserve Tax (0.50% on BUY of UK main-market ordinary equities; EXEMPT on ETFs, AIM, Foreign, Sells)
3. Panel on Takeovers & Mergers (PTM) Levy (£1.50 on UK/CI/IoM transactions > £10,000; EXEMPT on ETFs and <= £10,000)
4. US SEC Section 31 Fee (0.00206% on SELL of US-listed securities)
5. US FINRA Trading Activity Fee ($0.000195/share capped at $9.79 on SELL of US securities)
6. French Financial Transaction Tax (0.40% on BUY of Euronext Paris French equities with market cap > €1bn)
7. Italian Tobin Tax (0.10% on BUY of Borsa Italiana Italian equities)
8. Spanish FTT (0.20% on BUY of Bolsa de Madrid Spanish equities > €1bn)
9. Bid-Ask Spread Friction

Enforces strict completeness:
If tax/fee applicability for an instrument cannot be established reliably:
    COST_MODEL_COMPLETE = False
    strategy may score the instrument informationally
    but it MUST NOT be authorised for a real order where expected NET profit
    depends on an unknown material charge.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class CostEvaluationResult:
    cost_model_complete: bool
    incomplete_reasons: List[str]
    estimated_costs_round_trip: Optional[float]
    fx_fee_rate: float
    stamp_duty_rate: float
    ptm_levy_amount_gbp: float
    sec_fee_rate: float
    finra_fee_rate: float
    french_ftt_rate: float
    italian_ftt_rate: float
    spanish_ftt_rate: float
    spread_friction: Optional[float] = None
    finra_fee_amount_usd: Optional[float] = None
    fee_breakdown: Dict[str, Any] = field(default_factory=dict)


class HitAndRunCostModel:
    """Authoritative cost & tax evaluator enforcing regulatory schedules and Trading212 terms."""

    # 2026 Authoritative Rates
    TRADING212_FX_FEE_RATE = 0.0015         # 15 bps per side on non-GBP/GBX transactions (0.30% round trip)
    UK_SDRT_RATE = 0.0050                   # 0.50% UK SDRT on qualifying main-market equity buys (exempt on ETFs & AIM)
    PTM_LEVY_THRESHOLD_GBP = 10000.0        # £10,000 Takeover Panel threshold
    PTM_LEVY_PER_LEG_GBP = 1.50             # £1.50 flat fee per qualifying leg (> £10,000 consideration)
    SEC_SECTION_31_RATE = 0.0000206         # Current FY2026 rate from 4 April 2026: $20.60 per $1,000,000 (0.00206%) on US sells
    FINRA_TAF_PER_SHARE_USD = 0.000195      # Trading212 Published Fee Schedule: $0.000195 * quantity sold
    FINRA_TAF_MAX_FEE_USD = 9.79            # FINRA statutory cap per transaction ($9.79)
    FRENCH_FTT_RATE = 0.0040                # 0.40% on Euronext Paris French equities > €1bn (effective 1 April 2025 per French BOFiP / Art. 235 ter ZD and Trading212 fee schedule)
    ITALIAN_FTT_RATE = 0.0010               # 0.10% statutory rate (Italian Law 228/2012; not withheld by Trading212 at order execution)
    SPANISH_FTT_RATE = 0.0020               # 0.20% statutory rate (Spanish Law 5/2020; not withheld by Trading212 at order execution)

    # UK Regulated Main Market Venues (where SDRT applies to ordinary shares)
    UK_MAIN_MARKET_VENUES = {
        "London Stock Exchange",
        "London Stock Exchange NON-ISA",
        "LSE",
        "XLON"
    }

    # UK MTF Venues (where SDRT is legally exempt by statute)
    UK_MTF_VENUES = {
        "London Stock Exchange AIM",
        "AIM",
        "AIMX"
    }

    # US National Securities Exchanges
    US_VENUES = {
        "NYSE",
        "NASDAQ",
        "XNYS",
        "XNAS"
    }

    def evaluate_instrument_costs(
        self,
        product_type: str,
        currency: str,
        isin: str = "",
        exchange_venue: str = "",
        current_price: float = 1.0,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        order_size_gbp: Optional[float] = None,
        order_quantity: Optional[float] = None,
        market_cap_eur: Optional[float] = None,
        market_cap_tier: Optional[str] = None,
        french_ftt_applicable: Optional[bool] = None,
        custom_spread_pct: Optional[float] = None,
        order_preview_fees: Optional[Dict[str, float]] = None
    ) -> CostEvaluationResult:
        """
        Evaluates all applicable customer execution fees and taxes with strict completeness checking.
        Enforces execution source precedence:
        1. Trading212 order preview / broker metadata if available
        2. Current Trading212 published customer fee schedule
        3. Authoritative statutory/exchange source where broker treatment is established
        4. Otherwise COST_MODEL_COMPLETE = False
        """
        cost_complete = True
        reasons: List[str] = []

        pt_upper = product_type.upper().strip()
        curr_upper = currency.upper().strip()
        isin_upper = isin.upper().strip()
        venue_clean = exchange_venue.strip()

        # Precedence 1: Exact Broker Order Preview
        if order_preview_fees is not None:
            # If explicit broker order preview metadata provides customer charges
            fx_rate = float(order_preview_fees.get("fx_rate", 0.0))
            stamp_duty_rate = float(order_preview_fees.get("stamp_duty_rate", 0.0))
            sec_rate = float(order_preview_fees.get("sec_rate", 0.0))
            finra_rate = float(order_preview_fees.get("finra_rate", 0.0))
            finra_fee_amount_usd = float(order_preview_fees.get("finra_fee", 0.0)) if "finra_fee" in order_preview_fees else None
            french_ftt_rate = float(order_preview_fees.get("french_ftt_rate", 0.0))
            italian_ftt_rate = float(order_preview_fees.get("italian_ftt_rate", 0.0))
            spanish_ftt_rate = float(order_preview_fees.get("spanish_ftt_rate", 0.0))
            ptm_levy_amount = float(order_preview_fees.get("ptm_levy_amount_gbp", 0.0))
        else:
            # Precedence 2 & 3: Trading212 Published Fee Schedule & Established Statutory Treatment
            # 1. Trading212 FX Fee
            # Applied on both entry buy and exit sell when currency is not GBP or GBX
            if curr_upper in ("GBP", "GBX"):
                fx_rate = 0.0
            elif curr_upper in ("USD", "EUR", "CAD", "CHF"):
                # 15 bps on buy + 15 bps on sell = 30 bps round trip
                fx_rate = self.TRADING212_FX_FEE_RATE * 2.0
            else:
                fx_rate = self.TRADING212_FX_FEE_RATE * 2.0
                cost_complete = False
                reasons.append(f"CURRENCY_UNKNOWN: Currency '{curr_upper}' unverified for currency accounting")

            # 2. UK Stamp Duty Reserve Tax (SDRT)
            # Authoritative Rules:
            # - ETFs: EXEMPT by statute (Finance Act 2014 s.65)
            # - AIM: EXEMPT by statute (Finance Act 2014 s.110)
            # - Foreign incorporated (non-GB ISIN): EXEMPT even if quoted in GBX on LSE
            # - Sells: EXEMPT (SDRT applies on purchase only)
            # - Only UK ordinary shares (product_type == STOCK, ISIN starts with GB) on UK Main Market incur 0.5% SDRT
            stamp_duty_rate = 0.0
            if pt_upper == "ETF":
                stamp_duty_rate = 0.0
            elif venue_clean in self.UK_MTF_VENUES:
                stamp_duty_rate = 0.0
            elif venue_clean in self.UK_MAIN_MARKET_VENUES:
                if isin_upper.startswith("GB") and pt_upper == "STOCK":
                    stamp_duty_rate = self.UK_SDRT_RATE
                elif isin_upper and not isin_upper.startswith("GB"):
                    # Foreign incorporated stock trading in UK (e.g. Irish IE, Jersey JE)
                    stamp_duty_rate = 0.0
                elif not isin_upper:
                    # ISIN is missing on an LSE stock: SDRT cannot be established reliably!
                    cost_complete = False
                    reasons.append("SDRT_STATUS_UNKNOWN: Missing ISIN on UK Main Market equity prevents SDRT verification")
            else:
                # Non-UK venues (NYSE, NASDAQ, Xetra, Paris, etc.)
                stamp_duty_rate = 0.0

            # 3. Takeover Panel PTM Levy
            # Rule: £1.50 per leg for UK/CI/IoM companies on UK venues if consideration > £10,000. ETFs exempt.
            ptm_levy_amount = 0.0
            order_nominal = order_size_gbp or 0.0
            if pt_upper == "ETF":
                ptm_levy_amount = 0.0
            elif order_nominal <= self.PTM_LEVY_THRESHOLD_GBP and order_nominal > 0:
                # Under threshold: strictly exempt (£0.00)
                ptm_levy_amount = 0.0
            elif order_nominal > self.PTM_LEVY_THRESHOLD_GBP:
                if venue_clean in (self.UK_MAIN_MARKET_VENUES | self.UK_MTF_VENUES):
                    if any(isin_upper.startswith(p) for p in ("GB", "JE", "GG", "IM")):
                        # Round trip = £1.50 buy + £1.50 sell = £3.00
                        ptm_levy_amount = self.PTM_LEVY_PER_LEG_GBP * 2.0
                    elif isin_upper:
                        ptm_levy_amount = 0.0
                    else:
                        cost_complete = False
                        reasons.append("PTM_STATUS_UNKNOWN: Order consideration > £10,000 but issuer jurisdiction cannot be verified")
                else:
                    ptm_levy_amount = 0.0
            else:
                # Order size not specified at evaluation time: assume standard position <= £10k (ptm = 0.0)
                ptm_levy_amount = 0.0

            # 4. US Transaction Fee (SEC Section 31) & FINRA Fee
            # Execution Precedence:
            # 1. Trading212 live order-preview charge, if available
            # 2. Current Trading212 published fee schedule: $0.000195 * quantity sold (max $9.79) for covered US stock and ETF sales
            # 3. Otherwise COST_MODEL_COMPLETE = False
            sec_rate = 0.0
            finra_rate = 0.0
            finra_fee_amount_usd = None
            if venue_clean in self.US_VENUES:
                sec_rate = self.SEC_SECTION_31_RATE
                if order_quantity is not None and order_quantity > 0:
                    finra_fee_amount_usd = min(self.FINRA_TAF_MAX_FEE_USD, self.FINRA_TAF_PER_SHARE_USD * order_quantity)
                    finra_rate = float(finra_fee_amount_usd / (order_quantity * current_price)) if current_price > 0 else 0.0
                elif current_price > 0:
                    # Informational per-share rate from Trading212 published schedule ($0.000195 * 1 share / price)
                    finra_fee_amount_usd = self.FINRA_TAF_PER_SHARE_USD
                    finra_rate = float(self.FINRA_TAF_PER_SHARE_USD / current_price)
                else:
                    cost_complete = False
                    reasons.append("FINRA_FEE_UNKNOWN: Cannot calculate Trading212 published FINRA fee without price or quantity")

            # 5. French Financial Transaction Tax (FTT)
            # 0.40% on BUY of French tax resident equities (ISIN prefix FR) with market cap > €1bn on Euronext Paris
            # Effective 1 April 2025 per French BOFiP / Article 235 ter ZD and current Trading212 fee schedule
            french_ftt_rate = 0.0
            if venue_clean == "Euronext Paris" and isin_upper.startswith("FR") and pt_upper == "STOCK":
                if french_ftt_applicable is True or market_cap_tier == "LARGE" or (market_cap_eur and market_cap_eur > 1e9):
                    french_ftt_rate = self.FRENCH_FTT_RATE
                elif french_ftt_applicable is False or (market_cap_eur and market_cap_eur <= 1e9):
                    french_ftt_rate = 0.0
                else:
                    # Market cap eligibility cannot be established reliably
                    cost_complete = False
                    reasons.append("FRENCH_FTT_STATUS_UNKNOWN: Market capitalization unverified for French FTT applicability")

            # 6. Italian Tobin Tax
            # Statutory Source: Italian Law 228/2012 (Art. 1, paras 491-500) sets 0.10% on Italian share purchases >= €500m.
            # Broker Execution Applicability: Trading212 does NOT act as a tax-withholding agent for Italian Tobin Tax
            # (operates under a declarative tax reporting model and does not deduct it at execution).
            # Unless verified on live order preview, customer execution applicability is unverified -> COST_STATUS_UNKNOWN.
            italian_ftt_rate = 0.0
            if venue_clean == "Borsa Italiana" or isin_upper.startswith("IT"):
                cost_complete = False
                reasons.append("COST_STATUS_UNKNOWN: Trading212 customer execution applicability for Italian Tobin Tax (Law 228/2012) is unverified on published schedule")

            # 7. Spanish FTT
            # Statutory Source: Spanish Law 5/2020 sets 0.20% on Spanish share purchases > €1bn.
            # Broker Execution Applicability: Trading212 does NOT act as a tax-withholding agent for Spanish FTT.
            # Unless verified on live order preview, customer execution applicability is unverified -> COST_STATUS_UNKNOWN.
            spanish_ftt_rate = 0.0
            if venue_clean == "Bolsa de Madrid" or isin_upper.startswith("ES"):
                cost_complete = False
                reasons.append("COST_STATUS_UNKNOWN: Trading212 customer execution applicability for Spanish FTT (Law 5/2020) is unverified on published schedule")

        # 8. Spread Friction (STRICTLY AUTHORITATIVE LIVE QUOTES - NO ZERO / NO FABRICATED FALLBACK)
        # If authoritative live bid/ask spread is unavailable:
        # spread_friction = None, cost_model_complete = False, reason = LIVE_SPREAD_UNKNOWN, execution_authorised = False
        if bid is not None and ask is not None and ask > bid and current_price > 0:
            spread_friction = float((ask - bid) / current_price)
        elif custom_spread_pct is not None and custom_spread_pct > 0:
            spread_friction = float(custom_spread_pct)
        else:
            spread_friction = None
            cost_complete = False
            reasons.append("LIVE_SPREAD_UNKNOWN: Authoritative live bid/ask spread unavailable")

        # Total Estimated Round-Trip Friction Rate
        if spread_friction is not None:
            total_costs = float(
                fx_rate + stamp_duty_rate + sec_rate + finra_rate +
                french_ftt_rate + italian_ftt_rate + spanish_ftt_rate + spread_friction
            )
            if ptm_levy_amount > 0 and order_nominal > 0:
                total_costs += float(ptm_levy_amount / order_nominal)
            estimated_costs_round_trip = round(total_costs, 6)
        else:
            # Spread is unknown: composite friction cannot be calculated as zero
            estimated_costs_round_trip = None

        breakdown = {
            "fx_fee_rate": fx_rate,
            "stamp_duty_rate": stamp_duty_rate,
            "ptm_levy_amount_gbp": ptm_levy_amount,
            "sec_fee_rate": sec_rate,
            "finra_fee_rate": finra_rate,
            "finra_fee_amount_usd": finra_fee_amount_usd,
            "french_ftt_rate": french_ftt_rate,
            "italian_ftt_rate": italian_ftt_rate,
            "spanish_ftt_rate": spanish_ftt_rate,
            "spread_friction": spread_friction
        }

        return CostEvaluationResult(
            cost_model_complete=cost_complete,
            incomplete_reasons=reasons,
            estimated_costs_round_trip=estimated_costs_round_trip,
            fx_fee_rate=fx_rate,
            stamp_duty_rate=stamp_duty_rate,
            ptm_levy_amount_gbp=ptm_levy_amount,
            sec_fee_rate=sec_rate,
            finra_fee_rate=finra_rate,
            french_ftt_rate=french_ftt_rate,
            italian_ftt_rate=italian_ftt_rate,
            spanish_ftt_rate=spanish_ftt_rate,
            spread_friction=round(spread_friction, 6) if spread_friction is not None else None,
            finra_fee_amount_usd=finra_fee_amount_usd,
            fee_breakdown=breakdown
        )


hit_and_run_cost_model = HitAndRunCostModel()
