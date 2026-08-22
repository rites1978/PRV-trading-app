"""
MFE / MAE Excursion & Trajectory Analytics Service
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from src.database.db import db

class TrajectoryService:
    def record_trajectory(
        self,
        trade_id: int,
        symbol: str,
        entry_timestamp: str,
        exit_timestamp: str,
        entry_price: float,
        exit_price: float,
        entry_atr: float,
        duration_hours: float,
        in_trade_mfe_pct: float,
        in_trade_mae_pct: float,
        post_mfe_20d_pct: float = 0.0,
        post_mae_20d_pct: float = 0.0
    ):
        reached_target = 1 if (post_mfe_20d_pct >= 7.5 or in_trade_mfe_pct >= 7.5) else 0
        record = {
            "trade_id": trade_id,
            "symbol": symbol,
            "entry_timestamp": entry_timestamp,
            "exit_timestamp": exit_timestamp,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_atr14": entry_atr,
            "duration_hours": duration_hours,
            "max_favorable_excursion_pct": in_trade_mfe_pct,
            "max_adverse_excursion_pct": in_trade_mae_pct,
            "post_exit_mfe_5d_pct": post_mfe_20d_pct * 0.4,
            "post_exit_mfe_10d_pct": post_mfe_20d_pct * 0.7,
            "post_exit_mfe_20d_pct": post_mfe_20d_pct,
            "post_exit_mae_20d_pct": post_mae_20d_pct,
            "reached_target_post_exit": reached_target
        }

        with db.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trade_trajectories (
                    trade_id, symbol, entry_timestamp, exit_timestamp,
                    entry_price, exit_price, entry_atr14, duration_hours,
                    max_favorable_excursion_pct, max_adverse_excursion_pct,
                    post_exit_mfe_5d_pct, post_exit_mfe_10d_pct, post_exit_mfe_20d_pct,
                    post_exit_mae_20d_pct, reached_target_post_exit
                ) VALUES (
                    :trade_id, :symbol, :entry_timestamp, :exit_timestamp,
                    :entry_price, :exit_price, :entry_atr14, :duration_hours,
                    :max_favorable_excursion_pct, :max_adverse_excursion_pct,
                    :post_exit_mfe_5d_pct, :post_exit_mfe_10d_pct, :post_exit_mfe_20d_pct,
                    :post_exit_mae_20d_pct, :reached_target_post_exit
                )
            """, record)

    def get_trajectory_summary(self) -> Dict[str, Any]:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT AVG(max_favorable_excursion_pct) as avg_mfe,
                       AVG(max_adverse_excursion_pct) as avg_mae,
                       AVG(post_exit_mfe_20d_pct) as avg_post_mfe,
                       AVG(reached_target_post_exit) * 100.0 as pct_reached,
                       COUNT(*) as cnt
                FROM trade_trajectories
            """)
            row = cursor.fetchone()
            if not row or row["cnt"] == 0:
                return {
                    "trades_count": 0,
                    "avg_in_trade_mfe_pct": 0.0,
                    "avg_in_trade_mae_pct": 0.0,
                    "avg_post_exit_mfe_20d_pct": 0.0,
                    "pct_stopped_reaching_target": 0.0
                }
                
            return {
                "trades_count": row["cnt"],
                "avg_in_trade_mfe_pct": round(row["avg_mfe"] or 0.0, 2),
                "avg_in_trade_mae_pct": round(row["avg_mae"] or 0.0, 2),
                "avg_post_exit_mfe_20d_pct": round(row["avg_post_mfe"] or 0.0, 2),
                "pct_stopped_reaching_target": round(row["pct_reached"] or 0.0, 1)
            }

trajectory_service = TrajectoryService()
