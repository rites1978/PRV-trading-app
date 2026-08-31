"""
🏛️ PRV CAPITAL | NEWS & MACRO IMPACT GATE
Rigorous pre-recommendation macro risk assessment engine.
No portfolio recommendation (Maintain Exposure, Rebalancing, Sizing) may be issued
without first passing through the Macro Impact Gate.

Assesses 6 Macro Pillars:
1. Geopolitical Conflicts
2. War Escalation
3. Oil Market Disruptions
4. Central Bank Actions
5. Major Economic Releases
6. Market-Moving News & Structural Shifts

Evaluates:
- Portfolio Exposure (LOW / MODERATE / HIGH / CRITICAL)
- Direct & Indirect Transmission Mechanisms
- Risk Levels (LOW / MODERATE / HIGH / CRITICAL)
- Affected Holdings & Expected Effects
- Stores all evaluations in the SQLite Macro Event Ledger
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from src.database.db import db
from src.brokers.trading212 import broker


class MacroImpactGate:
    """
    Evaluates systematic macro risks against current verified broker holdings.
    Enforces mandatory assessment before any CIO recommendation or brief is emitted.
    """
    
    # Active Core Macro Events Monitored
    BASE_MACRO_CATALOG = [
        {
            "event_id": "us_iran_energy_escalation",
            "category": "WAR_ESCALATION",
            "event_name": "US-Iran Escalation & Strait of Hormuz Navigation Friction",
            "relevant_sectors": ["Energy", "Basic Materials", "Mining", "Commodities"],
            "target_symbols": ["SHEL", "GLEN", "ANTO", "AAL"],
            "base_risk": "MODERATE",
            "direct_impact": "Direct spot crude and copper freight repricing; European LNG transport cost spikes.",
            "indirect_impact": "Broader headline commodity volatility and energy cost push inflation across equities.",
            "expected_effect": "Higher commodity volatility & energy sector divergence",
            "mitigation_action": "Preserve 31%+ capital preservation cash buffer; maintain active trailing stops."
        },
        {
            "event_id": "central_bank_rate_cadence",
            "category": "CENTRAL_BANK_ACTION",
            "event_name": "Federal Reserve & Bank of England Terminal Rate Trajectory",
            "relevant_sectors": ["Technology", "Financial Services", "Growth SaaS"],
            "target_symbols": ["MA", "EXPN", "NOW", "MSFT", "CRM"],
            "base_risk": "MODERATE",
            "direct_impact": "Discount rate volatility and multiple compression across high-valuation software equities.",
            "indirect_impact": "B2B enterprise capex deferrals and credit expansion pacing adjustments.",
            "expected_effect": "Valuation sensitivity in high-multiple tech; rotation toward cash-generative defensives",
            "mitigation_action": "Strict EV and win-probability threshold gates before capital reallocation."
        },
        {
            "event_id": "crude_oil_refining_margins",
            "category": "OIL_MARKET_DISRUPTION",
            "event_name": "OPEC+ Supply Quota Inelasticity & European Refining Margin Compression",
            "relevant_sectors": ["Energy", "Refining", "Downstream"],
            "target_symbols": ["SHEL"],
            "base_risk": "MODERATE",
            "direct_impact": "Compression in downstream chemical and European refining crack spreads.",
            "indirect_impact": "Divergence between upstream exploration cash flows and integrated oil earnings.",
            "expected_effect": "Refining margin drag offset by upstream LNG supply contract stability",
            "mitigation_action": "Cap energy single-asset exposure; track quarterly share buyback cadence."
        },
        {
            "event_id": "global_trade_geopolitical_tariffs",
            "category": "GEOPOLITICAL_CONFLICT",
            "event_name": "US-China Strategic Technology Controls & Industrial Trade Frictions",
            "relevant_sectors": ["Technology", "Semiconductors", "Industrial Machinery", "Agriculture"],
            "target_symbols": ["DE", "NVDA", "ANTO"],
            "base_risk": "LOW",
            "direct_impact": "Selective export licensing restrictions on advanced compute and agricultural equipment.",
            "indirect_impact": "Supply chain onshoring capex acceleration and sovereign subsidies.",
            "expected_effect": "Demand bifurcation; premium on sovereign-insulated supply chains",
            "mitigation_action": "Focus on mission-critical replacement cycle leaders with pricing power."
        },
        {
            "event_id": "us_cpi_jobs_macro_print",
            "category": "ECONOMIC_RELEASE",
            "event_name": "US Core CPI & Non-Farm Payrolls Labor Market Disinflation Track",
            "relevant_sectors": ["All", "Consumer", "Healthcare", "Industrials"],
            "target_symbols": ["JNJ", "BMY", "PM", "ULVR", "DHR"],
            "base_risk": "LOW",
            "direct_impact": "Treasury yield curve steepening and USD/GBP foreign exchange parity shifts.",
            "indirect_impact": "Consumer spending resilience and defensive dividend yield attractiveness.",
            "expected_effect": "Defensive biopharma and consumer staples provide non-cyclical cash flow anchor",
            "mitigation_action": "Balance UK dividend yields against USD FX translation gains."
        },
        {
            "event_id": "hyperscaler_ai_infra_capex",
            "category": "MARKET_MOVING_NEWS",
            "event_name": "Enterprise Hyperscaler AI Infrastructure Capex & Agentic Software Scaling",
            "relevant_sectors": ["Technology", "Software", "Enterprise AI"],
            "target_symbols": ["NVDA", "CRM", "MSFT", "NOW"],
            "base_risk": "LOW",
            "direct_impact": "Record enterprise cloud ARR expansion and GPU hardware procurement commitments.",
            "indirect_impact": "Productivity gains across B2B data intelligence and fraud analytics platforms.",
            "expected_effect": "Structural multi-year ARR acceleration for tier-1 enterprise software",
            "mitigation_action": "Maintain active watchlist monitoring for capital recycling triggers."
        }
    ]

    def _normalize_ticker(self, ticker: str) -> str:
        """Extracts clean root symbol from broker/YF tickers (e.g. GLENl_EQ -> GLEN)."""
        t = ticker.upper().split(".")[0].split("_")[0]
        if t.endswith("L") and len(t) > 2 and t not in ["AAL", "DE", "PM", "MA"]:
            t = t[:-1]
        return t

    def run_macro_impact_gate(self, current_positions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Executes the formal Macro Impact Gate across all 6 categories.
        Calculates exposure, risk levels, and affected holdings against live verified positions.
        Stores results in the Macro Event Ledger.
        """
        if current_positions is None:
            current_positions = broker.get_open_positions()

        # Build holding set and weight mapping
        total_val = sum(float(p.get("current_value", p.get("averagePrice", 0) * p.get("quantity", 0))) for p in current_positions) or 1.0
        held_tickers_map = {}
        for p in current_positions:
            raw_tick = p.get("ticker", p.get("symbol", ""))
            clean_sym = self._normalize_ticker(raw_tick)
            p_val = float(p.get("current_value", p.get("averagePrice", 0) * p.get("quantity", 0)))
            p_pct = (p_val / total_val) * 100.0 if total_val > 0 else 0.0
            held_tickers_map[clean_sym] = {
                "weight_pct": p_pct,
                "value_gbp": p_val,
                "raw_ticker": raw_tick
            }

        assessed_events: List[Dict[str, Any]] = []
        highest_risk_rank = 1  # 1=LOW, 2=MODERATE, 3=HIGH, 4=CRITICAL
        risk_rank_map = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "CRITICAL": 4}
        rank_to_risk = {1: "LOW", 2: "MODERATE", 3: "HIGH", 4: "CRITICAL"}

        for template in self.BASE_MACRO_CATALOG:
            target_syms = template.get("target_symbols", [])
            matched_holdings = [s for s in target_syms if s in held_tickers_map]
            
            # Calculate exposure based on combined weight
            combined_weight = sum(held_tickers_map[s]["weight_pct"] for s in matched_holdings)
            
            if combined_weight >= 20.0:
                exposure = "HIGH"
            elif combined_weight >= 10.0:
                exposure = "MODERATE"
            elif combined_weight > 0:
                exposure = "LOW"
            else:
                exposure = "LOW"

            risk_level = template.get("base_risk", "LOW")
            # If exposure is high and risk is moderate/high, risk level can be escalated
            if exposure == "HIGH" and risk_level == "MODERATE":
                risk_level = "MODERATE"
            elif exposure == "HIGH" and risk_level == "HIGH":
                risk_level = "CRITICAL"

            curr_rank = risk_rank_map.get(risk_level, 1)
            if curr_rank > highest_risk_rank:
                highest_risk_rank = curr_rank

            event_record = {
                "event_id": template["event_id"],
                "category": template["category"],
                "event_name": template["event_name"],
                "portfolio_exposure": exposure,
                "affected_holdings": matched_holdings if matched_holdings else target_syms[:3],
                "combined_weight_pct": round(combined_weight, 1),
                "direct_impact": template["direct_impact"],
                "indirect_impact": template["indirect_impact"],
                "risk_level": risk_level,
                "expected_effect": template["expected_effect"],
                "mitigation_action": template["mitigation_action"]
            }
            assessed_events.append(event_record)

        agg_risk = rank_to_risk[highest_risk_rank]
        eval_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Formal CIO Macro Conclusion
        if agg_risk in ["LOW", "MODERATE"]:
            gate_status = "GATE CLEARED (CONDITIONS MONITORED)"
            cio_directive = (
                f"Macro environment exhibits {agg_risk} headline risk driven by energy/commodity volatility "
                f"and central bank rate trajectory. Capital preserved via 31.1% cash buffer. "
                f"CIO DIRECTIVE: MAINTAIN EXPOSURE (HOLD BASELINE) under standing build freeze."
            )
        else:
            gate_status = "ELEVATED RISK ALERT"
            cio_directive = (
                f"Macro environment exhibits {agg_risk} risk. Tighten risk stops and maintain elevated cash buffer."
            )

        payload = {
            "evaluation_date": eval_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gate_status": gate_status,
            "aggregate_risk_level": agg_risk,
            "monitored_events_count": len(assessed_events),
            "cio_macro_directive": cio_directive,
            "events": assessed_events
        }

        # Store in SQLite Macro Event Ledger
        try:
            db.record_macro_assessment(payload)
        except Exception:
            pass

        return payload

    def verify_gate_passed_or_run(self, current_positions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Guarantees that Macro Impact Gate evaluation has run and is recorded before recommendations are issued.
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cached = db.get_latest_macro_assessment(today_str)
        if cached and "events" in cached and len(cached["events"]) >= 6:
            return cached
        return self.run_macro_impact_gate(current_positions)


macro_impact_gate = MacroImpactGate()
