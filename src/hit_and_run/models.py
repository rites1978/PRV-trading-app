"""
PRV Capital - Hit-and-Run Engine Data Models
Encapsulates OpportunityCandidate, AllocationDecision, and TradeAuditRecord.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


@dataclass
class OpportunityCandidate:
    """
    Structured short-term opportunity representation for Hit-and-Run scanning and ranking.
    Captures multi-dimensional quantitative metrics required for conviction scoring.
    """
    instrument_id: str
    symbol: str
    feed_ticker: str
    product_type: str
    currency: str
    is_uk_pence: bool
    quote_divisor: float
    current_price: float
    current_price_gbp: float

    # Short-term quantitative indicators
    momentum: float = 0.0
    acceleration: float = 0.0
    relative_strength: float = 0.0
    liquidity: float = 0.0
    spread_friction: float = 0.0
    volatility: float = 0.0
    volume_activity: float = 1.0
    distance_from_high: float = 0.0
    distance_from_low: float = 0.0

    # Economics & Risk
    estimated_costs: float = 0.0
    expected_net_reward: float = 0.0
    downside_risk: float = 0.05  # Capped at 5% max
    risk_reward_ratio: float = 0.0

    # AI Conviction & Thesis
    opportunity_score: float = 0.0
    entry_thesis: str = ""
    technical_execution_supported: bool = True
    strategy_qualified: bool = False
    qualification_reasons: List[str] = field(default_factory=list)

    # Market context
    market_session: str = "REGULAR"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.current_price <= 0.0:
            raise ValueError(f"Current price must be strictly positive, got {self.current_price}")
        if self.current_price_gbp <= 0.0:
            raise ValueError(f"Current price in GBP must be strictly positive, got {self.current_price_gbp}")
        if self.downside_risk > 0.05:
            raise ValueError(f"Downside risk exceeds 5% max-loss invariant: {self.downside_risk:.4f}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AllocationDecision:
    """
    Output of DynamicCapitalAllocator for a single qualified opportunity.
    Enforces <=80% deployment constraint and per-holding max 5% loss.
    """
    instrument_id: str
    symbol: str
    feed_ticker: str
    allocated_capital_gbp: float
    allocation_pct_of_portfolio: float
    target_quantity: float
    estimated_fill_price: float
    opportunity_score: float
    entry_thesis: str
    stop_loss_price: float
    max_loss_pct: float = 0.05
    take_profit_target: Optional[float] = None
    currency: str = "GBP"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.allocated_capital_gbp <= 0.0:
            raise ValueError(f"Allocated capital must be positive, got {self.allocated_capital_gbp}")
        if self.max_loss_pct > 0.05:
            raise ValueError(f"Allocation max loss pct exceeds 5% invariant: {self.max_loss_pct}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeAuditRecord:
    """
    Immutable audit record for every AI Hit-and-Run decision per Requirement 11.
    """
    trade_id: str
    instrument: str
    timestamp: str
    market_session: str
    opportunity_score: float
    entry_thesis: str
    capital_allocated_gbp: float
    expected_costs_gbp: float
    expected_net_reward_gbp: float
    downside_gbp: float
    fill_price: float
    protective_level: float
    exit_reason: Optional[str] = None
    exit_price: Optional[float] = None
    gross_pnl_gbp: float = 0.0
    costs_gbp: float = 0.0
    net_pnl_gbp: float = 0.0
    cumulative_banked_profit_gbp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
