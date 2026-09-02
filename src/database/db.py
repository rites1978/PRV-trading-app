import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from src.config.settings import settings

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS profit_vault (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    trade_id TEXT,
    symbol TEXT,
    realized_profit REAL NOT NULL,
    cumulative_vault_total REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    total_cost REAL NOT NULL,
    spread_cost REAL DEFAULT 0,
    slippage_cost REAL DEFAULT 0,
    fx_cost REAL DEFAULT 0,
    net_cost REAL NOT NULL,
    realized_pnl REAL DEFAULT 0,
    confidence_score REAL NOT NULL,
    reward_risk_ratio REAL NOT NULL,
    trade_reason TEXT NOT NULL,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL,
    average_entry_price REAL NOT NULL,
    current_price REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    unrealized_pnl_pct REAL NOT NULL,
    stop_loss_price REAL NOT NULL,
    take_profit_price REAL NOT NULL,
    sector TEXT,
    entry_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS boardroom_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    symbol TEXT NOT NULL,
    overall_confidence REAL NOT NULL,
    market_regime TEXT NOT NULL,
    trend_agent_vote TEXT NOT NULL,
    momentum_agent_vote TEXT NOT NULL,
    volatility_agent_vote TEXT NOT NULL,
    liquidity_agent_vote TEXT NOT NULL,
    risk_agent_vote TEXT NOT NULL,
    approved INTEGER NOT NULL,
    reasoning TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confidence_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    symbol TEXT NOT NULL,
    trend_strength REAL NOT NULL,
    relative_strength REAL NOT NULL,
    momentum REAL NOT NULL,
    volume_confirmation REAL NOT NULL,
    volatility_condition REAL NOT NULL,
    market_regime REAL NOT NULL,
    portfolio_exposure REAL NOT NULL,
    trading_cost_impact REAL NOT NULL,
    composite_confidence REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    portfolio_value REAL NOT NULL,
    action_taken TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_performance (
    date TEXT PRIMARY KEY,
    starting_nav REAL NOT NULL,
    ending_nav REAL NOT NULL,
    daily_pnl REAL NOT NULL,
    daily_pnl_pct REAL NOT NULL,
    drawdown_pct REAL NOT NULL,
    peak_nav REAL NOT NULL,
    profit_vault_balance REAL NOT NULL,
    capital_utilization_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    symbol TEXT,
    market_conditions TEXT,
    agent_votes TEXT,
    confidence_score REAL,
    trade_reason TEXT,
    risk_approval INTEGER,
    position_size REAL,
    exit_reason TEXT,
    final_result TEXT
);

CREATE TABLE IF NOT EXISTS catalyst_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sector TEXT,
    headline TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    importance_score REAL NOT NULL,
    confidence_score REAL NOT NULL,
    catalyst_score REAL NOT NULL,
    deployment_flag INTEGER DEFAULT 0,
    trade_outcome TEXT DEFAULT 'MONITORING'
);

CREATE TABLE IF NOT EXISTS catalyst_paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_trade_id TEXT UNIQUE,
    event_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    ticker TEXT NOT NULL,
    sector TEXT,
    catalyst_type TEXT NOT NULL DEFAULT 'MACRO_POLICY',
    catalyst_score REAL NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL NOT NULL,
    return_1d REAL,
    return_5d REAL,
    return_10d REAL,
    return_30d REAL,
    benchmark_return_1d REAL,
    benchmark_return_5d REAL,
    benchmark_return_10d REAL,
    benchmark_return_30d REAL,
    alpha_vs_baseline REAL DEFAULT 0.0,
    status TEXT DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS daily_executive_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT UNIQUE,
    report_json TEXT NOT NULL,
    nav REAL NOT NULL,
    daily_pnl REAL NOT NULL,
    trades_opened_count INTEGER DEFAULT 0,
    trades_closed_count INTEGER DEFAULT 0,
    compliance_status TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_executive_reports(report_date);

CREATE TABLE IF NOT EXISTS symbol_cooldowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    t212_ticker TEXT NOT NULL,
    triggering_trade_id INTEGER NOT NULL,
    cooldown_start_timestamp DATETIME NOT NULL,
    cooldown_expiry_timestamp DATETIME NOT NULL,
    duration_days INTEGER NOT NULL DEFAULT 10,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'EXPIRED', 'ADMIN_OVERRIDDEN')),
    quarantine_reason TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_regimes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    spy_close REAL NOT NULL,
    spy_sma20 REAL NOT NULL,
    spy_sma50 REAL NOT NULL,
    spy_sma200 REAL NOT NULL,
    vix_level REAL NOT NULL,
    regime_classification TEXT NOT NULL,
    risk_capacity_pct REAL NOT NULL,
    trading_permission TEXT NOT NULL,
    diagnostic_rationale TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL UNIQUE,
    claim_statement TEXT NOT NULL,
    epistemic_grade TEXT NOT NULL,
    empirical_evidence_summary TEXT NOT NULL,
    sample_size_evaluated INTEGER NOT NULL,
    verified_by TEXT NOT NULL,
    last_audit_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    exit_timestamp DATETIME NOT NULL,
    realized_pnl REAL NOT NULL,
    realized_pnl_pct REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    pre_entry_latency_days REAL NOT NULL DEFAULT 0.0,
    entry_atr14 REAL NOT NULL DEFAULT 0.0,
    post_exit_mfe_20d_pct REAL NOT NULL DEFAULT 0.0,
    post_exit_mae_20d_pct REAL NOT NULL DEFAULT 0.0,
    days_since_prior_stop INTEGER DEFAULT NULL,
    macro_regime_at_entry TEXT NOT NULL,
    earnings_proximity_days INTEGER DEFAULT NULL,
    slippage_pct REAL NOT NULL DEFAULT 0.0,
    root_cause_category TEXT NOT NULL,
    attribution_confidence REAL NOT NULL,
    forensic_notes TEXT NOT NULL,
    classified_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    entry_timestamp DATETIME NOT NULL,
    exit_timestamp DATETIME NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    entry_atr14 REAL NOT NULL,
    duration_hours REAL NOT NULL,
    max_favorable_excursion_pct REAL NOT NULL,
    max_adverse_excursion_pct REAL NOT NULL,
    post_exit_mfe_5d_pct REAL NOT NULL DEFAULT 0.0,
    post_exit_mfe_10d_pct REAL NOT NULL DEFAULT 0.0,
    post_exit_mfe_20d_pct REAL NOT NULL DEFAULT 0.0,
    post_exit_mae_20d_pct REAL NOT NULL DEFAULT 0.0,
    reached_target_post_exit INTEGER NOT NULL DEFAULT 0,
    trajectory_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_performance_cycles (
    cycle_id TEXT PRIMARY KEY,
    cycle_name TEXT NOT NULL,
    start_date DATETIME NOT NULL,
    end_date DATETIME,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    starting_capital REAL NOT NULL,
    ending_capital REAL,
    realised_pnl REAL DEFAULT 0.0,
    unrealised_pnl REAL DEFAULT 0.0,
    total_return REAL DEFAULT 0.0,
    total_return_pct REAL DEFAULT 0.0,
    trade_count INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    max_drawdown REAL DEFAULT 0.0,
    profit_factor REAL DEFAULT 0.0,
    git_commit TEXT,
    ai_version TEXT,
    feature_set TEXT,
    notes TEXT,
    data_source_type TEXT NOT NULL DEFAULT 'LIVE',
    evaluation_eligible INTEGER NOT NULL DEFAULT 0,
    sample_size_classification TEXT NOT NULL DEFAULT 'LOW',
    confidence_level TEXT NOT NULL DEFAULT 'LOW',
    evaluation_reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_cycle_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id TEXT UNIQUE,
    cycle_a TEXT NOT NULL,
    cycle_b TEXT NOT NULL,
    return_delta REAL NOT NULL,
    win_rate_delta REAL NOT NULL,
    profit_factor_delta REAL NOT NULL,
    drawdown_delta REAL NOT NULL,
    ai_effectiveness_score REAL,
    classification TEXT NOT NULL,
    comparison_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_integrity_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    broker_nav REAL NOT NULL,
    api_nav REAL NOT NULL,
    dashboard_nav REAL,
    variance REAL NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSON
);

