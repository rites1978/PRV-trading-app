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

    # Broker contract & metadata attributes
    isin: str = ""
    min_trade_quantity: Optional[float] = None
    quantity_precision: Optional[int] = None
    tick_size: Optional[float] = None
    exchange_venue: str = ""
    cost_model_complete: bool = True
    cost_model_reasons: List[str] = field(default_factory=list)

    # Short-term quantitative indicators (None when data unavailable - no semantic fabrication)
    momentum: Optional[float] = None
    acceleration: Optional[float] = None
    relative_strength: Optional[float] = None
    liquidity: Optional[float] = None
    spread_friction: Optional[float] = None
    volatility: Optional[float] = None
    volume_activity: Optional[float] = None
    distance_from_high: Optional[float] = None
    distance_from_low: Optional[float] = None
    volume_data_status: str = "VOLUME_DATA_UNAVAILABLE"
    volatility_data_status: str = "VOLATILITY_DATA_UNAVAILABLE"

    # Economics & Risk
    estimated_costs: Optional[float] = None
    expected_net_reward: Optional[float] = None
    downside_risk: Optional[float] = None  # None if downside model unavailable; holding stop capped at 5%
    downside_model_status: str = "DOWNSIDE_MODEL_UNAVAILABLE"
    risk_reward_ratio: Optional[float] = None

    # AI Conviction & Thesis
    opportunity_score: Optional[float] = None
    entry_thesis: str = ""
    technical_execution_supported: bool = True
    strategy_qualified: bool = False
    execution_authorised: bool = False
    qualification_reasons: List[str] = field(default_factory=list)

    # Market context
    market_session: str = "REGULAR"
    extended_hours_eligible: bool = False
    extended_hours_status: str = "UNKNOWN"
    extended_hours: Optional[bool] = None
    overnight_eligibility: str = "UNKNOWN"
    execution_session: str = "REGULAR"
    next_session_transition: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.current_price <= 0.0:
            raise ValueError(f"Current price must be strictly positive, got {self.current_price}")
        if self.current_price_gbp <= 0.0:
            raise ValueError(f"Current price in GBP must be strictly positive, got {self.current_price_gbp}")

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
    entry_thesis: str
    stop_loss_price: float
    opportunity_score: Optional[float] = None
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


class LifecycleAction:
    """Authorised position lifecycle actions for Hit-and-Run holdings."""
    HOLD = "HOLD"
    TAKE_PROFIT = "TAKE_PROFIT"
    EDGE_DECAY_EXIT = "EDGE_DECAY_EXIT"
    MOMENTUM_REVERSAL_EXIT = "MOMENTUM_REVERSAL_EXIT"
    ROTATE = "ROTATE"
    STOP_LOSS_EXIT = "STOP_LOSS_EXIT"

    ALL_ACTIONS = {HOLD, TAKE_PROFIT, EDGE_DECAY_EXIT, MOMENTUM_REVERSAL_EXIT, ROTATE, STOP_LOSS_EXIT}


class ProductionClassification:
    """Authoritative production telemetry classification per Requirement H and Non-Negotiable Gate."""
    PRODUCTION_FAILURE = "PRODUCTION_FAILURE"
    STRATEGY_OUTCOME = "STRATEGY_OUTCOME"
    NO_VALID_EDGE = "NO_VALID_EDGE"
    TRADE_EXECUTED = "TRADE_EXECUTED"
    BROKER_EXECUTION_FAILURE = "BROKER_EXECUTION_FAILURE"
    STRATEGY_DECISION_UNAVAILABLE = "STRATEGY_DECISION_UNAVAILABLE"
    TRADING_LOSS = "TRADING_LOSS"


