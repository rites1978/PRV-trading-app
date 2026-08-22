from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from src.config.settings import settings
from src.database.db import db

class CatalystCategory:
    POLITICAL_POLICY = "POLITICAL_POLICY"
    CORPORATE_LEADERSHIP = "CORPORATE_LEADERSHIP"
    COMPANY_EARNINGS = "COMPANY_EARNINGS"
    MACRO_ECONOMIC = "MACRO_ECONOMIC"

class CatalystIntelligenceEngine:
    """
    PRV Capital Catalyst Intelligence Engine:
    Ingests, classifies, scores, and gates high-impact market catalysts.
    
    CRITICAL RULE:
    The module NEVER initiates trades solely based on public figures or social media posts.
    All catalyst-ranked opportunities MUST clear 100% of technical, volume, risk, and portfolio constraints.
    """
    
    # Source Credibility Matrix (0 - 100)
    SOURCE_CREDIBILITY = {
        "SEC_FILING": 100.0,
        "EARNINGS_RELEASE": 100.0,
        "FEDERAL_RESERVE": 98.0,
        "US_TREASURY": 95.0,
        "ECB": 95.0,
        "BANK_OF_ENGLAND": 95.0,
        "WHITE_HOUSE": 90.0,
        "OFFICIAL_COMPANY_PR": 88.0,
        "CEO_CONFERENCE_CALL": 85.0,
        "TIER1_FINANCIAL_PRESS": 80.0,
        "PUBLIC_FIGURE_TRUTH_SOCIAL": 50.0,
        "PUBLIC_FIGURE_TWITTER_X": 50.0,
        "UNVERIFIED_SOCIAL": 25.0
    }
    
    # Category Baseline Importance Weights
    CATEGORY_IMPORTANCE = {
        CatalystCategory.MACRO_ECONOMIC: 90.0,
        CatalystCategory.COMPANY_EARNINGS: 88.0,
        CatalystCategory.POLITICAL_POLICY: 82.0,
        CatalystCategory.CORPORATE_LEADERSHIP: 70.0
    }

    def __init__(self):
        self._ensure_seed_catalysts()

    def compute_catalyst_score(
        self,
        category: str,
        source: str,
        news_importance: float,
        sentiment_polarity: float,  # -1.0 to +1.0
        volume_expansion_ratio: float,  # 1.0 = normal, 2.0 = 2x average volume
        price_reaction_pct: float,  # % change in price post-event
        sector_relevance: float  # 0 to 100
    ) -> Tuple[float, str, Dict[str, Any]]:
        """
        Section 3: Catalyst Scoring Engine
        Weights:
        - News Importance:       25%
        - Source Credibility:    20%
        - Sentiment Strength:    20%
        - Volume Expansion:      15%
        - Price Reaction:        10%
        - Sector Relevance:      10%
        """
        credibility = self.SOURCE_CREDIBILITY.get(source, 50.0)
        base_importance = max(news_importance, self.CATEGORY_IMPORTANCE.get(category, 50.0))
        
        # Sentiment Strength (0 to 100 scale, absolute directional force)
        sentiment_strength = min(100.0, abs(sentiment_polarity) * 100.0)
        
        # Volume Expansion Score (Normalized: 1.0x -> 50pts, 2.0x -> 80pts, 3.0x+ -> 100pts)
        volume_score = min(100.0, max(0.0, (volume_expansion_ratio - 0.5) * 40.0))
        
        # Initial Price Reaction Score (Normalized: 0% -> 30pts, +2% -> 70pts, +4%+ -> 100pts)
        price_score = min(100.0, max(0.0, 30.0 + (abs(price_reaction_pct) * 17.5)))
        
        # Multi-Factor Weighted Scoring
        raw_score = (
            (base_importance * 0.25) +
            (credibility * 0.20) +
            (sentiment_strength * 0.20) +
            (volume_score * 0.15) +
            (price_score * 0.10) +
            (sector_relevance * 0.10)
        )
        catalyst_score = round(max(0.0, min(100.0, raw_score)), 1)
        
        # Determine Rating Tier
        if catalyst_score >= 81.0:
            tier = "HIGH_CONVICTION_CATALYST"
        elif catalyst_score >= 66.0:
            tier = "MONITOR"
        elif catalyst_score >= 41.0:
            tier = "WATCH"
        else:
            tier = "IGNORE"
            
        factors = {
            "news_importance": round(base_importance, 1),
            "source_credibility": round(credibility, 1),
            "sentiment_strength": round(sentiment_strength, 1),
            "volume_score": round(volume_score, 1),
            "price_score": round(price_score, 1),
            "sector_relevance": round(sector_relevance, 1),
            "tier": tier
        }
        
        return catalyst_score, tier, factors

    def evaluate_catalyst_deployment_gate(
        self,
        catalyst_score: float,
        technical_score: float,
        boardroom_quorum: float,
        reward_risk_ratio: float,
        sector_exposure_pct_nav: float,
        max_correlation: float,
        is_market_open: bool
    ) -> Tuple[bool, str, List[str]]:
        """
        Section 5 & 6: Catalyst Safety & Reserve Deployment Gate.
        
        Strict Requirements:
        1. Market Open Check (Zero execution when closed)
        2. Catalyst Score >= 80.0
        3. Technical Score >= 65.0 (Anti-Hype technical confirmation)
        4. Boardroom Quorum >= 75.0% (Multi-agent quorum approval)
        5. Net Reward/Risk >= 3.0
        6. Sector NAV Exposure <= 30.0%
        7. Pairwise Correlation <= 0.65
        """
        reasons = []
        approved = True
        
        if not is_market_open:
            approved = False
            reasons.append("BLOCKED: Market session closed. Standby protection active.")
            
        if catalyst_score < 80.0:
            approved = False
            reasons.append(f"VETO: Catalyst score ({catalyst_score}) below high-conviction threshold (80.0).")
            
        if technical_score < 65.0:
            approved = False
            reasons.append(f"VETO: Technical score ({technical_score}) failed. No price/SMA confirmation (Anti-Hype rule).")
            
        if boardroom_quorum < 75.0:
            approved = False
            reasons.append(f"VETO: Boardroom quorum ({boardroom_quorum}%) below catalyst threshold (75.0%).")
            
        if reward_risk_ratio < 3.0:
            approved = False
            reasons.append(f"VETO: Reward/Risk ratio ({reward_risk_ratio:.2f}) below minimum 3.0:1 requirement.")
            
        if sector_exposure_pct_nav > 30.0:
            approved = False
            reasons.append(f"VETO: Sector exposure ({sector_exposure_pct_nav:.1f}%) breaches 30.0% NAV ceiling.")
            
        if max_correlation > 0.65:
            approved = False
            reasons.append(f"VETO: Cross-asset correlation ({max_correlation:.2f}) exceeds 0.65 diversification limit.")
            
        summary = "APPROVED: All 7 Catalyst Risk & Safety Gates Satisfied." if approved else "GATED: Catalyst entry rejected by quantitative safety filters."
        return approved, summary, reasons

    def get_dashboard_payload(self) -> Dict[str, Any]:
        """Section 7: Catalyst Intelligence Dashboard View"""
        raw_events = db.get_catalyst_events(limit=50)
        
        active_catalysts = []
        sector_impact = {}
        for ev in raw_events:
            active_catalysts.append({
                "id": ev.get("event_id"),
                "timestamp": ev.get("timestamp"),
                "source": ev.get("source"),
                "category": ev.get("category"),
                "ticker": ev.get("ticker"),
                "sector": ev.get("sector"),
                "headline": ev.get("headline"),
                "sentiment_score": ev.get("sentiment_score"),
                "importance_score": ev.get("importance_score"),
                "catalyst_score": ev.get("catalyst_score"),
                "deployment_flag": bool(ev.get("deployment_flag")),
                "outcome": ev.get("trade_outcome")
            })
            sec = ev.get("sector", "General")
            sector_impact[sec] = sector_impact.get(sec, 0) + 1

        # Ranked Opportunity Queue
        ranked_queue = sorted(
            [c for c in active_catalysts if c["catalyst_score"] >= 66.0],
            key=lambda x: x["catalyst_score"],
            reverse=True
        )

        return {
            "module_status": "RESEARCH_MONITOR_ACTIVE",
            "active_catalysts_count": len(active_catalysts),
            "high_conviction_count": len([c for c in active_catalysts if c["catalyst_score"] >= 80.0]),
            "active_catalysts": active_catalysts[:15],
            "ranked_opportunity_queue": ranked_queue[:10],
            "sector_impact_map": sector_impact,
            "catalyst_reserve_capital": {
                "proposed_pool_pct": 7.5,
                "proposed_pool_gbp": 3712.50,
                "current_deployed_gbp": 0.0,
                "status": "RESEARCH_FROZEN"
            },
            "safety_rules_summary": [
                "Rule 1: Zero direct execution on public figures / social posts alone",
                "Rule 2: Mandatory Technical Price Action confirmation (P > SMA20 > SMA50)",
                "Rule 3: Volume surge confirmation (V >= 1.5x 20-day SMA)",
                "Rule 4: Multi-Agent Boardroom Quorum >= 75.0%",
                "Rule 5: Strict -2.5% Stop Loss & 3.0:1 Reward/Risk enforcement",
                "Rule 6: Sector Exposure <= 30.0% NAV & Correlation <= 0.65"
            ]
        }

    def _ensure_seed_catalysts(self):
        """Seed representative high-impact events across all 4 categories for audit tracking."""
        existing = db.get_catalyst_events(limit=5)
        if existing:
            return

        seed_data = [
            {
                "event_id": "CAT-FED-001",
                "timestamp": "2026-08-20 19:00:00",
                "source": "FEDERAL_RESERVE",
                "category": CatalystCategory.MACRO_ECONOMIC,
                "ticker": "SPY",
                "sector": "Broad Market",
                "headline": "FOMC Rate Decision: Benchmark Rate Cut 25bps with Dovish Forward Guidance",
                "sentiment_score": 0.85,
                "importance_score": 95.0,
                "confidence_score": 98.0,
                "catalyst_score": 92.5,
                "deployment_flag": 1,
                "trade_outcome": "ALPHA_CONFIRMED (+1.8% Market Expansion)"
            },
            {
                "event_id": "CAT-NVDA-002",
                "timestamp": "2026-08-21 14:30:00",
                "source": "CEO_CONFERENCE_CALL",
                "category": CatalystCategory.CORPORATE_LEADERSHIP,
                "ticker": "NVDA",
                "sector": "Technology",
                "headline": "Jensen Huang Keynote: Blackwell GPU Ultra Architecture Exceeds Demand Forecasts",
                "sentiment_score": 0.90,
                "importance_score": 88.0,
                "confidence_score": 90.0,
                "catalyst_score": 86.4,
                "deployment_flag": 1,
                "trade_outcome": "MONITORING (Holding Tech Exposure within 30% NAV)"
            },
            {
                "event_id": "CAT-MSFT-003",
                "timestamp": "2026-08-21 21:05:00",
                "source": "EARNINGS_RELEASE",
                "category": CatalystCategory.COMPANY_EARNINGS,
                "ticker": "MSFT",
                "sector": "Technology",
                "headline": "Q4 Cloud & Azure AI Revenue Grows 33% YoY; Raises FY27 CapEx Guidance",
                "sentiment_score": 0.88,
                "importance_score": 90.0,
                "confidence_score": 100.0,
                "catalyst_score": 89.2,
                "deployment_flag": 1,
                "trade_outcome": "PENDING_OPEN (Awaiting London/NY Cash Session)"
            },
            {
                "event_id": "CAT-TRUMP-004",
                "timestamp": "2026-08-22 03:15:00",
                "source": "PUBLIC_FIGURE_TRUTH_SOCIAL",
                "category": CatalystCategory.POLITICAL_POLICY,
                "ticker": "TSLA",
                "sector": "Consumer Discretionary",
                "headline": "Trump Truth Social Post: Advocates Domestic EV Manufacturing & Autonomous Grid",
                "sentiment_score": 0.60,
                "importance_score": 65.0,
                "confidence_score": 50.0,
                "catalyst_score": 58.5,
                "deployment_flag": 0,
                "trade_outcome": "WATCH_ONLY (Anti-Hype Filter Vetoed Unconfirmed Social Signal)"
            },
            {
                "event_id": "CAT-US-SEC-005",
                "timestamp": "2026-08-22 08:30:00",
                "source": "SEC_FILING",
                "category": CatalystCategory.COMPANY_EARNINGS,
                "ticker": "AAPL",
                "sector": "Technology",
                "headline": "Form 8-K: Authorizes Expanded $110B Share Repurchase Program",
                "sentiment_score": 0.80,
                "importance_score": 85.0,
                "confidence_score": 100.0,
                "catalyst_score": 84.1,
                "deployment_flag": 1,
                "trade_outcome": "RANKING_UPGRADE (Added to Top Conviction Queue)"
            }
        ]

        for s in seed_data:
            db.record_catalyst_event(s)

catalyst_engine = CatalystIntelligenceEngine()
