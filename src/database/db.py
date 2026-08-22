import sqlite3
import json
from datetime import datetime
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
    ai_effectiveness_score REAL NOT NULL,
    classification TEXT NOT NULL,
    comparison_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
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

            # 4. Seed initial cycles if ai_performance_cycles is empty
            cur.execute("SELECT COUNT(*) as cnt FROM ai_performance_cycles")
            cnt = cur.fetchone()["cnt"]
            if cnt == 0:
                # Historical Baseline (Cycle 1 - Archived with the 38 previous test trades)
                cur.execute("""
                    INSERT INTO ai_performance_cycles (
                        cycle_id, cycle_name, start_date, end_date, status,
                        starting_capital, ending_capital, realised_pnl, unrealised_pnl,
                        total_return, total_return_pct, trade_count, win_count, loss_count,
                        win_rate, max_drawdown, profit_factor, git_commit, ai_version, feature_set, notes, data_source_type
                    ) VALUES (
                        'CYCLE-001', 'Phase 47 Forward-Test Baseline', '2026-07-07 15:30:00', '2026-08-22 16:00:00', 'ARCHIVED',
                        50000.0, 49800.53, -199.47, 0.0, -199.47, -0.40, 38, 4, 34,
                        10.5, 2.18, 0.11, '07179c6', 'v1.0-forward-test',
                        'Phase 47 ATR Stop & Breakeven Rules', 'Archived legacy forward-testing baseline', 'SIMULATED_TEST'
                    )
                """)
                # Active Clean Evaluation Cycle (Cycle 2 - Reset Account £50,000 baseline)
                cur.execute("""
                    INSERT INTO ai_performance_cycles (
                        cycle_id, cycle_name, start_date, end_date, status,
                        starting_capital, ending_capital, realised_pnl, unrealised_pnl,
                        total_return, total_return_pct, trade_count, win_count, loss_count,
                        win_rate, max_drawdown, profit_factor, git_commit, ai_version, feature_set, notes, data_source_type
                    ) VALUES (
                        'CYCLE-002', 'Cycle 2: Autonomous Production Engine v2.0', CURRENT_TIMESTAMP, NULL, 'ACTIVE',
                        50000.0, 50000.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0,
                        0.0, 0.0, 0.0, '07179c6', 'v2.0-lean-fastapi',
                        'Unified Ingress, Single-Daily Executive Report, Strict Broker Parity', 'Clean evaluation cycle initialized after broker reset to £50,000.00', 'LIVE'
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
                    win_rate, max_drawdown, profit_factor, git_commit, ai_version, feature_set, notes, data_source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                cycle_data.get("data_source_type", "LIVE")
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
                float(report_data.get("portfolio_summary", {}).get("nav", 49998.0)),
                float(report_data.get("daily_pnl", {}).get("gbp", 0.0)),
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

db = Database()