@dataclass
class LiveOpportunityState:
    """
    Live market-state model for technically executable instruments (Requirement A).
    Carries all available market, liquidity, friction, and capability information.
    Does NOT enforce arbitrary thresholds or cutoffs.
    Missing critical execution data remain UNKNOWN (None), never fabricated.
    """
    instrument_id: str
    symbol: str
    feed_ticker: str
    exchange_venue: str
    session_state: str                   # "REGULAR", "OPEN", "CLOSED", "AUCTION", "UNKNOWN"
    current_price: float
    current_price_gbp: float
    currency: str
    is_uk_pence: bool = False
    quote_divisor: float = 1.0

    # Executable Bid / Ask & Spread Friction (strictly None if unavailable)
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_friction: Optional[float] = None

    # Recent Price Path & Technical Indicators
    recent_prices: List[float] = field(default_factory=list)
    short_duration_momentum: Optional[float] = None
    momentum_acceleration: Optional[float] = None
    relative_strength: Optional[float] = None
    volume_activity: Optional[float] = None
    volatility: Optional[float] = None
    distance_from_high: Optional[float] = None
    distance_from_low: Optional[float] = None
    volume_data_status: str = "VOLUME_DATA_UNAVAILABLE"
    volatility_data_status: str = "VOLATILITY_DATA_UNAVAILABLE"

    # Economics & Cost Model
    estimated_costs: Optional[float] = None
    expected_gross_move: Optional[float] = None
    expected_net_opportunity: Optional[float] = None
    expected_move_model_status: str = "EXPECTED_MOVE_MODEL_UNAVAILABLE"
    cost_model_complete: bool = True
    cost_model_reasons: List[str] = field(default_factory=list)

    # Technical Execution Capability
    technical_execution_supported: bool = True
    min_trade_quantity: Optional[float] = None
    quantity_precision: Optional[int] = None
    tick_size: Optional[float] = None
    tick_size_rule: Optional[str] = None
    isin: str = ""

    # Data Freshness & Session Executability Verification
    data_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    quote_timestamp: Optional[str] = None
    data_age_seconds: Optional[float] = None
    quote_freshness_status: str = "UNKNOWN"   # CURRENT, STALE, UNKNOWN
    is_fresh: bool = True
    session_open: bool = False
    extended_hours_eligible: bool = False
    extended_hours_status: str = "UNKNOWN"
    extended_hours: Optional[bool] = None
    overnight_eligibility: str = "UNKNOWN"    # TRUE, FALSE, UNKNOWN
    execution_session: str = "UNKNOWN"
    next_session_transition: Optional[Dict[str, Any]] = None
    quote_executable_now: bool = False
    quote_market_timestamp: Optional[str] = None
    quote_fetch_timestamp: Optional[str] = None

    # Setup features and metadata
    setup_features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OpportunityAnalysisResult:
    """
    Output of the auditable opportunity-analysis interface (Requirement B).
    Reasons across diverse short-duration setups: momentum, acceleration, breakout,
    pullback continuation, mean reversion, relative strength divergence, catalyst.
    Never fabricates a score if required data are incomplete.
    """
    instrument_id: str
    symbol: str
    feed_ticker: str
    state: LiveOpportunityState
    setup_family: str                    # MOMENTUM_CONTINUATION, ACCELERATION, BREAKOUT, etc.
    opportunity_thesis: str
    supporting_evidence: List[str]
    contrary_evidence: List[str]
    estimated_costs: Optional[float]
    expected_net_opportunity: Optional[float]
    data_quality_state: str              # COMPLETE, INCOMPLETE_SPREAD, INCOMPLETE_METADATA, etc.
    conviction_evidence: Dict[str, Any]
    downside_estimate: Optional[float] = None      # Informational evidence for AI reasoning (None if model unavailable)
    downside_model_status: str = "DOWNSIDE_MODEL_UNAVAILABLE"
    expected_gross_move: Optional[float] = None
    expected_move_model_status: str = "EXPECTED_MOVE_MODEL_UNAVAILABLE"
    setup_classification_status: str = "SETUP_MODEL_UNAVAILABLE"
    opportunity_score: Optional[float] = None  # None if required data are incomplete

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class AIAllocationDecision:
    """
    Authoritative AI capital allocation decision across opportunities (Requirement C).
    Enforces total deployment <= 80% of currently available capital.
    Fails closed with ALLOCATION_DECISION_UNAVAILABLE if AI is unavailable.
    """
    whether_to_trade: bool
    selected_allocations: Dict[str, float]  # instrument_id/symbol -> capital_gbp
    total_deployment_gbp: float
    total_deployment_pct: float
    rationale: str
    concentration_summary: str
    status: str                          # ALLOCATED, ALLOCATION_DECISION_UNAVAILABLE, NO_VALID_EDGE, etc.
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HitAndRunEntryDecision:
    """
    Explicit hit-and-run entry decision object (Requirement D).
    Result is strictly ENTER or NO_ENTRY with exhaustive audit fields.
    """
    decision: str                        # "ENTER" or "NO_ENTRY"
    instrument_id: str
    symbol: str
    feed_ticker: str
    intended_capital_gbp: Optional[float] = None
    intended_quantity: Optional[float] = None
    current_bid: Optional[float] = None
    current_ask: Optional[float] = None
    current_price: Optional[float] = None
    expected_costs_gbp: Optional[float] = None
    expected_net_opportunity: Optional[float] = None
    thesis: str = ""
    downside: Optional[float] = None      # Informational market downside estimate
    quantity_increment: Optional[float] = None
    quantity_precision: Optional[int] = None
    tick_size: Optional[float] = None
    required_protective_level: Optional[float] = None
    allocation_rationale: str = ""
    decision_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_timestamp: str = ""
    no_entry_reason: Optional[str] = None

    def __post_init__(self):
        if self.decision == "ENTER":
            if not self.intended_capital_gbp or self.intended_capital_gbp <= 0:
                raise ValueError(f"ENTER decision requires positive intended capital: {self.intended_capital_gbp}")
            if not self.intended_quantity or self.intended_quantity <= 0:
                raise ValueError(f"ENTER decision requires positive intended quantity: {self.intended_quantity}")
            if self.required_protective_level is None:
                raise ValueError("ENTER decision requires explicit required_protective_level")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HoldingState:
    """Live state for an active Hit-and-Run position."""
    holding_id: str
    instrument_id: str
    symbol: str
    feed_ticker: str
    fill_price: float
    quantity: float
    allocated_capital_gbp: float
    entry_timestamp: str
    entry_thesis: str
    protective_stop_price: float
    planned_loss_pct: float
    tick_size: float
    quantity_precision: int
    currency: str = "GBP"
    quote_divisor: float = 1.0
    exchange_venue: str = ""
    isin: str = ""
    highest_price_seen: float = 0.0
    lowest_price_seen: float = 0.0
    current_unrealised_net_pnl_gbp: Optional[float] = None

    def __post_init__(self):
        if self.planned_loss_pct > 0.05:
            raise ValueError(f"Holding planned loss pct exceeds 5% max-loss invariant: {self.planned_loss_pct}")
        if self.highest_price_seen <= 0.0:
            self.highest_price_seen = self.fill_price
        if self.lowest_price_seen <= 0.0:
            self.lowest_price_seen = self.fill_price

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LifecycleAssessment:
    """
    Continuous evaluation result for an active Hit-and-Run holding (Requirement E).
    Actions: HOLD, TAKE_PROFIT, EDGE_DECAY_EXIT, MOMENTUM_REVERSAL_EXIT, ROTATE, STOP_LOSS_EXIT.
    Adaptive profit capture, no arbitrary fixed percentages.
    When no authorised lifecycle decision exists: action=None, lifecycle_decision_status="UNAVAILABLE".
    """
    holding_id: str
    instrument_id: str
    symbol: str
    action: Optional[str] = None         # One of LifecycleAction, or None if UNAVAILABLE
    current_price: float = 0.0
    current_bid: Optional[float] = None
    current_ask: Optional[float] = None
    gross_unrealised_pnl_gbp: float = 0.0
    estimated_exit_costs_gbp: Optional[float] = None
    net_unrealised_pnl_gbp: Optional[float] = None
    net_unrealised_pct: Optional[float] = None
    thesis_health: str = "UNKNOWN"       # "INTACT", "EXHAUSTED", "REVERSED", "DECAYED", "STOP_BREACHED", "LIFECYCLE_DECISION_UNAVAILABLE"
    rationale: str = ""
    target_rotation_symbol: Optional[str] = None
    rotation_decision_status: Optional[str] = None
    lifecycle_decision_status: str = "UNAVAILABLE"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionTelemetry:
    """
    Authoritative production telemetry distinguishing failures, outcomes, and edge availability.
    Enforces the Non-Negotiable No-Trade Acceptance Gate:
    - NO_VALID_EDGE only when all prerequisites are proven.
    - Product failures are never classified as NO_VALID_EDGE.
    - Decoupled scan process completion vs market evaluation complete.
    """
    timestamp: str
    classification: str                  # Allowed: TRADE_EXECUTED, NO_VALID_EDGE, PRODUCTION_FAILURE, BROKER_EXECUTION_FAILURE, STRATEGY_DECISION_UNAVAILABLE, STRATEGY_OUTCOME, TRADING_LOSS
    
    # Scan Coverage Telemetry (Section 5)
    discovered_count: Any                # int or "UNKNOWN"
    broker_tradable_known_count: Any     # int or "UNKNOWN"
    broker_tradability_unknown_count: Any# int or "UNKNOWN"
    open_session_count: Any              # int or "UNKNOWN"
    market_data_requested_count: Any     # int or "UNKNOWN"
    market_data_success_count: Any       # int or "UNKNOWN"
    market_data_failure_count: Any       # int or "UNKNOWN"
    current_execution_grade_quote_count: Any # int or "UNKNOWN"
    technically_executable_count: Any    # int or "UNKNOWN"
    cost_complete_count: Any             # int or "UNKNOWN"
    strategy_analysed_count: Any         # int or "UNKNOWN"
    positive_edge_candidate_count: Any   # int or "UNKNOWN"
    ai_evaluated_count: Any              # int or "UNKNOWN"
    final_approval_count: Any            # int or "UNKNOWN"
    orders_submitted_count: Any          # int or "UNKNOWN"

    # Process & Evaluation Decoupling (Section 1 & 3)
    scan_process_completed: bool = True
    market_evaluation_complete: bool = False
    no_valid_edge_prerequisites_proven: bool = False
    scan_universe_type: str = "FULL_UNIVERSE" # "FULL_UNIVERSE" or "TEST_SUBSET"

    # Prerequisite Statuses (Section 1)
    universe_discovery_status: str = "UNKNOWN"
    broker_tradability_status: str = "UNKNOWN"
    session_status: str = "UNKNOWN"
    market_data_status: str = "UNKNOWN"
    quote_status: str = "UNKNOWN"
    bid_ask_status: str = "UNKNOWN"
    cost_status: str = "UNKNOWN"
    technical_execution_status: str = "UNKNOWN"
    expected_move_decision_status: str = "UNKNOWN"
    ai_allocation_decision_status: str = "UNKNOWN"
    strategy_analysis_status: str = "UNKNOWN"

    # Business & Portfolio Metrics
    active_holdings_count: int = 0
    banked_net_profit_today_gbp: float = 0.0
    remaining_to_100_base_target_gbp: float = 100.0
    base_target_achieved: bool = False
    continue_trading: bool = True
    failures_found: List[str] = field(default_factory=list)
    primary_failure_reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    # Legacy compatibility fields
    fresh_quote_count: int = 0
    opportunity_count: int = 0
    qualified_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DashboardScanStatus:
    """
    Independent dashboard status view preventing healthy infrastructure from being
    mistaken for successful trading capability (Section 10).
    """
    engine_health: str                   # "HEALTHY", "DEGRADED", "UNHEALTHY"
    scan_process_status: str             # "COMPLETED", "IN_PROGRESS", "FAILED"
    market_evaluation_status: str        # "COMPLETE", "INCOMPLETE"
    trade_outcome: str                   # "TRADE_EXECUTED", "NO_VALID_EDGE", "NONE"
    production_status: str               # "OK", "FAILURE"
    production_failure_reason: Optional[str] = None
    no_valid_edge_prerequisites_proven: bool = False
    scan_universe_type: str = "FULL_UNIVERSE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
