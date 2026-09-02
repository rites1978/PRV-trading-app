"""
🏛️ PRV CAPITAL | NET EXPECTANCY, STATISTICAL CONFIDENCE & MFE/MAE ENGINE
Quantitative performance analytics engine with rigorous sample size confidence intervals.

Core Metrics:
1. Net Expectancy:
   NET_EXPECTANCY = (P_win * avg_net_win) - (P_loss * avg_net_loss)
2. Profit Factor = Gross/Net Wins / Gross/Net Losses
3. Net Capital-Time Efficiency:
   NET_CAPITAL_EFFICIENCY = expected_net_return / expected_holding_days
4. Sample Size Confidence Intervals (Milestones: 20, 50, 100, 200 trades):
   - Wilson Score Interval for Win Rate (95% CI)
   - Standard Error & t-distribution CI for Net Expectancy and Average Returns
5. Maximum Favourable Excursion (MFE) & Maximum Adverse Excursion (MAE)

CRITICAL GOVERNANCE RULE:
Modelled and shadow expectancy figures must be explicitly labelled:
"MODELLED/SHADOW EXPECTANCY — NOT YET LIVE VALIDATED"
Implementation Verification is NOT Strategy Profitability Validation.
"""
import math
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from src.database.db import db


class ExpectancyEngine:
    """
    Computes statistical edge, expectancy distributions, confidence intervals, and capital efficiency.
    """
    def compute_wilson_confidence_interval(self, successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Calculates Wilson score interval for binomial proportion (Win Rate).
        """
        if total <= 0:
            return 0.0, 0.0
        z = 1.96 if confidence == 0.95 else 2.576 # 95% or 99%
        p_hat = successes / total
        denominator = 1.0 + (z**2) / total
        centre = p_hat + (z**2) / (2 * total)
        spread = z * math.sqrt((p_hat * (1.0 - p_hat) / total) + (z**2) / (4 * total**2))
        lower = max(0.0, (centre - spread) / denominator)
        upper = min(1.0, (centre + spread) / denominator)
        return round(lower * 100.0, 2), round(upper * 100.0, 2)

    def compute_expectancy_metrics(self, closed_trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Calculates Net Expectancy, sample confidence intervals, and statistical trade distribution metrics.
        """
        if closed_trades is None:
            trades_raw = db.get_trades(limit=500)
            closed_trades = [t for t in trades_raw if t.get("action") in ["SELL", "CLOSE", "EXIT"] or t.get("realized_pnl") != 0]

        if not closed_trades:
            return {
                "validation_status": "INSUFFICIENT LIVE TRADES — SHADOW/MODELLED ONLY",
                "is_live_validated": False,
                "label": "MODELLED/SHADOW EXPECTANCY — NOT YET LIVE VALIDATED",
                "trade_count": 0,
                "completed_exits_count": 0,
                "next_milestone": 20,
                "progress_to_next_milestone_pct": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate_pct": 0.0,
                "win_rate_95_ci": [0.0, 0.0],
                "profit_factor": 0.0,
                "avg_net_win_gbp": 0.0,
                "avg_net_loss_gbp": 0.0,
                "payoff_ratio": 0.0,
                "net_expectancy_gbp": 0.0,
                "net_expectancy_std_err": 0.0,
                "net_expectancy_95_ci": [0.0, 0.0],
                "avg_holding_period_days": 14.0,
                "mfe_avg_pct": 0.0,
                "mae_avg_pct": 0.0,
                "sample_milestones": {
                    "20_trades": "PENDING (0/20)",
                    "50_trades": "PENDING (0/50)",
                    "100_trades": "PENDING (0/100)",
                    "200_trades": "PENDING (0/200)"
                }
            }

        net_pnls = [float(t.get("net_realized_pnl", t.get("realized_pnl", 0.0))) for t in closed_trades]
        wins = [p for p in net_pnls if p > 0]
        losses = [abs(p) for p in net_pnls if p <= 0]

        win_cnt = len(wins)
        loss_cnt = len(losses)
        total_cnt = len(net_pnls)

        win_rate = (win_cnt / total_cnt) if total_cnt > 0 else 0.0
        loss_rate = 1.0 - win_rate

        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0

        payoff_ratio = (avg_win / max(0.01, avg_loss)) if avg_loss > 0 else avg_win

        # Net Expectancy in GBP
        net_expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

        total_wins_sum = sum(wins)
        total_losses_sum = sum(losses)
        profit_factor = (total_wins_sum / max(0.01, total_losses_sum)) if total_losses_sum > 0 else (total_wins_sum if total_wins_sum > 0 else 0.0)

        # Standard Error and 95% Confidence Interval for Expectancy
        if total_cnt >= 2:
            pnl_std = float(np.std(net_pnls, ddof=1))
            std_err = pnl_std / math.sqrt(total_cnt)
            t_crit = 1.96 if total_cnt >= 30 else 2.10
            exp_ci_lower = round(net_expectancy - (t_crit * std_err), 2)
            exp_ci_upper = round(net_expectancy + (t_crit * std_err), 2)
        else:
            std_err = 0.0
            exp_ci_lower = round(net_expectancy, 2)
            exp_ci_upper = round(net_expectancy, 2)

        win_ci_lower, win_ci_upper = self.compute_wilson_confidence_interval(win_cnt, total_cnt)

        # Sample Size Classification
        if total_cnt < 20:
            val_status = "INSUFFICIENT LIVE TRADES (<20 exits) — SHADOW/MODELLED ONLY"
            is_live_val = False
            next_ms = 20
        elif total_cnt < 50:
            val_status = "PRELIMINARY CHECKPOINT 1 REACHED (20-49 exits) — LOW STATISTICAL POWER"
            is_live_val = False
            next_ms = 50
        elif total_cnt < 100:
            val_status = "CHECKPOINT 2 REACHED (50-99 exits) — MODERATE STATISTICAL POWER"
            is_live_val = True
            next_ms = 100
        else:
            val_status = "STATISTICALLY ROBUST DATASET (>=100 exits) — LIVE VALIDATED"
            is_live_val = True
            next_ms = 200

        # Holding days & MFE/MAE
        holding_days_list = [float(t.get("holding_period_days", 14.0)) for t in closed_trades]
        avg_holding_days = float(np.mean(holding_days_list)) if holding_days_list else 14.0

        mfe_list = [float(t.get("mfe", 0.0)) for t in closed_trades if t.get("mfe")]
        mae_list = [float(t.get("mae", 0.0)) for t in closed_trades if t.get("mae")]
        avg_mfe = float(np.mean(mfe_list)) if mfe_list else 0.0
        avg_mae = float(np.mean(mae_list)) if mae_list else 0.0

        return {
            "validation_status": val_status,
            "is_live_validated": is_live_val,
            "label": "LIVE EMPIRICAL DATASET" if is_live_val else "MODELLED/SHADOW EXPECTANCY — NOT YET LIVE VALIDATED",
            "trade_count": total_cnt,
            "completed_exits_count": total_cnt,
            "next_milestone": next_ms,
            "progress_to_next_milestone_pct": round((total_cnt / next_ms) * 100.0, 1),
            "win_count": win_cnt,
            "loss_count": loss_cnt,
            "win_rate_pct": round(win_rate * 100.0, 2),
            "win_rate_95_ci": [win_ci_lower, win_ci_upper],
            "profit_factor": round(profit_factor, 2),
            "avg_net_win_gbp": round(avg_win, 2),
            "avg_net_loss_gbp": round(avg_loss, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "net_expectancy_gbp": round(net_expectancy, 2),
            "net_expectancy_std_err": round(std_err, 2),
            "net_expectancy_95_ci": [exp_ci_lower, exp_ci_upper],
            "avg_holding_period_days": round(avg_holding_days, 1),
            "mfe_avg_pct": round(avg_mfe, 2),
            "mae_avg_pct": round(avg_mae, 2),
            "sample_milestones": {
                "20_trades": f"{'COMPLETED' if total_cnt>=20 else 'PENDING'} ({min(20, total_cnt)}/20)",
                "50_trades": f"{'COMPLETED' if total_cnt>=50 else 'PENDING'} ({min(50, total_cnt)}/50)",
                "100_trades": f"{'COMPLETED' if total_cnt>=100 else 'PENDING'} ({min(100, total_cnt)}/100)",
                "200_trades": f"{'COMPLETED' if total_cnt>=200 else 'PENDING'} ({min(200, total_cnt)}/200)"
            }
        }

    def calculate_capital_efficiency(
        self,
        predicted_net_return_pct: float,
        expected_holding_days: int
    ) -> Dict[str, float]:
        """
        Calculates Net Capital Efficiency (% net return per holding day).
        """
        days = max(1, expected_holding_days)
        eff_per_day = predicted_net_return_pct / days
        annualized_eff = eff_per_day * 252.0  # 252 trading days per year

        return {
            "predicted_net_return_pct": round(predicted_net_return_pct, 2),
            "expected_holding_days": days,
            "net_capital_efficiency_per_day": round(eff_per_day, 4),
            "annualized_capital_efficiency_pct": round(annualized_eff, 2)
        }


expectancy_engine = ExpectancyEngine()
