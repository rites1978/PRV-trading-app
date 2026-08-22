"""
Trade Attribution & Root Cause Analytics Service
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from src.database.db import db

class TradeAttributionService:
    def classify_trade_outcome(self, trade_id: int, trade_data: Dict[str, Any], telemetry: Dict[str, Any]) -> Dict[str, Any]:
        pnl = float(trade_data.get("realized_pnl", 0.0))
        pnl_pct = float(trade_data.get("realized_pnl_pct", 0.0))
        exit_reason = trade_data.get("trade_reason", trade_data.get("exit_reason", ""))
        latency_days = float(telemetry.get("pre_entry_latency_days", 0.0))
        post_mfe = float(telemetry.get("post_exit_mfe_20d_pct", 0.0))
        days_since_stop = telemetry.get("days_since_prior_stop")
        regime = telemetry.get("macro_regime_at_entry", "MILD_BULL")
        earnings_prox = telemetry.get("earnings_proximity_days")
        slippage = float(telemetry.get("slippage_pct", 0.0))

        if pnl > 0:
            category = "CLEAN_WINNER"
            conf = 95.0
            notes = f"Trade reached target/trailing exit (+£{pnl:.2f}) cleanly."
        elif earnings_prox is not None and abs(earnings_prox) <= 2:
            category = "EARNINGS_EVENT"
            conf = 90.0
            notes = f"Stopped out during quarterly earnings window ({earnings_prox}d proximity)."
        elif days_since_stop is not None and days_since_stop < 10:
            category = "REPEAT_ENTRY"
            conf = 95.0
            notes = f"Re-entered symbol {days_since_stop} days after prior stop-loss without cooldown."
        elif post_mfe >= 7.5 and "STOP" in exit_reason.upper():
            category = "STOP_COLLISION"
            conf = 90.0
            notes = f"Stopped out at {pnl_pct:.2f}%, but asset subsequently rallied +{post_mfe:.2f}% to target."
        elif latency_days >= 3.0 and post_mfe >= 4.0:
            category = "AI_LATENCY"
            conf = 85.0
            notes = f"Entered {latency_days:.1f} days late after breakout; absorbed normal pullback."
        elif regime in ["STRONG_BEAR", "MILD_BEAR"]:
            category = "MARKET_REGIME"
            conf = 80.0
            notes = f"Entered during adverse macro regime ({regime})."
        elif slippage >= 0.35:
            category = "SLIPPAGE"
            conf = 85.0
            notes = f"Fill price suffered {slippage:.2f}% slippage beyond model trigger."
        else:
            category = "OTHER"
            conf = 70.0
            notes = "Loss caused by standard structural trend invalidation."

        record = {
            "trade_id": trade_id,
            "symbol": trade_data.get("symbol", "UNKNOWN"),
            "exit_timestamp": trade_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "realized_pnl": pnl,
            "realized_pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "pre_entry_latency_days": latency_days,
            "entry_atr14": float(telemetry.get("entry_atr14", 0.0)),
            "post_exit_mfe_20d_pct": post_mfe,
            "post_exit_mae_20d_pct": float(telemetry.get("post_exit_mae_20d_pct", 0.0)),
            "days_since_prior_stop": days_since_stop,
            "macro_regime_at_entry": regime,
            "earnings_proximity_days": earnings_prox,
            "slippage_pct": slippage,
            "root_cause_category": category,
            "attribution_confidence": conf,
            "forensic_notes": notes
        }

        with db.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trade_attributions (
                    trade_id, symbol, exit_timestamp, realized_pnl, realized_pnl_pct,
                    exit_reason, pre_entry_latency_days, entry_atr14, post_exit_mfe_20d_pct,
                    post_exit_mae_20d_pct, days_since_prior_stop, macro_regime_at_entry,
                    earnings_proximity_days, slippage_pct, root_cause_category,
                    attribution_confidence, forensic_notes
                ) VALUES (
                    :trade_id, :symbol, :exit_timestamp, :realized_pnl, :realized_pnl_pct,
                    :exit_reason, :pre_entry_latency_days, :entry_atr14, :post_exit_mfe_20d_pct,
                    :post_exit_mae_20d_pct, :days_since_prior_stop, :macro_regime_at_entry,
                    :earnings_proximity_days, :slippage_pct, :root_cause_category,
                    :attribution_confidence, :forensic_notes
                )
            """, record)

        return record

    def get_attribution_summary(self) -> Dict[str, Any]:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT root_cause_category, COUNT(*) as cnt, SUM(realized_pnl) as total_pnl
                FROM trade_attributions
                GROUP BY root_cause_category
            """)
            rows = cursor.fetchall()
            
            breakdown = {}
            total_losses = 0.0
            for r in rows:
                cat = r["root_cause_category"]
                cnt = r["cnt"]
                pnl_val = float(r["total_pnl"] or 0.0)
                breakdown[cat] = {"count": cnt, "total_pnl_gbp": round(pnl_val, 2)}
                if pnl_val < 0:
                    total_losses += abs(pnl_val)
                    
            for cat, data in breakdown.items():
                if data["total_pnl_gbp"] < 0:
                    data["pct_of_losses"] = round((abs(data["total_pnl_gbp"]) / max(1.0, total_losses)) * 100.0, 1)

            return {
                "total_classified_trades": sum(d["count"] for d in breakdown.values()),
                "total_loss_amount_gbp": round(total_losses, 2),
                "breakdown": breakdown
            }

attribution_service = TradeAttributionService()
