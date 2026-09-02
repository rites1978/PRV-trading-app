"""
🏛️ PRV CAPITAL | 10,000-ITERATION BOOTSTRAP MONTE CARLO RISK RESAMPLING ENGINE
Executes non-parametric bootstrap resampling on actual empirical trade returns.
Preserves heavy tails, skewness, and non-normal payoff characteristics.

Calculates:
- 95% Confidence Interval for Net Expectancy
- 95% Confidence Interval for Profit Factor
- Probability of Negative Expectancy P(Exp < 0)
- 95th Percentile Drawdown Ceiling
- Probability of 5 Consecutive Losses P(L >= 5)
- Probability of 10 Consecutive Losses P(L >= 10)
- Probability of Net Capital Loss over 50 trades P(Loss_50 > 0)
"""
import random
import numpy as np
from typing import Dict, Any, List, Optional
from src.analytics.shadow_dataset import shadow_dataset_service


class MonteCarloEngine:
    """
    Simulates forward portfolio distribution using 10,000 empirical bootstrap replications.
    """
    def __init__(self, iterations: int = 10000, seed: int = 42):
        self.iterations = iterations
        self.seed = seed

    def run_bootstrap_simulation(
        self,
        strategy_key: str = "strategy_D_decision",
        horizon_trades: int = 50
    ) -> Dict[str, Any]:
        """
        Executes 10,000-path bootstrap simulation on accepted trade returns.
        """
        random.seed(self.seed)
        np.random.seed(self.seed)

        ledger = shadow_dataset_service.generate_full_42_trade_ledger()
        accepted_trades = [t for t in ledger if t[strategy_key] == "EXECUTE"]

        if not accepted_trades:
            return {}

        empirical_net_pnls = [t["net_pnl"] for t in accepted_trades]
        n_empirical = len(empirical_net_pnls)

        bootstrapped_expectancies: List[float] = []
        bootstrapped_profit_factors: List[float] = []
        max_drawdowns_gbp: List[float] = []
        max_drawdowns_pct: List[float] = []
        consec_losses_5_count = 0
        consec_losses_10_count = 0
        capital_loss_50_trades_count = 0

        starting_capital = 50000.0

        for _ in range(self.iterations):
            # 1. Resample with replacement for point expectancy & profit factor estimation
            resample = [random.choice(empirical_net_pnls) for _ in range(n_empirical)]
            wins = [p for p in resample if p > 0]
            losses = [p for p in resample if p <= 0]
            
            exp = sum(resample) / n_empirical
            bootstrapped_expectancies.append(exp)

            pf = sum(wins) / max(0.01, sum(abs(p) for p in losses)) if losses else sum(wins)
            bootstrapped_profit_factors.append(pf)

            # 2. Simulate 50-Trade Path for Drawdown and Streak Analysis
            path = [random.choice(empirical_net_pnls) for _ in range(horizon_trades)]
            
            # Consecutive losses
            cur_consec_loss = 0
            max_consec_loss = 0
            for p in path:
                if p <= 0:
                    cur_consec_loss += 1
                    if cur_consec_loss > max_consec_loss:
                        max_consec_loss = cur_consec_loss
                else:
                    cur_consec_loss = 0

            if max_consec_loss >= 5:
                consec_losses_5_count += 1
            if max_consec_loss >= 10:
                consec_losses_10_count += 1

            # Cumulative equity curve & Max Drawdown
            equity = starting_capital
            peak = starting_capital
            max_dd = 0.0

            for p in path:
                equity += p
                if equity > peak:
                    peak = equity
                dd = peak - equity
                if dd > max_dd:
                    max_dd = dd

            max_drawdowns_gbp.append(max_dd)
            max_drawdowns_pct.append((max_dd / peak) * 100.0)

            # Net capital loss over 50 trades
            if (equity - starting_capital) < 0:
                capital_loss_50_trades_count += 1

        # Calculate Percentiles
        bootstrapped_expectancies.sort()
        bootstrapped_profit_factors.sort()
        max_drawdowns_pct.sort()
        max_drawdowns_gbp.sort()

        exp_p025 = np.percentile(bootstrapped_expectancies, 2.5)
        exp_median = np.percentile(bootstrapped_expectancies, 50.0)
        exp_p975 = np.percentile(bootstrapped_expectancies, 97.5)

        pf_p025 = np.percentile(bootstrapped_profit_factors, 2.5)
        pf_median = np.percentile(bootstrapped_profit_factors, 50.0)
        pf_p975 = np.percentile(bootstrapped_profit_factors, 97.5)

        dd_95th_pct = np.percentile(max_drawdowns_pct, 95.0)
        dd_95th_gbp = np.percentile(max_drawdowns_gbp, 95.0)

        prob_neg_expectancy = sum(1 for e in bootstrapped_expectancies if e <= 0) / float(self.iterations)
        prob_consec_5_losses = consec_losses_5_count / float(self.iterations)
        prob_consec_10_losses = consec_losses_10_count / float(self.iterations)
        prob_capital_loss_50 = capital_loss_50_trades_count / float(self.iterations)

        return {
            "simulation_type": "NON_PARAMETRIC_BOOTSTRAP_MONTE_CARLO",
            "iterations": self.iterations,
            "horizon_trades": horizon_trades,
            "strategy_analyzed": strategy_key,
            "net_expectancy_ci_95": {
                "p2_5_lower_bound_gbp": round(float(exp_p025), 2),
                "median_gbp": round(float(exp_median), 2),
                "p97_5_upper_bound_gbp": round(float(exp_p975), 2),
                "confidence_level_pct": 95.0
            },
            "profit_factor_ci_95": {
                "p2_5_lower_bound": round(float(pf_p025), 2),
                "median": round(float(pf_median), 2),
                "p97_5_upper_bound": round(float(pf_p975), 2)
            },
            "risk_tail_probabilities": {
                "prob_negative_expectancy_pct": round(prob_neg_expectancy * 100.0, 3),
                "prob_5_consecutive_losses_pct": round(prob_consec_5_losses * 100.0, 2),
                "prob_10_consecutive_losses_pct": round(prob_consec_10_losses * 100.0, 4),
                "prob_net_loss_over_50_trades_pct": round(prob_capital_loss_50 * 100.0, 3)
            },
            "drawdown_distribution": {
                "p95_maximum_drawdown_pct": round(float(dd_95th_pct), 2),
                "p95_maximum_drawdown_gbp": round(float(dd_95th_gbp), 2),
                "median_maximum_drawdown_pct": round(float(np.percentile(max_drawdowns_pct, 50.0)), 2),
                "median_maximum_drawdown_gbp": round(float(np.percentile(max_drawdowns_gbp, 50.0)), 2)
            },
            "governance_note": "MODELLED BOOTSTRAP DISTRIBUTION — PRESERVES NON-NORMAL EMPIRICAL RETURN TAILS. Live risk remains frozen until completed broker exits accumulate."
        }


monte_carlo_engine = MonteCarloEngine()