CREATE TABLE IF NOT EXISTS evidence_broker_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    broker_nav REAL NOT NULL,
    internal_nav REAL NOT NULL,
    nav_discrepancy_pct REAL NOT NULL,
    open_positions_broker INTEGER NOT NULL,
    open_positions_internal INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    nav REAL NOT NULL,
    cash REAL NOT NULL,
    invested REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    cycle_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON portfolio_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_cycle ON portfolio_snapshots(cycle_id);

CREATE TABLE IF NOT EXISTS research_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    entry_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    universe_rank INTEGER NOT NULL,
    expected_value_pct REAL NOT NULL,
    predicted_win_probability REAL NOT NULL,
    expected_return_pct REAL NOT NULL DEFAULT 7.50,
    expected_holding_period_days REAL NOT NULL DEFAULT 10.0,
    catalyst_type TEXT NOT NULL,
    catalyst_description TEXT NOT NULL,
    investment_thesis TEXT NOT NULL,
    invalidation_criteria TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    exit_timestamp DATETIME DEFAULT NULL,
    actual_return_pct REAL DEFAULT NULL,
    actual_alpha_vs_benchmark REAL DEFAULT NULL,
    benchmark_name TEXT DEFAULT 'S&P 500',
    outcome TEXT DEFAULT NULL,
    exit_reason TEXT DEFAULT NULL,
    thesis_correct INTEGER DEFAULT NULL,
    notes TEXT DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS thesis_drift_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    original_thesis TEXT NOT NULL,
    original_catalyst TEXT NOT NULL,
    original_ev REAL NOT NULL,
    original_probability REAL NOT NULL,
    thesis_strength REAL NOT NULL,
    catalyst_status TEXT NOT NULL,
    thesis_integrity TEXT NOT NULL CHECK (thesis_integrity IN ('STRENGTHENING', 'UNCHANGED', 'DETERIORATING')),
    drift_reason TEXT NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_drift_sym_date ON thesis_drift_records(symbol, date);

CREATE TABLE IF NOT EXISTS regime_performance_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regime TEXT NOT NULL UNIQUE,
    win_rate REAL NOT NULL,
    profit_factor REAL NOT NULL,
    alpha_vs_sp500 REAL NOT NULL,
    alpha_vs_ftse100 REAL NOT NULL,
    average_trade_return REAL NOT NULL,
    average_holding_period_days REAL NOT NULL,
    sample_trades_count INTEGER NOT NULL,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_health_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    health_score REAL NOT NULL,
    trend TEXT NOT NULL CHECK (trend IN ('IMPROVING', 'STABLE', 'DETERIORATING')),
    research_accuracy_subscore REAL NOT NULL,
    capital_efficiency_subscore REAL NOT NULL,
    ranking_quality_subscore REAL NOT NULL,
    probability_calibration_subscore REAL NOT NULL,
    benchmark_alpha_subscore REAL NOT NULL,
    regime_performance_subscore REAL NOT NULL,
    risk_control_subscore REAL NOT NULL,
    summary_notes TEXT
);

CREATE TABLE IF NOT EXISTS learning_engine_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    lesson_category TEXT NOT NULL,
    best_alpha_source TEXT NOT NULL,
    worst_alpha_source TEXT NOT NULL,
    optimal_holding_period_days REAL NOT NULL,
    best_regime TEXT NOT NULL,
    worst_regime TEXT NOT NULL,
    empirical_evidence TEXT NOT NULL,
    actionable_insight TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_postmortems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    entry_timestamp DATETIME NOT NULL,
    exit_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    prediction_summary TEXT NOT NULL,
    actual_outcome TEXT NOT NULL,
    actual_return_pct REAL NOT NULL,
    forecast_error_pct REAL NOT NULL,
    thesis_accuracy_score REAL NOT NULL,
    catalyst_accuracy_score REAL NOT NULL,
    alpha_generated_pct REAL NOT NULL,
    lessons_learned TEXT NOT NULL,
    regime TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_postmortem_sym ON trade_postmortems(symbol);

CREATE TABLE IF NOT EXISTS thesis_success_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    thesis_type TEXT NOT NULL,
    original_thesis TEXT NOT NULL,
    catalyst TEXT NOT NULL,
    entry_rank INTEGER NOT NULL,
    entry_ev REAL NOT NULL,
    entry_probability REAL NOT NULL,
    exit_outcome TEXT NOT NULL,
    alpha_generated_pct REAL NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_thesis_type ON thesis_success_records(thesis_type);

CREATE TABLE IF NOT EXISTS portfolio_evolution_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    portfolio_health REAL NOT NULL,
    live_evidence_score REAL NOT NULL,
    cumulative_alpha_sp500 REAL NOT NULL,
    capital_efficiency_score REAL NOT NULL,
    research_accuracy_pct REAL NOT NULL,
    nav REAL NOT NULL,
    completed_trades_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evolution_time ON portfolio_evolution_snapshots(timestamp);

CREATE TABLE IF NOT EXISTS exit_quality_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exit_type TEXT NOT NULL,
    realized_pnl REAL NOT NULL,
    mfe_pct REAL NOT NULL,
    mae_pct REAL NOT NULL,
    exit_efficiency_pct REAL NOT NULL,
    slippage_bps REAL NOT NULL,
    evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS position_upgrade_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    current_symbol TEXT NOT NULL,
    current_rank INTEGER NOT NULL,
    current_ev REAL NOT NULL,
    upgrade_candidate_symbol TEXT NOT NULL,
    candidate_rank INTEGER NOT NULL,
    candidate_ev REAL NOT NULL,
    ev_differential_pct REAL NOT NULL,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS capital_recycling_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol TEXT NOT NULL,
    capital_freed_gbp REAL NOT NULL,
    reinvested_symbol TEXT NOT NULL,
    reinvested_amount_gbp REAL NOT NULL,
    recycling_reason TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alpha_contribution_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    weight_pct REAL NOT NULL,
    realized_alpha_bps REAL NOT NULL,
    contribution_category TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_concentration_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    max_single_stock_pct REAL NOT NULL,
    max_sector_name TEXT NOT NULL,
    max_sector_pct REAL NOT NULL,
    currency_usd_pct REAL NOT NULL,
    currency_gbp_pct REAL NOT NULL,
    hhi_index REAL NOT NULL,
    risk_status TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_journeys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_timestamp DATETIME NOT NULL,
    peak_gain_pct REAL NOT NULL,
    peak_loss_pct REAL NOT NULL,
    exit_price REAL,
    exit_timestamp DATETIME,
    mfe_pct REAL NOT NULL,
    mae_pct REAL NOT NULL,
    time_to_peak_hours REAL NOT NULL,
    time_to_exit_hours REAL,
    profit_capture_pct REAL,
    status TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE INDEX IF NOT EXISTS idx_journey_sym ON trade_journeys(symbol);

CREATE TABLE IF NOT EXISTS decision_quality_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    decision_type TEXT NOT NULL CHECK (decision_type IN ('BUY', 'HOLD', 'SELL', 'REDUCE', 'INCREASE')),
    symbol TEXT NOT NULL,
    decision_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    evaluated_outcome TEXT NOT NULL CHECK (evaluated_outcome IN ('CORRECT', 'NEUTRAL', 'INCORRECT', 'PENDING')),
    decision_quality_score REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS edge_decay_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    day_horizon INTEGER NOT NULL,
    alpha_decay_pct REAL NOT NULL,
    probability_decay_pct REAL NOT NULL,
    catalyst_decay_status TEXT NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS benchmark_dominance_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    winning_days_pct REAL NOT NULL,
    winning_weeks_pct REAL NOT NULL,
    winning_months_pct REAL NOT NULL,
    rolling_alpha_sp500 REAL NOT NULL,
    rolling_alpha_ftse100 REAL NOT NULL,
    cash_outperformance_pct REAL NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS institutional_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_health REAL NOT NULL,
    live_evidence_score REAL NOT NULL,
    alpha_score REAL NOT NULL,
    research_quality REAL NOT NULL,
    capital_efficiency REAL NOT NULL,
    risk_quality REAL NOT NULL,
    execution_quality REAL NOT NULL,
    institutional_readiness_score REAL NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS premarket_readiness_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    overall_status TEXT NOT NULL CHECK (overall_status IN ('READY FOR TRADING', 'NOT READY FOR TRADING')),
    infrastructure_status TEXT NOT NULL,
    broker_status TEXT NOT NULL,
    data_status TEXT NOT NULL,
    research_status TEXT NOT NULL,
    phase2_status TEXT NOT NULL,
    phase4_status TEXT NOT NULL,
    phase5_status TEXT NOT NULL,
    reporting_status TEXT NOT NULL,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_readiness_time ON premarket_readiness_checks(timestamp);

