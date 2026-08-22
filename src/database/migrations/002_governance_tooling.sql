-- =============================================================================
-- Migration 002: Institutional Governance, Attribution, Regime & Trajectory Schema
-- Database: SQLite3 (prv_capital.db)
-- =============================================================================
BEGIN TRANSACTION;

-- 1. Symbol Quarantine & 10-Day Cooldown Registry
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
CREATE INDEX IF NOT EXISTS idx_cooldown_sym_status ON symbol_cooldowns(symbol, status);

-- 2. Daily Market Regime State History
CREATE TABLE IF NOT EXISTS market_regimes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    spy_close REAL NOT NULL,
    spy_sma20 REAL NOT NULL,
    spy_sma50 REAL NOT NULL,
    spy_sma200 REAL NOT NULL,
    vix_level REAL NOT NULL,
    regime_classification TEXT NOT NULL CHECK (
        regime_classification IN ('STRONG_BULL', 'MILD_BULL', 'SIDEWAYS', 'MILD_BEAR', 'STRONG_BEAR')
    ),
    risk_capacity_pct REAL NOT NULL,
    trading_permission TEXT NOT NULL CHECK (
        trading_permission IN ('FULL_TRADING', 'RESTRICTED_TRADING', 'CASH_PRESERVATION_HALT')
    ),
    diagnostic_rationale TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_regime_date ON market_regimes(date);

-- 3. Epistemic Research Evidence Ledger
CREATE TABLE IF NOT EXISTS evidence_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL UNIQUE,
    claim_statement TEXT NOT NULL,
    epistemic_grade TEXT NOT NULL CHECK (epistemic_grade IN ('PROVEN', 'SUPPORTED', 'HYPOTHESIS')),
    empirical_evidence_summary TEXT NOT NULL,
    sample_size_evaluated INTEGER NOT NULL,
    verified_by TEXT NOT NULL,
    last_audit_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 4. Trade Attribution Engine Table
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
    root_cause_category TEXT NOT NULL CHECK (
        root_cause_category IN (
            'AI_LATENCY',
            'STOP_COLLISION',
            'REPEAT_ENTRY',
            'MARKET_REGIME',
            'EARNINGS_EVENT',
            'SLIPPAGE',
            'CLEAN_WINNER',
            'OTHER'
        )
    ),
    attribution_confidence REAL NOT NULL,
    forensic_notes TEXT NOT NULL,
    classified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);
CREATE INDEX IF NOT EXISTS idx_attr_cat ON trade_attributions(root_cause_category);

-- 5. MFE / MAE Trajectory Tracking Table
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
    trajectory_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

-- Seed Initial Research Claims
INSERT OR REPLACE INTO evidence_registry (claim_id, claim_statement, epistemic_grade, empirical_evidence_summary, sample_size_evaluated, verified_by)
VALUES 
('CLM-001', 'Baseline -2.5% static stop produces unviable PF (0.11)', 'PROVEN', 'Observed in 38 live trades on Trading 212 broker ledger.', 38, 'External Audit (Phase 51)'),
('CLM-002', 'Position sizing at 5.53% preserves >96% capital across 35 losses', 'PROVEN', 'Realized maximum peak drawdown restricted to 1.64%.', 38, 'Risk Directorate'),
('CLM-003', 'Broker parity achieves 0.00% desync across all live fills', 'PROVEN', 'Zero ledger discrepancies on Trading 212 API.', 38, 'Chief Systems Architect'),
('CLM-004', 'Synchronous AI quorum introduced 5.0-day entry timing latency', 'SUPPORTED', 'In-sample historical candle reconstruction across 38 trades.', 38, 'Quantitative Research'),
('CLM-005', '10-day cooldown eliminates 5 repeat losses without cutting wins', 'SUPPORTED', 'In-sample historical trade ablation analysis.', 38, 'Quantitative Research'),
('CLM-006', 'Redesigned Phase 47 architecture will produce PF >= 1.25 in live trading', 'HYPOTHESIS', 'Awaiting Phase 47 forward live validation across Trades #51–#80.', 0, 'Investment Committee');

COMMIT;
