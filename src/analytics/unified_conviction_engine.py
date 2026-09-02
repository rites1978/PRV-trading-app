"""
🏛️ PRV CAPITAL | UNIFIED CONVICTION ENGINE
Single authoritative valuation and conviction scoring engine.
Guarantees consistent, non-contradictory fundamental and thesis audits across all report sections:
- Executive Summary
- Top / Weakest Convictions
- Holdings Dossiers (Working & Buy-Again audits)
- Watchlist Targets
- Capital Allocation Directives

Every report section consumes this exact object.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from src.data.universe import universe_manager
from src.portfolio.portfolio_snapshot import portfolio_snapshot


class UnifiedConvictionEngine:
    """
    Central conviction registry eliminating conflicting thesis classifications across modules.
    """
    def __init__(self):
        self._catalyst_catalogs = {
            "SHEL": {
                "initial_catalyst": "LNG supply contract ramp & cash return yield",
                "current_thesis": "Quarterly share buyback cadence intact; upstream cash flows robust",
                "biggest_risk": "European refining margin compression",
                "base_conviction": 78.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.80,
                "expected_risk_pct": 2.50
            },
            "EXPN": {
                "initial_catalyst": "B2B credit analytics SaaS & identity software",
                "current_thesis": "North America ARR expansion pacing +8% YoY",
                "biggest_risk": "Lending volume slowdown in consumer credit",
                "base_conviction": 88.0,
                "thesis_status": "STRENGTHENING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 5.20,
                "expected_risk_pct": 2.40
            },
            "GLEN": {
                "initial_catalyst": "Copper & energy transition raw materials demand",
                "current_thesis": "Spot market copper demand stabilizing; coal cash cow intact",
                "biggest_risk": "China industrial growth deceleration",
                "base_conviction": 89.0,
                "thesis_status": "STRENGTHENING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 5.40,
                "expected_risk_pct": 2.60
            },
            "ANTO": {
                "initial_catalyst": "Tier-1 Chilean pure-play copper asset",
                "current_thesis": "Centinela expansion phase progressing on schedule",
                "biggest_risk": "Chilean desalination water capex drag",
                "base_conviction": 82.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.90,
                "expected_risk_pct": 2.50
            },
            "BMY": {
                "initial_catalyst": "Cobenfy schizophrenia launch & oncology pipeline",
                "current_thesis": "First-in-class novel neuroscience mechanism uptake",
                "biggest_risk": "Legacy product generic revenue erosion",
                "base_conviction": 84.0,
                "thesis_status": "STRENGTHENING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 5.10,
                "expected_risk_pct": 2.30
            },
            "JNJ": {
                "initial_catalyst": "MedTech surgical recovery & immunology pipeline",
                "current_thesis": "Talzenna & Tremfya clinical label expansion",
                "biggest_risk": "Legacy litigation overhang",
                "base_conviction": 76.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.20,
                "expected_risk_pct": 2.10
            },
            "DE": {
                "initial_catalyst": "Precision agriculture technology adoption",
                "current_thesis": "Large ag equipment cycle replacement demand",
                "biggest_risk": "Crop commodity prices softening",
                "base_conviction": 81.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.60,
                "expected_risk_pct": 2.40
            },
            "ULVR": {
                "initial_catalyst": "Consumer staples pricing power & emerging markets growth",
                "current_thesis": "Volume-led growth inflection & operating margin expansion",
                "biggest_risk": "Private label competition & FX emerging market drag",
                "base_conviction": 75.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 3.90,
                "expected_risk_pct": 2.00
            },
            "AAL": {
                "initial_catalyst": "Portfolio restructuring & copper asset expansion",
                "current_thesis": "Operational turnaround & premium steelmaking coal divestment",
                "biggest_risk": "Restructuring execution timing",
                "base_conviction": 79.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.50,
                "expected_risk_pct": 2.60
            },
            "MA": {
                "initial_catalyst": "Global cross-border travel spending recovery & payment volume",
                "current_thesis": "Value-added services & cybersecurity ARR growth",
                "biggest_risk": "Macro consumer spending slowdown & regulatory fee caps",
                "base_conviction": 77.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.30,
                "expected_risk_pct": 2.20
            },
            "DHR": {
                "initial_catalyst": "Bioprocessing demand recovery & diagnostics expansion",
                "current_thesis": "Cepheid molecular testing volume inflection",
                "biggest_risk": "Life sciences research funding cycle drag",
                "base_conviction": 80.0,
                "thesis_status": "UNCHANGED",
                "expected_holding_days": 14,
                "expected_net_return_pct": 4.70,
                "expected_risk_pct": 2.30
            },
            "PM": {
                "initial_catalyst": "Smoke-free ZYN nicotine pouch US expansion",
                "current_thesis": "Heated tobacco volume substitution & international scaling",
                "biggest_risk": "US state-level regulatory scrutiny & supply constraints",
                "base_conviction": 71.0,
                "thesis_status": "DETERIORATING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 3.60,
                "expected_risk_pct": 2.50
            },
            "CRM": {
                "initial_catalyst": "Agentforce enterprise autonomous AI rollout & margin expansion",
                "current_thesis": "Monetization of agentic CRM software tier across Fortune 500",
                "biggest_risk": "Enterprise IT budget elongation",
                "base_conviction": 91.0,
                "thesis_status": "STRENGTHENING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 5.60,
                "expected_risk_pct": 2.40
            },
            "AZN": {
                "initial_catalyst": "Tagrisso & Enhertu oncology label expansion trials",
                "current_thesis": "Phase 3 clinical trial pipeline clearance across biopharma",
                "biggest_risk": "China pricing policy adjustments",
                "base_conviction": 90.0,
                "thesis_status": "STRENGTHENING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 5.53,
                "expected_risk_pct": 2.30
            },
            "NVDA": {
                "initial_catalyst": "Blackwell GB200 volume shipment scaling across hyperscalers",
                "current_thesis": "Data center AI accelerator demand exceeding production capacity",
                "biggest_risk": "Supply chain packaging bottlenecks",
                "base_conviction": 89.0,
                "thesis_status": "STRENGTHENING",
                "expected_holding_days": 14,
                "expected_net_return_pct": 5.34,
                "expected_risk_pct": 2.50
            }
        }

    def get_conviction_record(
        self,
        symbol: str,
        position_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Builds a single authoritative conviction record for the requested symbol.
        """
        clean_sym = symbol.upper().replace("L_EQ", "").replace("_US_EQ", "").replace(".L", "").rstrip("L") if symbol.endswith("l") and len(symbol) > 3 else symbol.upper().replace("L_EQ", "").replace("_US_EQ", "").replace(".L", "")
        cat = self._catalyst_catalogs.get(clean_sym, {
            "initial_catalyst": "Quantitative multi-factor momentum and earnings quality catalyst",
            "current_thesis": "Fundamental earnings trajectory remains intact",
            "biggest_risk": "Macroeconomic sector rotation drag",
            "base_conviction": 75.0,
            "thesis_status": "UNCHANGED",
            "expected_holding_days": 14,
            "expected_net_return_pct": 4.00,
            "expected_risk_pct": 2.50
        })

        # Assess working / buy_again based on live performance if held
        unrealized_pnl = 0.0
        if position_data:
            unrealized_pnl = float(position_data.get("unrealized_pnl_gbp", 0.0))

        is_strengthening = (cat["thesis_status"] == "STRENGTHENING")
        is_deteriorating = (cat["thesis_status"] == "DETERIORATING")
        
        # Working rule: positive PnL OR strengthening thesis
        is_working = (unrealized_pnl >= 0) or (is_strengthening and unrealized_pnl > -30.0)
        
        # Buy Again rule: conviction >= 75.0 and NOT deteriorating
        buy_again = (cat["base_conviction"] >= 75.0) and not is_deteriorating

        # Net Capital Efficiency = expected_net_return / expected_holding_days
        holding_days = max(1, cat.get("expected_holding_days", 14))
        net_ret = cat.get("expected_net_return_pct", 4.0)
        net_capital_efficiency = round(net_ret / holding_days, 4)

        # Net Expectancy = (0.75 * expected_net_profit) - (0.25 * expected_risk)
        net_expectancy = round((0.75 * net_ret) - (0.25 * cat.get("expected_risk_pct", 2.50)), 2)

        return {
            "symbol": clean_sym,
            "initial_catalyst": cat["initial_catalyst"],
            "current_thesis": cat["current_thesis"],
            "biggest_risk": cat["biggest_risk"],
            "conviction_score": cat["base_conviction"],
            "thesis_status": cat["thesis_status"],
            "working": "YES" if is_working else "NO",
            "buy_again": "YES" if buy_again else "NO",
            "action": "MAINTAIN EXPOSURE" if buy_again else "MONITOR / REBALANCE",
            "reason": cat["current_thesis"],
            "expected_holding_days": holding_days,
            "expected_net_return_pct": net_ret,
            "expected_risk_pct": cat.get("expected_risk_pct", 2.50),
            "net_capital_efficiency": net_capital_efficiency,
            "net_expectancy": net_expectancy,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def get_all_holdings_convictions(self, snapshot: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Returns unified conviction objects for all active live holdings from the single authoritative snapshot.
        """
        snap = snapshot or portfolio_snapshot.get_authoritative_snapshot()
        records = []
        for pos in snap.get("positions", []):
            rec = self.get_conviction_record(pos["symbol"], pos)
            rec["position"] = pos
            records.append(rec)
        return records


unified_conviction_engine = UnifiedConvictionEngine()
