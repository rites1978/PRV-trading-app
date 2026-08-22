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
            # Automatic schema migration for existing SQLite databases
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(catalyst_paper_trades)")
            cols = [r["name"] for r in cur.fetchall()]
            if cols and "catalyst_type" not in cols:
                cur.execute("ALTER TABLE catalyst_paper_trades ADD COLUMN catalyst_type TEXT NOT NULL DEFAULT 'MACRO_POLICY'")
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
            cur.execute("""
                INSERT INTO trades (
                    trade_id, symbol, action, quantity, price, total_cost,
                    spread_cost, slippage_cost, fx_cost, net_cost,
                    realized_pnl, confidence_score, reward_risk_ratio, trade_reason, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                trade.get("mode", "LIVE")
            ))
            conn.commit()

    def get_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
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

