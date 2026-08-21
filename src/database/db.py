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
"""

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DB_PATH
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            conn.executescript(CREATE_TABLES_SQL)
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

db = Database()