CREATE TABLE IF NOT EXISTS shadow_portfolio_comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    portfolio_a_return_pct REAL NOT NULL,
    portfolio_a_alpha_sp500 REAL NOT NULL,
    portfolio_a_drawdown_pct REAL NOT NULL,
    portfolio_a_ev_pct REAL NOT NULL,
    portfolio_b_return_pct REAL NOT NULL,
    portfolio_b_alpha_sp500 REAL NOT NULL,
    portfolio_b_drawdown_pct REAL NOT NULL,
    portfolio_b_ev_pct REAL NOT NULL,
    spread_return_pct REAL NOT NULL,
    spread_ev_pct REAL NOT NULL,
    opportunity_cost_gbp REAL NOT NULL,
    opportunity_cost_bps REAL NOT NULL,
    winning_portfolio TEXT NOT NULL,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_shadow_comp_time ON shadow_portfolio_comparisons(timestamp);

CREATE TABLE IF NOT EXISTS shadow_promotion_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_symbol TEXT NOT NULL,
    replace_symbol TEXT NOT NULL,
    days_winning INTEGER DEFAULT 0,
    candidate_return_pct REAL NOT NULL,
    held_return_pct REAL NOT NULL,
    excess_return_pct REAL NOT NULL,
    opportunity_gain_gbp REAL NOT NULL,
    promotion_score REAL NOT NULL,
    promotion_eligible TEXT NOT NULL CHECK (promotion_eligible IN ('ELIGIBLE', 'IN_PROGRESS', 'LOCKED')),
    eligibility_reason TEXT,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_shadow_promo_cand ON shadow_promotion_candidates(candidate_symbol);

CREATE TABLE IF NOT EXISTS macro_event_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    evaluation_date TEXT NOT NULL,
    event_id TEXT NOT NULL,
    category TEXT NOT NULL,
    event_name TEXT NOT NULL,
    portfolio_exposure TEXT NOT NULL CHECK (portfolio_exposure IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')),
    affected_holdings TEXT NOT NULL,
    direct_impact TEXT NOT NULL,
    indirect_impact TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')),
    expected_effect TEXT NOT NULL,
    mitigation_action TEXT,
    source_classification TEXT NOT NULL DEFAULT 'LIVE NEWS',
    publisher TEXT,
    source_url TEXT,
    published_at TEXT,
    retrieved_at TEXT,
    is_last_24h INTEGER DEFAULT 1,
    confidence_score REAL DEFAULT 90.0,
    raw_headline TEXT,
    raw_payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_macro_ledger_date ON macro_event_ledger(evaluation_date);

CREATE TABLE IF NOT EXISTS reconciliation_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    report_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_nav REAL NOT NULL,
    free_cash REAL NOT NULL,
    invested_capital REAL NOT NULL,
    positions_sum REAL NOT NULL,
    nav_variance REAL NOT NULL,
    invested_variance REAL NOT NULL,
    position_count INTEGER NOT NULL,
    broker_position_count INTEGER NOT NULL,
    failed_invariants TEXT,
    reconciliation_details TEXT
);
CREATE INDEX IF NOT EXISTS idx_recon_date ON reconciliation_ledger(report_date);

CREATE TABLE IF NOT EXISTS order_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    signal_timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    action TEXT NOT NULL,
    signal_price REAL NOT NULL,
    bid_at_signal REAL,
    ask_at_signal REAL,
    spread_bps REAL,
    requested_price REAL NOT NULL,
    submitted_price REAL NOT NULL,
    fill_price REAL NOT NULL,
    quantity REAL NOT NULL,
    partial_fill_quantity REAL DEFAULT 0,
    latency_ms REAL,
    slippage_bps REAL,
    time_to_fill_sec REAL,
    order_type TEXT NOT NULL DEFAULT 'MARKETABLE_LIMIT',
    status TEXT NOT NULL DEFAULT 'FILLED'
);
CREATE INDEX IF NOT EXISTS idx_telemetry_sym ON order_telemetry(symbol);

