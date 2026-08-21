import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.config.settings import settings

EVIDENCE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS evidence_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    date TEXT UNIQUE,
    starting_nav REAL NOT NULL,
    current_nav REAL NOT NULL,
    core_capital REAL NOT NULL,
    active_capital REAL NOT NULL,
    idle_cash REAL NOT NULL,
    vault_balance REAL NOT NULL,
    deployment_pct REAL NOT NULL,
    daily_pnl REAL NOT NULL,
    daily_pnl_pct REAL NOT NULL,
    drawdown_pct REAL NOT NULL,
    peak_nav REAL NOT NULL,
    open_positions_count INTEGER NOT NULL,
    market_regime TEXT NOT NULL,
    profit_factor REAL DEFAULT 0,
    win_rate REAL DEFAULT 0,
    completed_trades_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS evidence_trade_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    trade_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    t212_ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL DEFAULT 0,
    position_cost REAL NOT NULL,
    stop_loss_price REAL,
    take_profit_price REAL,
    spread_cost REAL DEFAULT 0,
    slippage_cost REAL DEFAULT 0,
    fx_cost REAL DEFAULT 0,
    total_friction REAL DEFAULT 0,
    gross_pnl REAL DEFAULT 0,
    net_pnl REAL DEFAULT 0,
    net_return_pct REAL DEFAULT 0,
    exit_reason TEXT,
    hold_duration_hours REAL DEFAULT 0,
    mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    symbol TEXT NOT NULL,
    market_regime TEXT NOT NULL,
    technical_score REAL NOT NULL,
    fundamental_score REAL NOT NULL,
    sector_score REAL NOT NULL,
    sentiment_score REAL NOT NULL,
    composite_alpha REAL NOT NULL,
    target_position_pct REAL NOT NULL,
    reward_risk_ratio REAL NOT NULL,
    status TEXT NOT NULL, -- 'APPROVED' or 'REJECTED'
    rejection_reason TEXT,
    boardroom_votes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_regime_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    previous_regime TEXT,
    new_regime TEXT NOT NULL,
    sp500_adx REAL,
    market_breadth_score REAL,
    target_deployment_pct REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS evidence_kill_switch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    trigger_type TEXT NOT NULL, -- 'DRAWDOWN', 'PROFIT_FACTOR', 'DESYNC', 'ORDER_ERROR'
    severity TEXT NOT NULL,
    current_value REAL NOT NULL,
    threshold REAL NOT NULL,
    action_taken TEXT NOT NULL,
    alert_sent INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS evidence_broker_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    broker_nav REAL NOT NULL,
    internal_nav REAL NOT NULL,
    nav_discrepancy_pct REAL NOT NULL,
    open_positions_broker INTEGER NOT NULL,
    open_positions_internal INTEGER NOT NULL,
    status TEXT NOT NULL -- 'SYNCED', 'DESYNC_WARNING', 'DESYNC_CRITICAL'
);
"""

class EvidenceRecorder:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DB_PATH
        self._init_evidence_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_evidence_db(self):
        with self.get_connection() as conn:
            conn.executescript(EVIDENCE_TABLES_SQL)
            conn.commit()

    def record_daily_snapshot(self, snapshot: Dict[str, Any]):
        today_str = datetime.now().strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO evidence_daily_snapshots (
                    date, starting_nav, current_nav, core_capital, active_capital,
                    idle_cash, vault_balance, deployment_pct, daily_pnl, daily_pnl_pct,
                    drawdown_pct, peak_nav, open_positions_count, market_regime,
                    profit_factor, win_rate, completed_trades_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    current_nav=excluded.current_nav,
                    core_capital=excluded.core_capital,
                    active_capital=excluded.active_capital,
                    idle_cash=excluded.idle_cash,
                    vault_balance=excluded.vault_balance,
                    deployment_pct=excluded.deployment_pct,
                    daily_pnl=excluded.daily_pnl,
                    daily_pnl_pct=excluded.daily_pnl_pct,
                    drawdown_pct=excluded.drawdown_pct,
                    peak_nav=excluded.peak_nav,
                    open_positions_count=excluded.open_positions_count,
                    market_regime=excluded.market_regime,
                    profit_factor=excluded.profit_factor,
                    win_rate=excluded.win_rate,
                    completed_trades_count=excluded.completed_trades_count
            """, (
                today_str,
                snapshot.get("starting_nav", 50000.0),
                snapshot.get("current_nav", 50000.0),
                snapshot.get("core_capital", 50000.0),
                snapshot.get("active_capital", 0.0),
                snapshot.get("idle_cash", 50000.0),
                snapshot.get("vault_balance", 0.0),
                snapshot.get("deployment_pct", 0.0),
                snapshot.get("daily_pnl", 0.0),
                snapshot.get("daily_pnl_pct", 0.0),
                snapshot.get("drawdown_pct", 0.0),
                snapshot.get("peak_nav", 50000.0),
                snapshot.get("open_positions_count", 0),
                snapshot.get("market_regime", "BULL"),
                snapshot.get("profit_factor", 0.0),
                snapshot.get("win_rate", 0.0),
                snapshot.get("completed_trades_count", 0)
            ))
            conn.commit()

    def record_signal(self, signal_data: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO evidence_signals (
                    symbol, market_regime, technical_score, fundamental_score,
                    sector_score, sentiment_score, composite_alpha, target_position_pct,
                    reward_risk_ratio, status, rejection_reason, boardroom_votes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_data.get("symbol"),
                signal_data.get("market_regime", "BULL"),
                signal_data.get("technical_score", 0.0),
                signal_data.get("fundamental_score", 50.0),
                signal_data.get("sector_score", 50.0),
                signal_data.get("sentiment_score", 50.0),
                signal_data.get("composite_alpha", 50.0),
                signal_data.get("target_position_pct", 0.05),
                signal_data.get("reward_risk_ratio", 3.0),
                signal_data.get("status", "APPROVED"),
                signal_data.get("rejection_reason", ""),
                json.dumps(signal_data.get("boardroom_votes", {}))
            ))
            conn.commit()

    def record_trade_ledger(self, trade_data: Dict[str, Any]):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO evidence_trade_ledger (
                    trade_id, symbol, t212_ticker, action, quantity,
                    entry_price, exit_price, position_cost, stop_loss_price,
                    take_profit_price, spread_cost, slippage_cost, fx_cost,
                    total_friction, gross_pnl, net_pnl, net_return_pct,
                    exit_reason, hold_duration_hours, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data.get("trade_id", f"TRD_{int(datetime.now().timestamp())}"),
                trade_data.get("symbol"),
                trade_data.get("t212_ticker"),
                trade_data.get("action"),
                trade_data.get("quantity"),
                trade_data.get("entry_price"),
                trade_data.get("exit_price", 0.0),
                trade_data.get("position_cost"),
                trade_data.get("stop_loss_price"),
                trade_data.get("take_profit_price"),
                trade_data.get("spread_cost", 0.0),
                trade_data.get("slippage_cost", 0.0),
                trade_data.get("fx_cost", 0.0),
                trade_data.get("total_friction", 0.0),
                trade_data.get("gross_pnl", 0.0),
                trade_data.get("net_pnl", 0.0),
                trade_data.get("net_return_pct", 0.0),
                trade_data.get("exit_reason", ""),
                trade_data.get("hold_duration_hours", 0.0),
                trade_data.get("mode", "LIVE")
            ))
            conn.commit()

    def record_kill_switch_event(self, trigger_type: str, severity: str, current_value: float, threshold: float, action_taken: str):
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO evidence_kill_switch_events (
                    trigger_type, severity, current_value, threshold, action_taken
                ) VALUES (?, ?, ?, ?, ?)
            """, (trigger_type, severity, current_value, threshold, action_taken))
            conn.commit()

    def record_broker_sync(self, broker_nav: float, internal_nav: float, broker_pos: int, internal_pos: int):
        discrepancy = abs(broker_nav - internal_nav) / max(1.0, internal_nav) * 100.0
        status = "SYNCED"
        if discrepancy > 1.50:
            status = "DESYNC_CRITICAL"
        elif discrepancy > 0.50:
            status = "DESYNC_WARNING"

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO evidence_broker_sync (
                    broker_nav, internal_nav, nav_discrepancy_pct,
                    open_positions_broker, open_positions_internal, status
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (broker_nav, internal_nav, discrepancy, broker_pos, internal_pos, status))
            conn.commit()

evidence_recorder = EvidenceRecorder()
