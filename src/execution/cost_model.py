"""
🏛️ PRV CAPITAL | INSTRUMENT-SPECIFIC TRUE NET P&L TRANSACTION COST MODEL
Comprehensive quantitative transaction friction engine with strict instrument-specific rules and effective-dated 2026 regulatory fees:
- UK Stamp Duty Reserve Tax (0.50% on qualifying LSE main market equity buys; EXEMPT on ETFs, AIM, and Sells)
- Panel on Takeovers & Mergers (PTM) Levy (£1.50 on UK equity transactions > £10,000)
- Foreign Exchange Conversion Fees (0.15% each way on non-GBP denominated trades)
- US Regulatory Charges (SEC Section 31 fee at 0.00206% [$20.60 per $1m] & FINRA TAF at $0.000195/share capped at $9.79 on US sells only)
- Bid-ask spread friction (Estimated vs Actual)
- Execution slippage (Estimated vs Actual)

Outputs:
- Gross P&L
- Total Transaction Cost (Estimated & Actual)
- True NET Realized P&L
- Cost as % of Gross Profit
"""
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List
from src.config.settings import settings


class InstitutionalCostModel:
    """
    True Net P&L Cost Accounting Model.
    Measures profitability strictly AFTER all execution costs, taxes, FX, and spread friction
    derived from authoritative instrument metadata and effective-dated fee schedules.
    """
    def __init__(
        self,
        uk_stamp_duty_rate: float = settings.UK_SDRT_RATE_PCT / 100.0,  # 0.50% UK SDRT
        fx_conversion_rate: float = settings.FX_FEE_BPS / 10000.0,      # 0.15% (15 bps) FX fee
        slippage_rate: float = settings.SLIPPAGE_ESTIMATE_BPS / 10000.0,# 0.10% (10 bps) slippage
        us_sec_fee_rate: float = settings.SEC_SECTION_31_RATE,         # SEC Section 31 ($20.60 / $1m = 0.0000206)
        us_finra_taf_rate: float = settings.FINRA_TAF_PER_SHARE,       # FINRA TAF ($0.000195/share)
        us_finra_taf_max: float = settings.FINRA_TAF_MAX_FEE,          # FINRA TAF max ($9.79)
        ptm_threshold_gbp: float = settings.PTM_LEVY_THRESHOLD_GBP,    # £10,000
        ptm_levy_amount_gbp: float = settings.PTM_LEVY_AMOUNT_GBP,     # £1.50
        min_reward_risk: float = settings.MIN_NET_REWARD_RISK_RATIO,   # 2.0x
        max_cost_to_profit_ratio: float = settings.MAX_COST_TO_PROFIT_RATIO_PCT / 100.0 # 30%
    ):
        self.uk_stamp_duty_rate = uk_stamp_duty_rate
        self.fx_conversion_rate = fx_conversion_rate
        self.slippage_rate = slippage_rate
        self.us_sec_fee_rate = us_sec_fee_rate
        self.us_finra_taf_rate = us_finra_taf_rate
        self.us_finra_taf_max = us_finra_taf_max
        self.ptm_threshold_gbp = ptm_threshold_gbp
        self.ptm_levy_amount_gbp = ptm_levy_amount_gbp
        self.min_reward_risk = min_reward_risk
        self.max_cost_to_profit_ratio = max_cost_to_profit_ratio

    def get_effective_fee_schedule(self, as_of_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns the full effective-dated regulatory fee schedule."""
        return settings.REGULATORY_FEE_SCHEDULE

    def estimate_spread_rate(self, is_uk: bool, instrument_type: str = "EQUITY", market_cap_tier: str = "LARGE") -> float:
        """
        Estimates bid-ask half-spread based on exchange, instrument type, and liquidity tier.
        """
        if instrument_type.upper() == "ETF":
            return 0.00025  # 2.5 bps half-spread (5 bps full spread) for major ETFs (e.g. CSPX, VUAG, SPY)
        if market_cap_tier == "MEGA":
            return 0.0003   # 3 bps half-spread
        elif is_uk:
            return 0.0006   # 6 bps half-spread (12 bps full spread) for UK FTSE large caps
        else:
            return 0.0004   # 4 bps half-spread (8 bps full spread) for US S&P 500 large caps

    def evaluate_ptm_levy_applicability(
        self,
        nominal_value: float,
        instrument_type: str = "EQUITY",
        issuer_jurisdiction: str = "UK",
        venue: str = "LSE_MAIN"
    ) -> Dict[str, Any]:
        """
        Evaluates Takeover Panel PTM Levy applicability per security & issuer rules:
        - Scope: Companies incorporated in UK, Channel Islands (JE, GG), or Isle of Man (IM)
                 whose shares trade on a UK regulated market (e.g. LSE) or UK MTF (e.g. AIM).
        - Exemptions: ETFs (collective investment schemes) and non-UK incorporated foreign issuers.
        - Threshold: Consideration > £10,000.
        - Rate: 150p (£1.50) flat per qualifying transaction leg (Buy & Sell).
        """
        is_etf = instrument_type.upper() == "ETF"
        is_qualifying_jurisdiction = issuer_jurisdiction.upper() in [
            "UK", "GB", "JE", "GG", "IM", "JERSEY", "GUERNSEY", "ISLE_OF_MAN"
        ]
        is_qualifying_venue = venue.upper() in ["LSE", "LSE_MAIN", "AIM", "AIM_MTF", "AQUIS", "AQSE"]

        if is_etf:
            return {
                "ptm_applicable": False,
                "ptm_levy_amount": 0.0,
                "reason": "Exempt: Collective investment scheme / ETF",
                "issuer_jurisdiction": issuer_jurisdiction,
                "qualifying_market_status": venue,
                "source": "Takeover Panel PTM Levy Rules (Exempt: ETFs)",
                "verified_date": "2026-09-01"
            }

        if not is_qualifying_jurisdiction or not is_qualifying_venue:
            return {
                "ptm_applicable": False,
                "ptm_levy_amount": 0.0,
                "reason": f"Exempt: Non-UK/CI/IoM jurisdiction ({issuer_jurisdiction}) or non-UK venue ({venue})",
                "issuer_jurisdiction": issuer_jurisdiction,
                "qualifying_market_status": venue,
                "source": "Takeover Panel PTM Levy Rules",
                "verified_date": "2026-09-01"
            }

        if nominal_value <= self.ptm_threshold_gbp:
            return {
                "ptm_applicable": True,
                "ptm_levy_amount": 0.0,
                "reason": f"Qualifying UK/MTF security, but consideration (£{nominal_value:,.2f}) <= £10,000 threshold",
                "issuer_jurisdiction": issuer_jurisdiction,
                "qualifying_market_status": venue,
                "source": "Takeover Panel PTM Levy Rules (£10k threshold)",
                "verified_date": "2026-09-01"
            }

        return {
            "ptm_applicable": True,
            "ptm_levy_amount": self.ptm_levy_amount_gbp,
            "reason": f"Qualifying UK/CI/IoM company on UK venue ({venue}) with consideration > £10,000 (150p flat levy applied)",
            "issuer_jurisdiction": issuer_jurisdiction,
            "qualifying_market_status": venue,
            "source": "Takeover Panel PTM Levy Schedule (150p rate)",
            "verified_date": "2026-09-01"
        }

    def calculate_trade_friction(
        self,
        nominal_value: float,
        is_buy: bool,
        is_uk: bool = True,
        is_foreign: bool = False,
        shares_count: float = 0.0,
        instrument_type: str = "EQUITY",
        exchange: str = "LSE",
        currency: str = "GBP",
        custom_spread_pct: Optional[float] = None,
        issuer_jurisdiction: str = "UK"
    ) -> Dict[str, float]:
        """
        Calculates all friction components for a single trade leg in GBP with strict instrument-level rules:
        1. UK SDRT (0.50%): Charged ONLY on BUY of qualifying UK main-market equities. Exempt on ETFs, AIM, and Sells.
        2. PTM Levy (£1.50): Charged on UK/CI/IoM qualifying equities on UK markets/MTFs (incl AIM) if consideration > £10k.
        3. FX Fee (0.15%): Charged on non-GBP transactions (T212 rate).
        4. SEC & FINRA Fees: Charged ONLY on SELL of US-listed securities ($20.60/$1m SEC, $0.000195/sh FINRA).
        5. Spread & Slippage: Half-spread + 10 bps execution slippage.
        """
        if nominal_value <= 0:
            return {
                "broker_fees": 0.0,
                "taxes": 0.0,
                "stamp_duty": 0.0,
                "ptm_levy": 0.0,
                "fx_cost": 0.0,
                "regulatory_fees": 0.0,
                "sec_fees": 0.0,
                "finra_fees": 0.0,
                "spread_cost": 0.0,
                "slippage_cost": 0.0,
                "total_friction": 0.0,
                "friction_pct": 0.0
            }

        # 1. Broker Commission (Trading212 zero commission)
        broker_fees = 0.0

        # 2. UK Stamp Duty Reserve Tax (SDRT 0.50%)
        # Rule: Only on UK Equity Buys (Exempt on ETFs, AIM, and all Sell orders)
        is_etf = instrument_type.upper() == "ETF"
        is_aim = instrument_type.upper() == "AIM" or exchange.upper() in ["AIM", "AIM_MTF"]
        stamp_duty = 0.0
        if is_uk and is_buy and not is_etf and not is_aim:
            stamp_duty = nominal_value * self.uk_stamp_duty_rate

        # 3. UK PTM Levy (£1.50 flat fee on qualifying trades > £10,000 per Takeover Panel rules)
        # Note: AIM is a UK MTF; UK-incorporated companies on AIM are subject to PTM Levy if consideration > £10,000.
        ptm_eval = self.evaluate_ptm_levy_applicability(
            nominal_value=nominal_value,
            instrument_type=instrument_type,
            issuer_jurisdiction=issuer_jurisdiction if is_uk else "US",
            venue=exchange
        )
        ptm_levy = ptm_eval["ptm_levy_amount"]

        # 4. Foreign Exchange Conversion Fee (0.15% / 15 bps)
        # Applied if trading currency is not GBP (e.g. USD, EUR) or is_foreign is True
        fx_cost = 0.0
        if is_foreign or currency.upper() != "GBP":
            fx_cost = nominal_value * self.fx_conversion_rate

        # 5. US Regulatory Charges (SEC Section 31 & FINRA TAF)
        # Rule: Applied on SELL orders of US equities/ETFs only
        sec_fees = 0.0
        finra_fees = 0.0
        regulatory_fees = 0.0
        if not is_uk and not is_buy:
            # SEC Section 31 Fee ($20.60 per $1m = 0.0000206 of USD consideration)
            sec_fees = nominal_value * self.us_sec_fee_rate
            # FINRA TAF ($0.000195/share up to $9.79 cap)
            if shares_count > 0:
                finra_fees = min(self.us_finra_taf_max, shares_count * self.us_finra_taf_rate)
            else:
                finra_fees = 0.02  # Minimal baseline
            regulatory_fees = sec_fees + finra_fees

        # 6. Bid-Ask Spread Friction
        if custom_spread_pct is not None:
            spread_half_rate = custom_spread_pct / 2.0
        else:
            spread_half_rate = self.estimate_spread_rate(is_uk=is_uk, instrument_type=instrument_type)
        spread_cost = nominal_value * spread_half_rate

        # 7. Slippage Cost (10 bps limit execution baseline)
        slippage_cost = nominal_value * self.slippage_rate

        total_taxes = stamp_duty + ptm_levy
        total_friction = broker_fees + total_taxes + fx_cost + regulatory_fees + spread_cost + slippage_cost
        friction_pct = (total_friction / nominal_value) * 100.0

        return {
            "broker_fees": round(broker_fees, 2),
            "taxes": round(total_taxes, 2),
            "stamp_duty": round(stamp_duty, 2),
            "ptm_levy": round(ptm_levy, 2),
            "fx_cost": round(fx_cost, 2),
            "regulatory_fees": round(regulatory_fees, 2),
            "sec_fees": round(sec_fees, 4),
            "finra_fees": round(finra_fees, 4),
            "spread_cost": round(spread_cost, 2),
            "slippage_cost": round(slippage_cost, 2),
            "total_friction": round(total_friction, 2),
            "friction_pct": round(friction_pct, 4)
        }

    def calculate_round_trip_friction(
        self,
        entry_value: float,
        exit_value: float,
        is_uk: bool,
        is_foreign: bool,
        shares_count: float = 0.0,
        instrument_type: str = "EQUITY",
        exchange: str = "LSE",
        currency: str = "GBP",
        custom_spread_pct: Optional[float] = None,
        issuer_jurisdiction: str = "UK"
    ) -> Dict[str, Any]:
        """
        Calculates complete round-trip (entry buy + exit sell) friction.
        """
        entry_friction = self.calculate_trade_friction(
            nominal_value=entry_value,
            is_buy=True,
            is_uk=is_uk,
            is_foreign=is_foreign,
            shares_count=shares_count,
            instrument_type=instrument_type,
            exchange=exchange,
            currency=currency,
            custom_spread_pct=custom_spread_pct,
            issuer_jurisdiction=issuer_jurisdiction
        )

        exit_friction = self.calculate_trade_friction(
            nominal_value=exit_value,
            is_buy=False,
            is_uk=is_uk,
            is_foreign=is_foreign,
            shares_count=shares_count,
            instrument_type=instrument_type,
            exchange=exchange,
            currency=currency,
            custom_spread_pct=custom_spread_pct,
            issuer_jurisdiction=issuer_jurisdiction
        )

        total_round_trip_cost = round(entry_friction["total_friction"] + exit_friction["total_friction"], 2)
        total_nominal = entry_value + exit_value
        round_trip_cost_pct = round((total_round_trip_cost / max(1.0, total_nominal)) * 100.0, 4)

        return {
            "entry_friction": entry_friction,
            "exit_friction": exit_friction,
            "total_round_trip_cost": total_round_trip_cost,
            "total_round_trip_cost_gbp": total_round_trip_cost,
            "round_trip_cost_pct": round_trip_cost_pct,
            "total_round_trip_pct": round_trip_cost_pct,
            "breakdown": {
                "broker_fees": round(entry_friction["broker_fees"] + exit_friction["broker_fees"], 2),
                "taxes_and_stamp_duty": round(entry_friction["taxes"] + exit_friction["taxes"], 2),
                "fx_conversion_fees": round(entry_friction["fx_cost"] + exit_friction["fx_cost"], 2),
                "us_regulatory_fees": round(entry_friction["regulatory_fees"] + exit_friction["regulatory_fees"], 2),
                "sec_fees": round(entry_friction["sec_fees"] + exit_friction["sec_fees"], 4),
                "finra_fees": round(entry_friction["finra_fees"] + exit_friction["finra_fees"], 4),
                "bid_ask_spread_cost": round(entry_friction["spread_cost"] + exit_friction["spread_cost"], 2),
                "spread_cost": round(entry_friction["spread_cost"] + exit_friction["spread_cost"], 2),
                "execution_slippage": round(entry_friction["slippage_cost"] + exit_friction["slippage_cost"], 2),
                "slippage_cost": round(entry_friction["slippage_cost"] + exit_friction["slippage_cost"], 2)
            }
        }

    def compute_net_realized_pnl(
        self,
        gross_entry_value: float,
        gross_exit_value: float,
        is_uk: bool = True,
        is_foreign: bool = False,
        shares_count: float = 0.0,
        instrument_type: str = "EQUITY",
        exchange: str = "LSE",
        currency: str = "GBP",
        actual_costs: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Calculates Net Realized P&L from gross values and complete fee breakdown.
        """
        gross_pnl = round(gross_exit_value - gross_entry_value, 2)
        gross_pnl_pct = round((gross_pnl / max(0.01, gross_entry_value)) * 100.0, 2)

        if actual_costs:
            total_costs = round(sum(actual_costs.values()), 2)
            breakdown = actual_costs
        else:
            rt = self.calculate_round_trip_friction(
                entry_value=gross_entry_value,
                exit_value=gross_exit_value,
                is_uk=is_uk,
                is_foreign=is_foreign,
                shares_count=shares_count,
                instrument_type=instrument_type,
                exchange=exchange,
                currency=currency
            )
            total_costs = rt["total_round_trip_cost"]
            breakdown = rt["breakdown"]

        net_pnl = round(gross_pnl - total_costs, 2)
        net_pnl_pct = round((net_pnl / max(0.01, gross_entry_value)) * 100.0, 2)

        cost_as_pct_of_gross_profit = 0.0
        if gross_pnl > 0:
            cost_as_pct_of_gross_profit = round((total_costs / gross_pnl) * 100.0, 2)
        elif gross_pnl < 0:
            cost_as_pct_of_gross_profit = round((total_costs / abs(gross_pnl)) * 100.0, 2)

        is_net_profitable = net_pnl > 0

        return {
            "gross_entry_value": round(gross_entry_value, 2),
            "gross_exit_value": round(gross_exit_value, 2),
            "gross_profit_loss": gross_pnl,
            "gross_profit_loss_pct": gross_pnl_pct,
            "total_transaction_costs": total_costs,
            "cost_breakdown": breakdown,
            "net_realized_pnl": net_pnl,
            "net_realized_pnl_pct": net_pnl_pct,
            "cost_as_pct_of_gross_profit": cost_as_pct_of_gross_profit,
            "is_net_profitable": is_net_profitable
        }

    def get_instrument_cost_profile(
        self,
        ticker: str,
        exchange: str,
        currency: str,
        instrument_type: str = "EQUITY",
        nominal_value: float = 2500.0
    ) -> Dict[str, Any]:
        """
        Generates comprehensive cost profile for a given instrument.
        """
        is_uk = (exchange.upper() == "LSE" or currency.upper() == "GBP" or ticker.endswith(".L") or ticker.endswith("l_EQ"))
        is_foreign = (currency.upper() != "GBP" or not is_uk)

        # 1. SDRT applicability
        is_etf = instrument_type.upper() == "ETF"
        is_aim = instrument_type.upper() == "AIM"
        if is_uk and not is_etf and not is_aim:
            sdrt_desc = "YES (0.50% Buy)"
            sdrt_rate = 0.0050
        elif is_etf:
            sdrt_desc = "EXEMPT (ETF Exemption s.49 FA 2014)"
            sdrt_rate = 0.0
        elif is_aim:
            sdrt_desc = "EXEMPT (AIM Exemption FA 2014)"
            sdrt_rate = 0.0
        else:
            sdrt_desc = "EXEMPT (Non-UK)"
            sdrt_rate = 0.0

        # 2. PTM applicability
        ptm_desc = "YES (£1.50 if > £10k)" if (is_uk and not is_etf) else "EXEMPT (£0.00)"

        # 3. FX applicability
        fx_desc = "YES (0.15% Each Way)" if is_foreign else "EXEMPT (0.00%)"

        # 4. SEC & FINRA applicability
        sec_desc = "YES (0.00206% Sell)" if (not is_uk) else "EXEMPT (0.00%)"
        finra_desc = "YES ($0.000195/sh Sell)" if (not is_uk) else "EXEMPT (0.00%)"

        # 5. Spread & Slippage
        half_spread = self.estimate_spread_rate(is_uk=is_uk, instrument_type=instrument_type)
        full_spread_bps = round(half_spread * 2.0 * 10000.0, 1)
        slippage_bps = round(self.slippage_rate * 10000.0, 1)

        # 6. Estimated Round-Trip Friction on £2,500 nominal
        rt = self.calculate_round_trip_friction(
            entry_value=nominal_value,
            exit_value=nominal_value,
            is_uk=is_uk,
            is_foreign=is_foreign,
            instrument_type=instrument_type,
            exchange=exchange,
            currency=currency
        )

        return {
            "ticker": ticker,
            "exchange": exchange,
            "trading_currency": currency,
            "instrument_type": instrument_type,
            "is_uk": is_uk,
            "is_foreign": is_foreign,
            "sdrt_applicable": sdrt_desc,
            "sdrt_rate_pct": sdrt_rate * 100.0,
            "ptm_applicable": ptm_desc,
            "fx_applicable": fx_desc,
            "sec_applicable": sec_desc,
            "finra_applicable": finra_desc,
            "expected_spread_bps": full_spread_bps,
            "expected_slippage_bps": slippage_bps,
            "estimated_round_trip_cost_gbp": rt["total_round_trip_cost"],
            "estimated_round_trip_cost_pct": round((rt["total_round_trip_cost"] / nominal_value) * 100.0, 2)
        }

    def evaluate_net_edge(
        self,
        entry_price: float,
        target_price: float,
        stop_loss_price: float,
        nominal_value: float = 2500.0,
        is_uk: bool = False,
        is_foreign: bool = True,
        custom_spread_pct: Optional[float] = None,
        is_foreign_currency: Optional[bool] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Evaluates net edge and reward/risk ratio after friction.
        """
        if is_foreign_currency is not None:
            is_foreign = is_foreign_currency
        rt = self.calculate_round_trip_friction(
            entry_value=nominal_value,
            exit_value=nominal_value * (target_price / entry_price),
            is_uk=is_uk,
            is_foreign=is_foreign,
            custom_spread_pct=custom_spread_pct
        )
        total_friction = rt["total_round_trip_cost"]
        gross_profit = nominal_value * ((target_price - entry_price) / entry_price)
        gross_loss = nominal_value * ((entry_price - stop_loss_price) / entry_price)
        net_profit = gross_profit - total_friction
        net_loss = gross_loss + total_friction
        net_rr = net_profit / max(0.01, net_loss)
        cost_ratio_pct = (total_friction / max(0.01, gross_profit)) * 100.0
        
        gross_rr = (target_price - entry_price) / max(0.0001, (entry_price - stop_loss_price))
        approved = (net_rr >= 2.0 and cost_ratio_pct <= 30.0 and gross_rr >= 2.95)
        return approved, {
            "approved": approved,
            "gross_reward_risk": round(gross_rr, 2),
            "net_reward_risk": round(net_rr, 2),
            "net_reward_risk_ratio": round(net_rr, 2),
            "cost_to_profit_ratio_pct": round(cost_ratio_pct, 2),
            "total_friction_gbp": total_friction,
            "net_expected_profit_gbp": round(net_profit, 2)
        }


cost_model = InstitutionalCostModel()
SpreadAwareCostModel = InstitutionalCostModel