CREATE TABLE IF NOT EXISTS shadow_strategy_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    evaluation_date TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    nav REAL NOT NULL,
    gross_pnl REAL NOT NULL,
    total_costs REAL NOT NULL,
    net_pnl REAL NOT NULL,
    net_expectancy REAL NOT NULL,
    profit_factor REAL NOT NULL,
    win_rate REAL NOT NULL,
    payoff_ratio REAL NOT NULL,
    cost_to_gross_profit_ratio REAL NOT NULL,
    trade_count INTEGER NOT NULL,
    avg_holding_period_days REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    mfe_avg REAL DEFAULT 0.0,
    mae_avg REAL DEFAULT 0.0,
    sharpe_ratio REAL DEFAULT 0.0,
    capital_employed_avg REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
);
CREATE INDEX IF NOT EXISTS idx_shadow_strat ON shadow_strategy_ledger(strategy_id, evaluation_date);
"""

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DB_PATH
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            conn.executescript(CREATE_TABLES_SQL)
            cur = conn.cursor()
            
            # 1. Automatic schema migration for catalyst_type
            cur.execute("PRAGMA table_info(catalyst_paper_trades)")
            cols = [r["name"] for r in cur.fetchall()]
            if cols and "catalyst_type" not in cols:
                cur.execute("ALTER TABLE catalyst_paper_trades ADD COLUMN catalyst_type TEXT NOT NULL DEFAULT 'MACRO_POLICY'")

            # 2. Automatic schema migration for cycle_id on relevant tables
            for tbl in ["trades", "trade_attributions", "daily_performance", "profit_vault", "daily_executive_reports", "boardroom_decisions"]:
                cur.execute(f"PRAGMA table_info({tbl})")
                tcols = [r["name"] for r in cur.fetchall()]
                if tcols and "cycle_id" not in tcols:
                    cur.execute(f"ALTER TABLE {tbl} ADD COLUMN cycle_id TEXT NOT NULL DEFAULT 'CYCLE-001'")

            # 3. Automatic migration for data_source_type in ai_performance_cycles
            cur.execute("PRAGMA table_info(ai_performance_cycles)")
            ccols = [r["name"] for r in cur.fetchall()]
            if ccols and "data_source_type" not in ccols:
                cur.execute("ALTER TABLE ai_performance_cycles ADD COLUMN data_source_type TEXT NOT NULL DEFAULT 'LIVE'")
                cur.execute("UPDATE ai_performance_cycles SET data_source_type = 'SIMULATED_TEST' WHERE cycle_id = 'CYCLE-001'")
                cur.execute("UPDATE ai_performance_cycles SET data_source_type = 'LIVE' WHERE cycle_id != 'CYCLE-001'")

            # 4. Automatic migration for statistical validity fields in ai_performance_cycles
            if ccols and "evaluation_eligible" not in ccols:
                cur.execute("ALTER TABLE ai_performance_cycles ADD COLUMN evaluation_eligible INTEGER NOT NULL DEFAULT 0")
            if ccols and "sample_size_classification" not in ccols:
                cur.execute("ALTER TABLE ai_performance_cycles ADD COLUMN sample_size_classification TEXT NOT NULL DEFAULT 'LOW'")
            if ccols and "confidence_level" not in ccols:
                cur.execute("ALTER TABLE ai_performance_cycles ADD COLUMN confidence_level TEXT NOT NULL DEFAULT 'LOW'")
            if ccols and "evaluation_reason" not in ccols:
                cur.execute("ALTER TABLE ai_performance_cycles ADD COLUMN evaluation_reason TEXT")

            # 5. Automatic migration for macro_event_ledger live news fields
            cur.execute("PRAGMA table_info(macro_event_ledger)")
            mcols = [r["name"] for r in cur.fetchall()]
            for c_name, c_def in [
                ("source_classification", "TEXT NOT NULL DEFAULT 'LIVE NEWS'"),
                ("publisher", "TEXT"),
                ("source_url", "TEXT"),
                ("published_at", "TEXT"),
                ("retrieved_at", "TEXT"),
                ("is_last_24h", "INTEGER DEFAULT 1"),
                ("confidence_score", "REAL DEFAULT 90.0"),
                ("raw_headline", "TEXT")
            ]:
                if mcols and c_name not in mcols:
                    cur.execute(f"ALTER TABLE macro_event_ledger ADD COLUMN {c_name} {c_def}")

            # 6. Automatic migration for trades true net P&L and post-mortem fields
            cur.execute("PRAGMA table_info(trades)")
            tr_cols = [r["name"] for r in cur.fetchall()]
            for c_name, c_def in [
                ("gross_entry_value", "REAL DEFAULT 0"),
                ("gross_exit_value", "REAL DEFAULT 0"),
                ("gross_profit_loss", "REAL DEFAULT 0"),
                ("broker_fees", "REAL DEFAULT 0"),
                ("taxes", "REAL DEFAULT 0"),
                ("stamp_duty_or_equivalent", "REAL DEFAULT 0"),
                ("fx_entry_cost", "REAL DEFAULT 0"),
                ("fx_exit_cost", "REAL DEFAULT 0"),
                ("exchange_regulatory_charges", "REAL DEFAULT 0"),
                ("estimated_spread_cost", "REAL DEFAULT 0"),
                ("actual_slippage", "REAL DEFAULT 0"),
                ("total_transaction_cost", "REAL DEFAULT 0"),
                ("net_realized_pnl", "REAL DEFAULT 0"),
                ("cost_as_pct_of_gross_profit", "REAL DEFAULT 0"),
                ("holding_period_days", "REAL DEFAULT 0"),
                ("mfe", "REAL DEFAULT 0"),
                ("mae", "REAL DEFAULT 0"),
                ("original_thesis", "TEXT"),
                ("original_probability", "REAL DEFAULT 0"),
                ("expected_return", "REAL DEFAULT 0"),
                ("expected_loss", "REAL DEFAULT 0"),
                ("expected_holding_period", "REAL DEFAULT 0"),
                ("stop_loss_price", "REAL DEFAULT 0"),
                ("take_profit_price", "REAL DEFAULT 0"),
                ("expected_costs", "REAL DEFAULT 0"),
                ("expected_net_expectancy", "REAL DEFAULT 0"),
                ("thesis_outcome", "TEXT")
            ]:
                if tr_cols and c_name not in tr_cols:
                    cur.execute(f"ALTER TABLE trades ADD COLUMN {c_name} {c_def}")

            # Auto-migrate order_telemetry table for implementation shortfall & order lifecycle
            cur.execute("PRAGMA table_info(order_telemetry)")
            ot_cols = [c["name"] for c in cur.fetchall()]
            for c_name, c_def in [
                ("decision_price", "REAL"),
                ("arrival_price", "REAL"),
                ("delay_cost_bps", "REAL"),
                ("spread_cost_bps", "REAL"),
                ("market_impact_bps", "REAL"),
                ("implementation_shortfall_bps", "REAL"),
                ("implementation_shortfall_gbp", "REAL"),
                ("chase_attempts", "INTEGER DEFAULT 0"),
                ("cancellation_reason", "TEXT")
            ]:
                if ot_cols and c_name not in ot_cols:
                    cur.execute(f"ALTER TABLE order_telemetry ADD COLUMN {c_name} {c_def}")

            # Seed initial cycles if ai_performance_cycles is empty
            cur.execute("SELECT COUNT(*) as cnt FROM ai_performance_cycles")
            cnt = cur.fetchone()["cnt"]
            if cnt == 0:
                # Historical Baseline (Cycle 1 - Archived with the 38 previous test trades)
                cur.execute("""
                    INSERT INTO ai_performance_cycles (
                        cycle_id, cycle_name, start_date, end_date, status,
                        starting_capital, ending_capital, realised_pnl, unrealised_pnl,
                        total_return, total_return_pct, trade_count, win_count, loss_count,
                        win_rate, max_drawdown, profit_factor, git_commit, ai_version, feature_set, notes, data_source_type,
                        evaluation_eligible, sample_size_classification, confidence_level, evaluation_reason
                    ) VALUES (
                        'CYCLE-001', 'Phase 47 Forward-Test Baseline', '2026-07-07 15:30:00', '2026-08-22 16:00:00', 'ARCHIVED',
                        50000.0, 49800.53, -199.47, 0.0, -199.47, -0.40, 38, 4, 34,
                        10.5, 2.18, 0.11, '07179c6', 'v1.0-forward-test',
                        'Phase 47 ATR Stop & Breakeven Rules', 'Archived legacy forward-testing baseline', 'SIMULATED_TEST',
                        1, 'MEDIUM', 'MEDIUM', 'Sample size criteria satisfied (38 trades, 46 days)'
                    )
                """)
                # Active Clean Evaluation Cycle (Cycle 2 - Reset Account £50,000 baseline)
                cur.execute("""
                    INSERT INTO ai_performance_cycles (
                        cycle_id, cycle_name, start_date, end_date, status,
                        starting_capital, ending_capital, realised_pnl, unrealised_pnl,
                        total_return, total_return_pct, trade_count, win_count, loss_count,
                        win_rate, max_drawdown, profit_factor, git_commit, ai_version, feature_set, notes, data_source_type,
                        evaluation_eligible, sample_size_classification, confidence_level, evaluation_reason
                    ) VALUES (
                        'CYCLE-002', 'Cycle 2: Autonomous Production Engine v2.0', CURRENT_TIMESTAMP, NULL, 'ACTIVE',
                        50000.0, 50000.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0,
                        0.0, 0.0, 0.0, '07179c6', 'v2.0-lean-fastapi',
                        'Unified Ingress, Single-Daily Executive Report, Strict Broker Parity', 'Clean evaluation cycle initialized after broker reset to £50,000.00', 'LIVE',
                        0, 'LOW', 'LOW', 'Trades Recorded: 0 / 20, Days Running: 0 / 30. More trading evidence required.'
                    )
                """)
            else:
                # Ensure existing historical records have updated validity status
                cur.execute("""
                    UPDATE ai_performance_cycles 
                    SET evaluation_eligible = 1, sample_size_classification = 'MEDIUM', confidence_level = 'MEDIUM',
                        evaluation_reason = 'Sample size criteria satisfied (38 trades, 46 days)'
                    WHERE cycle_id = 'CYCLE-001'
                """)

            # Seed default claims in evidence_registry if empty
            cur.execute("SELECT COUNT(*) as cnt FROM evidence_registry")
            ecnt = cur.fetchone()["cnt"]
            if ecnt == 0:
                cur.execute("""
                    INSERT INTO evidence_registry (
                        claim_id, claim_statement, epistemic_grade, empirical_evidence_summary,
                        sample_size_evaluated, verified_by
                    ) VALUES (
                        'CLAIM-001', 'Net Edge Filter avoids low-expectancy trades', 'GRADE_B',
                        'Validated on out-of-sample replay', 38, 'LEAD_QUANT'
                    )
                """)
            conn.commit()

    # --- Profit Vault ---
    def deposit_profit_vault(self, trade_id: str, symbol: str, realized_profit: float, notes: str = "") -> float:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT cumulative_vault_total FROM profit_vault ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            prev_total = row["cumulative_vault_total"] if row else 0.0
            new_total = prev_total + realized_profit
            cur.execute("""
                INSERT INTO profit_vault (trade_id, symbol, realized_profit, cumulative_vault_total, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (trade_id, symbol, realized_profit, new_total, notes))
            conn.commit()
            return new_total

    def get_vault_balance(self) -> float:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT cumulative_vault_total FROM profit_vault ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return float(row["cumulative_vault_total"]) if row else 0.0

    # --- Trades ---
    def record_trade(self, trade: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cycle_id = trade.get("cycle_id")
            if not cycle_id:
                active_cycle = self.get_active_cycle()
                cycle_id = active_cycle["cycle_id"] if active_cycle else "CYCLE-001"

            cur.execute("""
                INSERT INTO trades (
                    trade_id, symbol, action, quantity, price, total_cost,
                    spread_cost, slippage_cost, fx_cost, net_cost,
                    realized_pnl, confidence_score, reward_risk_ratio, trade_reason, mode, cycle_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("trade_id", f"TRD_{int(datetime.now().timestamp())}"),
                trade["symbol"],
                trade["action"],
                trade["quantity"],
                trade["price"],
                trade["total_cost"],
                trade.get("spread_cost", 0.0),
                trade.get("slippage_cost", 0.0),
                trade.get("fx_cost", 0.0),
                trade.get("net_cost", trade["total_cost"]),
                trade.get("realized_pnl", 0.0),
                trade.get("confidence_score", 0.0),
                trade.get("reward_risk_ratio", 0.0),
                trade.get("trade_reason", ""),
                trade.get("mode", "LIVE"),
                cycle_id
            ))
            conn.commit()

    def get_trades(self, limit: int = 100, cycle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            if cycle_id:
                cur.execute("SELECT * FROM trades WHERE cycle_id = ? ORDER BY id DESC LIMIT ?", (cycle_id, limit))
            else:
                cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Portfolio Snapshots & Historical Equity Curve ---
    def record_portfolio_snapshot(self, snapshot: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cycle_id = snapshot.get("cycle_id")
            if not cycle_id:
                active = self.get_active_cycle()
                cycle_id = active["cycle_id"] if active else "CYCLE-001"
            now_str = snapshot.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
            cur.execute("""
                INSERT INTO portfolio_snapshots (timestamp, nav, cash, invested, unrealized_pnl, realized_pnl, cycle_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                now_str,
                float(snapshot["nav"]),
                float(snapshot.get("cash", snapshot["nav"])),
                float(snapshot.get("invested", 0.0)),
                float(snapshot.get("unrealized_pnl", 0.0)),
                float(snapshot.get("realized_pnl", 0.0)),
                cycle_id
            ))
            conn.commit()

    def get_portfolio_snapshots(self, timeframe: str = "1D", limit: int = 100, cycle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            now = datetime.now(timezone.utc)
            if timeframe == "1D":
                since = now.strftime("%Y-%m-%d 00:00:00")
            elif timeframe == "1W":
                since = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
            elif timeframe == "1M":
                since = (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
            else: # ALL
                since = "2020-01-01 00:00:00"

            if cycle_id:
                cur.execute("""
                    SELECT * FROM portfolio_snapshots 
                    WHERE timestamp >= ? AND cycle_id = ? 
                    ORDER BY timestamp ASC LIMIT ?
                """, (since, cycle_id, limit))
            else:
                cur.execute("""
                    SELECT * FROM portfolio_snapshots 
                    WHERE timestamp >= ? 
                    ORDER BY timestamp ASC LIMIT ?
                """, (since, limit))
            rows = [dict(row) for row in cur.fetchall()]
            return rows

    def get_nav_baseline(self, period: str = "1D", current_nav: float = 50000.0, cycle_id: Optional[str] = None) -> float:
        """
        Fetch true starting NAV for the given period:
        - 1D: Close of previous trading day (snapshot <= today 00:00:00). If none (Day 1), starting capital.
        - 1W: Close of previous week (snapshot <= 7 days ago). If none (Week 1), starting capital.
        - 1M: Close of previous month (snapshot <= 30 days ago). If none (Month 1), starting capital.
        - ALL: Cycle starting capital.
        """
        with self.get_connection() as conn:
            cur = conn.cursor()
            active = self.get_active_cycle()
            starting_cap = float(active.get("starting_capital", current_nav)) if active else current_nav
            
            if period == "ALL":
                if cycle_id:
                    cur.execute("SELECT starting_capital FROM ai_performance_cycles WHERE cycle_id = ?", (cycle_id,))
                    row = cur.fetchone()
                    if row and row["starting_capital"]:
                        return float(row["starting_capital"])
                return starting_cap

            now = datetime.now(timezone.utc)
            if period == "1D":
                since = now.strftime("%Y-%m-%d 00:00:00")
            elif period == "1W":
                since = (now - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
            elif period == "1M":
                since = (now - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
            else:
                since = now.strftime("%Y-%m-%d 00:00:00")

            # Look for the last verified snapshot strictly on or before 'since'
            cur.execute("""
                SELECT nav FROM portfolio_snapshots 
                WHERE timestamp <= ? 
                ORDER BY timestamp DESC LIMIT 1
            """, (since,))
            row = cur.fetchone()
            if row and row["nav"] and float(row["nav"]) > 0:
                return float(row["nav"])

            # If no snapshot exists prior to 'since' (Day 1 of trading or new cycle), baseline is Starting Capital
            return starting_cap

    # --- AI Performance Cycles ---
    def get_active_cycle(self) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_performance_cycles WHERE status = 'ACTIVE' ORDER BY start_date DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_cycles(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_performance_cycles ORDER BY start_date DESC")
            return [dict(row) for row in cur.fetchall()]

    def get_cycle_by_id(self, cycle_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_performance_cycles WHERE cycle_id = ?", (cycle_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def create_cycle(self, cycle_data: Dict[str, Any]) -> str:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_performance_cycles (
                    cycle_id, cycle_name, start_date, end_date, status,
                    starting_capital, ending_capital, realised_pnl, unrealised_pnl,
                    total_return, total_return_pct, trade_count, win_count, loss_count,
                    win_rate, max_drawdown, profit_factor, git_commit, ai_version, feature_set, notes, data_source_type,
                    evaluation_eligible, sample_size_classification, confidence_level, evaluation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cycle_data["cycle_id"],
                cycle_data["cycle_name"],
                cycle_data.get("start_date", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
                cycle_data.get("end_date"),
                cycle_data.get("status", "ACTIVE"),
                float(cycle_data.get("starting_capital", 50000.0)),
                float(cycle_data.get("ending_capital", cycle_data.get("starting_capital", 50000.0))),
                float(cycle_data.get("realised_pnl", 0.0)),
                float(cycle_data.get("unrealised_pnl", 0.0)),
                float(cycle_data.get("total_return", 0.0)),
                float(cycle_data.get("total_return_pct", 0.0)),
                int(cycle_data.get("trade_count", 0)),
                int(cycle_data.get("win_count", 0)),
                int(cycle_data.get("loss_count", 0)),
                float(cycle_data.get("win_rate", 0.0)),
                float(cycle_data.get("max_drawdown", 0.0)),
                float(cycle_data.get("profit_factor", 0.0)),
                cycle_data.get("git_commit", "HEAD"),
                cycle_data.get("ai_version", "v2.0"),
                cycle_data.get("feature_set", ""),
                cycle_data.get("notes", ""),
                cycle_data.get("data_source_type", "LIVE"),
                1 if cycle_data.get("evaluation_eligible") else 0,
                cycle_data.get("sample_size_classification", "LOW"),
                cycle_data.get("confidence_level", "LOW"),
                cycle_data.get("evaluation_reason", "")
            ))
            conn.commit()
            return cycle_data["cycle_id"]

    def update_cycle(self, cycle_id: str, updates: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            set_clauses = []
            values = []
            for k, v in updates.items():
                set_clauses.append(f"{k} = ?")
                values.append(v)
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values.append(cycle_id)
            sql = f"UPDATE ai_performance_cycles SET {', '.join(set_clauses)} WHERE cycle_id = ?"
            cur.execute(sql, tuple(values))
            conn.commit()

    def record_cycle_comparison(self, comp_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_cycle_comparisons (
                    comparison_id, cycle_a, cycle_b, return_delta, win_rate_delta,
                    profit_factor_delta, drawdown_delta, ai_effectiveness_score,
                    classification, comparison_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                comp_data.get("comparison_id", f"CMP_{int(datetime.now().timestamp())}"),
                comp_data["cycle_a"],
                comp_data["cycle_b"],
                float(comp_data.get("return_delta", 0.0)),
                float(comp_data.get("win_rate_delta", 0.0)),
                float(comp_data.get("profit_factor_delta", 0.0)),
                float(comp_data.get("drawdown_delta", 0.0)),
                float(comp_data.get("ai_effectiveness_score", 0.0)),
                comp_data.get("classification", "NEUTRAL"),
                json.dumps(comp_data.get("comparison_json", {}))
            ))
            conn.commit()
            return cur.lastrowid

    def get_recent_comparisons(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_cycle_comparisons ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Audit Logs ---
    def record_audit(self, audit: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO audit_logs (
                    event_type, symbol, market_conditions, agent_votes,
                    confidence_score, trade_reason, risk_approval,
                    position_size, exit_reason, final_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit["event_type"],
                audit.get("symbol"),
                json.dumps(audit.get("market_conditions", {})),
                json.dumps(audit.get("agent_votes", {})),
                audit.get("confidence_score"),
                audit.get("trade_reason"),
                1 if audit.get("risk_approval") else 0,
                audit.get("position_size"),
                audit.get("exit_reason"),
                audit.get("final_result")
            ))
            conn.commit()

    def get_audit_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Risk Events ---
    def record_risk_event(self, event_type: str, severity: str, description: str, portfolio_value: float, action_taken: str):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO risk_events (event_type, severity, description, portfolio_value, action_taken)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, severity, description, portfolio_value, action_taken))
            conn.commit()

    # --- Boardroom & Confidence ---
    def record_boardroom_decision(self, decision: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO boardroom_decisions (
                    symbol, overall_confidence, market_regime,
                    trend_agent_vote, momentum_agent_vote, volatility_agent_vote,
                    liquidity_agent_vote, risk_agent_vote, approved, reasoning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision["symbol"],
                decision["overall_confidence"],
                decision["market_regime"],
                decision.get("trend_agent_vote", "HOLD"),
                decision.get("momentum_agent_vote", "HOLD"),
                decision.get("volatility_agent_vote", "HOLD"),
                decision.get("liquidity_agent_vote", "HOLD"),
                decision.get("risk_agent_vote", "HOLD"),
                1 if decision.get("approved") else 0,
                decision.get("reasoning", "")
            ))
            conn.commit()

    # --- Catalyst Events ---
    def record_catalyst_event(self, event: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO catalyst_events (
                    event_id, timestamp, source, category, ticker, sector, headline,
                    sentiment_score, importance_score, confidence_score, catalyst_score,
                    deployment_flag, trade_outcome
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.get("event_id", f"cat_{int(datetime.now().timestamp())}"),
                event.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                event.get("source", "GENERAL"),
                event.get("category", "MARKET"),
                event.get("ticker", "SPY"),
                event.get("sector", "General"),
                event.get("headline", ""),
                float(event.get("sentiment_score", 0.0)),
                float(event.get("importance_score", 0.0)),
                float(event.get("confidence_score", 0.0)),
                float(event.get("catalyst_score", 0.0)),
                1 if event.get("deployment_flag") else 0,
                event.get("trade_outcome", "MONITORING")
            ))
            conn.commit()
            return cur.lastrowid

    def get_catalyst_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM catalyst_events ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Catalyst Shadow Paper Trades ---
    def record_catalyst_paper_trade(self, trade: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO catalyst_paper_trades (
                    paper_trade_id, event_id, timestamp, ticker, sector, catalyst_type,
                    catalyst_score, entry_price, current_price,
                    return_1d, return_5d, return_10d, return_30d,
                    benchmark_return_1d, benchmark_return_5d, benchmark_return_10d, benchmark_return_30d,
                    alpha_vs_baseline, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("paper_trade_id", f"ptrade_{int(datetime.now().timestamp())}"),
                trade.get("event_id", ""),
                trade.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                trade.get("ticker", "SPY"),
                trade.get("sector", "General"),
                trade.get("catalyst_type", "MACRO_POLICY"),
                float(trade.get("catalyst_score", 0.0)),
                float(trade.get("entry_price", 100.0)),
                float(trade.get("current_price", 100.0)),
                trade.get("return_1d"),
                trade.get("return_5d"),
                trade.get("return_10d"),
                trade.get("return_30d"),
                trade.get("benchmark_return_1d"),
                trade.get("benchmark_return_5d"),
                trade.get("benchmark_return_10d"),
                trade.get("benchmark_return_30d"),
                trade.get("alpha_vs_baseline", 0.0),
                trade.get("status", "ACTIVE")
            ))
            conn.commit()
            return cur.lastrowid

    def get_catalyst_paper_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM catalyst_paper_trades ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def save_daily_executive_report(self, report_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            report_date = report_data.get("report_date", datetime.utcnow().strftime("%Y-%m-%d"))
            cur.execute("""
                INSERT INTO daily_executive_reports (
                    report_date, report_json, nav, daily_pnl, trades_opened_count, trades_closed_count, compliance_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    report_json = excluded.report_json,
                    nav = excluded.nav,
                    daily_pnl = excluded.daily_pnl,
                    trades_opened_count = excluded.trades_opened_count,
                    trades_closed_count = excluded.trades_closed_count,
                    compliance_status = excluded.compliance_status,
                    created_at = CURRENT_TIMESTAMP
            """, (
                report_date,
                json.dumps(report_data),
                float(report_data.get("portfolio_summary", {}).get("nav", 0.0) or 0.0),
                float(report_data.get("daily_pnl", {}).get("gbp", 0.0) or 0.0),
                int(len(report_data.get("trades_opened", []))),
                int(len(report_data.get("trades_closed", []))),
                str(report_data.get("compliance_events", {}).get("status", "PASS"))
            ))
            conn.commit()
            return cur.lastrowid

    def get_latest_daily_executive_report(self, report_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            if report_date:
                cur.execute("SELECT report_json FROM daily_executive_reports WHERE report_date = ? ORDER BY id DESC LIMIT 1", (report_date,))
            else:
                cur.execute("SELECT report_json FROM daily_executive_reports ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row and row["report_json"]:
                return json.loads(row["report_json"])
            return None

    def get_daily_executive_reports_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, report_date, nav, daily_pnl, trades_opened_count, trades_closed_count, compliance_status, created_at FROM daily_executive_reports ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Data Integrity & Broker Parity Logging ---
    def record_data_integrity_alert(self, alert_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO data_integrity_alerts (
                    alert_type, severity, broker_nav, api_nav, dashboard_nav,
                    variance, status, message, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert_data.get("alert_type", "DATA_INTEGRITY_ALERT"),
                alert_data.get("severity", "CRITICAL"),
                float(alert_data.get("broker_nav", 0.0)),
                float(alert_data.get("api_nav", 0.0)),
                float(alert_data.get("dashboard_nav", 0.0)) if alert_data.get("dashboard_nav") is not None else None,
                float(alert_data.get("variance", 0.0)),
                alert_data.get("status", "MISMATCH_DETECTED"),
                alert_data.get("message", "Broker NAV desynchronization detected"),
                json.dumps(alert_data.get("metadata", {}))
            ))
            conn.commit()
            return cur.lastrowid

    def get_recent_data_integrity_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_integrity_alerts ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def record_broker_sync_event(self, sync_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO evidence_broker_sync (
                    broker_nav, internal_nav, nav_discrepancy_pct,
                    open_positions_broker, open_positions_internal, status
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                float(sync_data.get("broker_nav", 0.0)),
                float(sync_data.get("internal_nav", 0.0)),
                float(sync_data.get("nav_discrepancy_pct", 0.0)),
                int(sync_data.get("open_positions_broker", 0)),
                int(sync_data.get("open_positions_internal", 0)),
                sync_data.get("status", "SYNCED")
            ))
            conn.commit()
            return cur.lastrowid

    def get_latest_broker_sync_event(self) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM evidence_broker_sync ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Research Prediction Scoreboard Methods ---
    def record_research_prediction(self, pred: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO research_predictions (
                    prediction_id, symbol, entry_timestamp, universe_rank,
                    expected_value_pct, predicted_win_probability, expected_return_pct,
                    expected_holding_period_days, catalyst_type, catalyst_description,
                    investment_thesis, invalidation_criteria, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pred.get("prediction_id"),
                pred.get("symbol"),
                pred.get("entry_timestamp", datetime.now(timezone.utc).isoformat()),
                int(pred.get("universe_rank", 1)),
                float(pred.get("expected_value_pct", 5.0)),
                float(pred.get("predicted_win_probability", 75.0)),
                float(pred.get("expected_return_pct", 7.50)),
                float(pred.get("expected_holding_period_days", 10.0)),
                pred.get("catalyst_type", "EARNINGS"),
                pred.get("catalyst_description", ""),
                pred.get("investment_thesis", ""),
                pred.get("invalidation_criteria", ""),
                pred.get("status", "OPEN"),
                pred.get("notes", "")
            ))
            conn.commit()
            return cur.lastrowid

    def close_research_prediction(self, symbol: str, outcome_data: Dict[str, Any]) -> bool:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE research_predictions
                SET status = 'CLOSED',
                    exit_timestamp = ?,
                    actual_return_pct = ?,
                    actual_alpha_vs_benchmark = ?,
                    benchmark_name = ?,
                    outcome = ?,
                    exit_reason = ?,
                    thesis_correct = ?,
                    notes = ?
                WHERE symbol = ? AND status = 'OPEN'
            """, (
                outcome_data.get("exit_timestamp", datetime.now(timezone.utc).isoformat()),
                float(outcome_data.get("actual_return_pct", 0.0)),
                float(outcome_data.get("actual_alpha_vs_benchmark", 0.0)),
                outcome_data.get("benchmark_name", "S&P 500"),
                outcome_data.get("outcome", "WIN" if float(outcome_data.get("actual_return_pct", 0.0)) > 0 else "LOSS"),
                outcome_data.get("exit_reason", ""),
                1 if outcome_data.get("thesis_correct") else 0,
                outcome_data.get("notes", ""),
                symbol
            ))
            conn.commit()
            return cur.rowcount > 0

    def get_research_predictions(self, limit: int = 500, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            if status:
                cur.execute("SELECT * FROM research_predictions WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
            else:
                cur.execute("SELECT * FROM research_predictions ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def get_open_research_prediction(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM research_predictions WHERE symbol = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1", (symbol,))
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Phase 3 Production Platform Methods ---
    def record_trade_postmortem(self, pm: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trade_postmortems (
                    trade_id, symbol, entry_timestamp, exit_timestamp,
                    prediction_summary, actual_outcome, actual_return_pct,
                    forecast_error_pct, thesis_accuracy_score, catalyst_accuracy_score,
                    alpha_generated_pct, lessons_learned, regime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pm.get("trade_id", f"TR-{uuid.uuid4().hex[:6]}"),
                pm.get("symbol"),
                pm.get("entry_timestamp", datetime.now(timezone.utc).isoformat()),
                pm.get("exit_timestamp", datetime.now(timezone.utc).isoformat()),
                pm.get("prediction_summary", ""),
                pm.get("actual_outcome", "WIN"),
                float(pm.get("actual_return_pct", 0.0)),
                float(pm.get("forecast_error_pct", 0.0)),
                float(pm.get("thesis_accuracy_score", 10.0)),
                float(pm.get("catalyst_accuracy_score", 10.0)),
                float(pm.get("alpha_generated_pct", 0.0)),
                pm.get("lessons_learned", ""),
                pm.get("regime", "MILD_BULL")
            ))
            conn.commit()
            return cur.lastrowid

    def get_trade_postmortems(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trade_postmortems ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def record_thesis_success(self, ts: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO thesis_success_records (
                    thesis_id, symbol, thesis_type, original_thesis, catalyst,
                    entry_rank, entry_ev, entry_probability, exit_outcome,
                    alpha_generated_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts.get("thesis_id", f"TH-{uuid.uuid4().hex[:6]}"),
                ts.get("symbol"),
                ts.get("thesis_type", "BIOPHARMACEUTICAL_INNOVATION"),
                ts.get("original_thesis", ""),
                ts.get("catalyst", ""),
                int(ts.get("entry_rank", 1)),
                float(ts.get("entry_ev", 5.0)),
                float(ts.get("entry_probability", 75.0)),
                ts.get("exit_outcome", "WIN"),
                float(ts.get("alpha_generated_pct", 0.0))
            ))
            conn.commit()
            return cur.lastrowid

    def get_thesis_success_records(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM thesis_success_records ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def record_portfolio_evolution_snapshot(self, snap: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO portfolio_evolution_snapshots (
                    portfolio_health, live_evidence_score, cumulative_alpha_sp500,
                    capital_efficiency_score, research_accuracy_pct, nav,
                    completed_trades_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                float(snap.get("portfolio_health", 74.3)),
                float(snap.get("live_evidence_score", 12.5)),
                float(snap.get("cumulative_alpha_sp500", -3.80)),
                float(snap.get("capital_efficiency_score", 62.5)),
                float(snap.get("research_accuracy_pct", 74.0)),
                float(snap.get("nav", 49821.67)),
                int(snap.get("completed_trades_count", 0))
            ))
            conn.commit()
            return cur.lastrowid

    def get_portfolio_evolution_history(self, limit: int = 365) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_evolution_snapshots ORDER BY timestamp ASC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Pre-Market Production Readiness Gate Methods ---
    def record_readiness_check(self, check: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO premarket_readiness_checks (
                    overall_status, infrastructure_status, broker_status,
                    data_status, research_status, phase2_status,
                    phase4_status, phase5_status, reporting_status,
                    details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                check.get("overall_status", "READY FOR TRADING"),
                check.get("infrastructure_status", "PASS"),
                check.get("broker_status", "PASS"),
                check.get("data_status", "PASS"),
                check.get("research_status", "PASS"),
                check.get("phase2_status", "PASS"),
                check.get("phase4_status", "PASS"),
                check.get("phase5_status", "PASS"),
                check.get("reporting_status", "PASS"),
                json.dumps(check.get("details", {}))
            ))
            conn.commit()
            return cur.lastrowid

    def get_latest_readiness_check(self) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM premarket_readiness_checks ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

    def get_readiness_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM premarket_readiness_checks ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Shadow Portfolio Comparison Methods ---
    def record_shadow_comparison(self, comp: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO shadow_portfolio_comparisons (
                    portfolio_a_return_pct, portfolio_a_alpha_sp500, portfolio_a_drawdown_pct, portfolio_a_ev_pct,
                    portfolio_b_return_pct, portfolio_b_alpha_sp500, portfolio_b_drawdown_pct, portfolio_b_ev_pct,
                    spread_return_pct, spread_ev_pct, opportunity_cost_gbp, opportunity_cost_bps,
                    winning_portfolio, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                float(comp.get("portfolio_a_return_pct", -0.35)),
                float(comp.get("portfolio_a_alpha_sp500", -3.80)),
                float(comp.get("portfolio_a_drawdown_pct", 0.35)),
                float(comp.get("portfolio_a_ev_pct", 5.03)),
                float(comp.get("portfolio_b_return_pct", 0.75)),
                float(comp.get("portfolio_b_alpha_sp500", -2.69)),
                float(comp.get("portfolio_b_drawdown_pct", 0.18)),
                float(comp.get("portfolio_b_ev_pct", 5.44)),
                float(comp.get("spread_return_pct", 1.10)),
                float(comp.get("spread_ev_pct", 0.41)),
                float(comp.get("opportunity_cost_gbp", 548.94)),
                float(comp.get("opportunity_cost_bps", 110.0)),
                str(comp.get("winning_portfolio", "PORTFOLIO B (SHADOW IDEAL)")),
                json.dumps(comp.get("details", {}))
            ))
            conn.commit()
            return cur.lastrowid

    def get_latest_shadow_comparison(self) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM shadow_portfolio_comparisons ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

    def get_shadow_comparison_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM shadow_portfolio_comparisons ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Shadow Promotion Candidates Methods ---
    def record_shadow_promotion_candidate(self, cand: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO shadow_promotion_candidates (
                    candidate_symbol, replace_symbol, days_winning,
                    candidate_return_pct, held_return_pct, excess_return_pct,
                    opportunity_gain_gbp, promotion_score, promotion_eligible,
                    eligibility_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cand.get("candidate_symbol", "CRM"),
                cand.get("replace_symbol", "PM"),
                cand.get("days_winning", 1),
                float(cand.get("candidate_return_pct", 1.45)),
                float(cand.get("held_return_pct", -0.26)),
                float(cand.get("excess_return_pct", 1.71)),
                float(cand.get("opportunity_gain_gbp", 47.03)),
                float(cand.get("promotion_score", 53.8)),
                cand.get("promotion_eligible", "IN_PROGRESS"),
                cand.get("eligibility_reason", "Tracking Day 1/20")
            ))
            conn.commit()
            return cur.lastrowid

    def get_shadow_promotion_candidates(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM shadow_promotion_candidates ORDER BY promotion_score DESC")
            return [dict(row) for row in cur.fetchall()]

    # --- Macro Event Ledger Methods ---
    def record_macro_assessment(self, assessment: Dict[str, Any]) -> bool:
        """
        Stores macro impact gate evaluation results in the permanent Macro Event Ledger.
        """
        eval_date = assessment.get("evaluation_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        events = assessment.get("events", [])
        raw_json = json.dumps(assessment)

        with self.get_connection() as conn:
            cur = conn.cursor()
            for ev in events:
                holdings_str = ",".join(ev.get("affected_holdings", [])) if isinstance(ev.get("affected_holdings"), list) else str(ev.get("affected_holdings", ""))
                cur.execute("""
                    INSERT INTO macro_event_ledger (
                        evaluation_date, event_id, category, event_name,
                        portfolio_exposure, affected_holdings, direct_impact,
                        indirect_impact, risk_level, expected_effect,
                        mitigation_action, source_classification, publisher,
                        source_url, published_at, retrieved_at, is_last_24h,
                        confidence_score, raw_headline, raw_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    eval_date,
                    ev.get("event_id", "UNKNOWN"),
                    ev.get("category", "MACRO"),
                    ev.get("event_name", ev.get("headline", "")),
                    ev.get("portfolio_exposure", "LOW"),
                    holdings_str,
                    ev.get("direct_impact", ""),
                    ev.get("indirect_impact", ""),
                    ev.get("risk_level", "LOW"),
                    ev.get("expected_effect", ""),
                    ev.get("mitigation_action", ""),
                    ev.get("source_classification", "LIVE NEWS"),
                    ev.get("publisher", "Reuters"),
                    ev.get("source_url", ""),
                    ev.get("published_at", ""),
                    ev.get("retrieved_at", datetime.now().strftime("%Y-%m-%d %H:%M %Z")),
                    1 if ev.get("is_last_24h", True) else 0,
                    float(ev.get("confidence_score", 90.0)),
                    ev.get("raw_headline", ""),
                    raw_json
                ))
            conn.commit()
            return True

    def get_latest_macro_assessment(self, date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves the most recent macro assessment payload.
        """
        with self.get_connection() as conn:
            cur = conn.cursor()
            if date_str:
                cur.execute("SELECT raw_payload FROM macro_event_ledger WHERE evaluation_date = ? ORDER BY id DESC LIMIT 1", (date_str,))
            else:
                cur.execute("SELECT raw_payload FROM macro_event_ledger ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except Exception:
                    return None
            return None

    def get_macro_ledger_entries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves recent entries from the Macro Event Ledger.
        """
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM macro_event_ledger ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Reconciliation Ledger Methods ---
    def record_reconciliation_event(self, recon_data: Dict[str, Any]) -> int:
        """Stores daily balance sheet reconciliation invariant verification."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO reconciliation_ledger (
                    report_date, status, total_nav, free_cash, invested_capital,
                    positions_sum, nav_variance, invested_variance, position_count,
                    broker_position_count, failed_invariants, reconciliation_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recon_data.get("report_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                recon_data.get("status", "VERIFIED"),
                float(recon_data.get("total_nav", 0.0)),
                float(recon_data.get("free_cash", 0.0)),
                float(recon_data.get("invested_capital", 0.0)),
                float(recon_data.get("positions_sum", 0.0)),
                float(recon_data.get("nav_variance", 0.0)),
                float(recon_data.get("invested_variance", 0.0)),
                int(recon_data.get("position_count", 0)),
                int(recon_data.get("broker_position_count", 0)),
                json.dumps(recon_data.get("failed_invariants", [])),
                json.dumps(recon_data.get("reconciliation_details", {}))
            ))
            conn.commit()
            return cur.lastrowid

    def get_latest_reconciliation_event(self, date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            if date_str:
                cur.execute("SELECT * FROM reconciliation_ledger WHERE report_date = ? ORDER BY id DESC LIMIT 1", (date_str,))
            else:
                cur.execute("SELECT * FROM reconciliation_ledger ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                d = dict(row)
                try:
                    d["failed_invariants"] = json.loads(d.get("failed_invariants") or "[]")
                    d["reconciliation_details"] = json.loads(d.get("reconciliation_details") or "{}")
                except Exception:
                    pass
                return d
            return None

    # --- Order Telemetry Methods ---
    def record_order_telemetry(self, t_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO order_telemetry (
                    signal_timestamp, symbol, exchange, action, signal_price,
                    bid_at_signal, ask_at_signal, spread_bps, requested_price,
                    submitted_price, fill_price, quantity, partial_fill_quantity,
                    latency_ms, slippage_bps, time_to_fill_sec, order_type, status,
                    decision_price, arrival_price, delay_cost_bps, spread_cost_bps,
                    market_impact_bps, implementation_shortfall_bps, implementation_shortfall_gbp,
                    chase_attempts, cancellation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t_data.get("signal_timestamp", datetime.now(timezone.utc).isoformat()),
                t_data.get("symbol", "UNKNOWN"),
                t_data.get("exchange", "LSE"),
                t_data.get("action", "BUY"),
                float(t_data.get("signal_price", 0.0)),
                float(t_data.get("bid_at_signal", 0.0)) if t_data.get("bid_at_signal") else None,
                float(t_data.get("ask_at_signal", 0.0)) if t_data.get("ask_at_signal") else None,
                float(t_data.get("spread_bps", 0.0)) if t_data.get("spread_bps") else None,
                float(t_data.get("requested_price", 0.0)),
                float(t_data.get("submitted_price", 0.0)),
                float(t_data.get("fill_price", 0.0)),
                float(t_data.get("quantity", 0.0)),
                float(t_data.get("partial_fill_quantity", 0.0)),
                float(t_data.get("latency_ms", 0.0)) if t_data.get("latency_ms") else None,
                float(t_data.get("slippage_bps", 0.0)) if t_data.get("slippage_bps") else None,
                float(t_data.get("time_to_fill_sec", 0.0)) if t_data.get("time_to_fill_sec") else None,
                t_data.get("order_type", "MARKETABLE_LIMIT"),
                t_data.get("status", "FILLED"),
                float(t_data.get("decision_price", 0.0)) if t_data.get("decision_price") else None,
                float(t_data.get("arrival_price", 0.0)) if t_data.get("arrival_price") else None,
                float(t_data.get("delay_cost_bps", 0.0)) if t_data.get("delay_cost_bps") else None,
                float(t_data.get("spread_cost_bps", 0.0)) if t_data.get("spread_cost_bps") else None,
                float(t_data.get("market_impact_bps", 0.0)) if t_data.get("market_impact_bps") else None,
                float(t_data.get("implementation_shortfall_bps", 0.0)) if t_data.get("implementation_shortfall_bps") else None,
                float(t_data.get("implementation_shortfall_gbp", 0.0)) if t_data.get("implementation_shortfall_gbp") else None,
                int(t_data.get("chase_attempts", 0)),
                t_data.get("cancellation_reason")
            ))
            conn.commit()
            return cur.lastrowid

    def get_order_telemetry_entries(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM order_telemetry ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cur.fetchall()]

    # --- Shadow Strategy Ledger Methods ---
    def record_shadow_strategy_metrics(self, strat_data: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO shadow_strategy_ledger (
                    evaluation_date, strategy_id, strategy_name, nav,
                    gross_pnl, total_costs, net_pnl, net_expectancy,
                    profit_factor, win_rate, payoff_ratio, cost_to_gross_profit_ratio,
                    trade_count, avg_holding_period_days, max_drawdown, mfe_avg,
                    mae_avg, sharpe_ratio, capital_employed_avg, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                strat_data.get("evaluation_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                strat_data.get("strategy_id", "STRATEGY_A"),
                strat_data.get("strategy_name", "Baseline"),
                float(strat_data.get("nav", 50000.0)),
                float(strat_data.get("gross_pnl", 0.0)),
                float(strat_data.get("total_costs", 0.0)),
                float(strat_data.get("net_pnl", 0.0)),
                float(strat_data.get("net_expectancy", 0.0)),
                float(strat_data.get("profit_factor", 0.0)),
                float(strat_data.get("win_rate", 0.0)),
                float(strat_data.get("payoff_ratio", 0.0)),
                float(strat_data.get("cost_to_gross_profit_ratio", 0.0)),
                int(strat_data.get("trade_count", 0)),
                float(strat_data.get("avg_holding_period_days", 0.0)),
                float(strat_data.get("max_drawdown", 0.0)),
                float(strat_data.get("mfe_avg", 0.0)),
                float(strat_data.get("mae_avg", 0.0)),
                float(strat_data.get("sharpe_ratio", 0.0)),
                float(strat_data.get("capital_employed_avg", 0.0)),
                strat_data.get("status", "ACTIVE")
            ))
            conn.commit()
            return cur.lastrowid

    def get_shadow_strategy_ledger(self, eval_date: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            if eval_date:
                cur.execute("SELECT * FROM shadow_strategy_ledger WHERE evaluation_date = ? ORDER BY strategy_id ASC", (eval_date,))
            else:
                cur.execute("SELECT * FROM shadow_strategy_ledger ORDER BY id DESC LIMIT 20")
            return [dict(row) for row in cur.fetchall()]

db = Database()






