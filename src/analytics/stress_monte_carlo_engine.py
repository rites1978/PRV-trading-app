"""
🏛️ PRV CAPITAL | ADVERSARIAL STRESS TESTING & BLOCK BOOTSTRAP RESAMPLING ENGINE
Replaces naive independent bootstrap with Chronological Block Resampling and Extreme Execution Stress Tests.

Methodological Improvements:
1. Block Bootstrap (Block Size = 5 trades): Preserves return autocorrelation, cluster risk, and streakiness.
2. Adversarial Stress Matrix:
   - Baseline Execution: 10 bps slippage, 1x spread, standard stop fills.
   - 2x Spread Stress: Double bid-ask friction across all trades.
   - 3x Slippage Stress: 30 bps execution slippage per leg.
   - Gap-Through-Stop Stress: 1.5x stop distance on adverse market openings.
   - Compound Quad-Stress: 2x Spread + 3x Slippage + Gap Losses combined.
3. Honest Empirical Reporting: Replaces '0.000% probability' claims with exact empirical counts:
   '0 occurrences observed in 10,000 block bootstrap replications'.
"""
import random
import numpy as np
from typing import Dict, Any, List, Optional
from src.analytics.oos_validation_engine import oos_validation_engine
from src.analytics.event_driven_portfolio_simulator import event_driven_portfolio_simulator


class StressMonteCarloEngine:
    """
    Simulates portfolio risk distributions under non-normal block bootstrap and adversarial execution stress.
    """
    def __init__(self, iterations: int = 10000, block_size: int = 5, seed: int = 42):
        self.iterations = iterations
        self.block_size = block_size
        self.seed = seed

    def run_block_bootstrap(
        self,
        strategy_key: str = "strategy_B_decision",
        horizon_trades: int = 50
    ) -> Dict[str, Any]:
        """
        Executes 10,000-iteration Block Bootstrap preserving serial correlation and clustering.
        """
        random.seed(self.seed)
        np.random.seed(self.seed)

        signals = oos_validation_engine.generate_oos_trade_ledger()
        accepted_trades = [s for s in signals if s.get(strategy_key) == "EXECUTE"]

        if len(accepted_trades) < self.block_size:
            return {}

        trade_pnls = [t["net_pnl"] for t in accepted_trades]
        n_trades = len(trade_pnls)

        # Generate overlapping blocks of length block_size
        blocks = [trade_pnls[i:i+self.block_size] for i in range(n_trades - self.block_size + 1)]

        bootstrapped_expectancies: List[float] = []
        bootstrapped_profit_factors: List[float] = []
        max_drawdowns_pct: List[float] = []
        max_drawdowns_gbp: List[float] = []

        consec_5_loss_events = 0
        consec_10_loss_events = 0
        capital_loss_50_trades_events = 0

        starting_nav = 50000.0

        for _ in range(self.iterations):
            # Sample blocks to build a 50-trade path
            simulated_path: List[float] = []
            while len(simulated_path) < horizon_trades:
                simulated_path.extend(random.choice(blocks))
            simulated_path = simulated_path[:horizon_trades]

            # Point Expectancy & Profit Factor for this path
            wins = [p for p in simulated_path if p > 0]
            losses = [p for p in simulated_path if p <= 0]
            
            exp = sum(simulated_path) / horizon_trades
            bootstrapped_expectancies.append(exp)

            pf = sum(wins) / max(0.01, sum(abs(p) for p in losses)) if losses else sum(wins)
            bootstrapped_profit_factors.append(pf)

            # Streak & Cluster Analysis
            cur_loss_streak = 0
            max_loss_streak = 0
            for p in simulated_path:
                if p <= 0:
                    cur_loss_streak += 1
                    if cur_loss_streak > max_loss_streak:
                        max_loss_streak = cur_loss_streak
                else:
                    cur_loss_streak = 0

            if max_loss_streak >= 5:
                consec_5_loss_events += 1
            if max_loss_streak >= 10:
                consec_10_loss_events += 1

            # Cumulative Equity Curve & Max Drawdown
            equity = starting_nav
            peak = starting_nav
            max_dd = 0.0

            for p in simulated_path:
                equity += (p * 2.5) # Scale to £2,500 base position size
                if equity > peak:
                    peak = equity
                dd = peak - equity
                if dd > max_dd:
                    max_dd = dd

            max_drawdowns_gbp.append(max_dd)
            max_drawdowns_pct.append((max_dd / peak) * 100.0)

            if (equity - starting_nav) < 0:
                capital_loss_50_trades_events += 1

        bootstrapped_expectancies.sort()
        bootstrapped_profit_factors.sort()
        max_drawdowns_pct.sort()
        max_drawdowns_gbp.sort()

        exp_p025 = float(np.percentile(bootstrapped_expectancies, 2.5))
        exp_median = float(np.percentile(bootstrapped_expectancies, 50.0))
        exp_p975 = float(np.percentile(bootstrapped_expectancies, 97.5))

        pf_p025 = float(np.percentile(bootstrapped_profit_factors, 2.5))
        pf_median = float(np.percentile(bootstrapped_profit_factors, 50.0))
        pf_p975 = float(np.percentile(bootstrapped_profit_factors, 97.5))

        dd_95th_pct = float(np.percentile(max_drawdowns_pct, 95.0))
        dd_95th_gbp = float(np.percentile(max_drawdowns_gbp, 95.0))

        return {
            "simulation_engine": "CHRONOLOGICAL_BLOCK_BOOTSTRAP",
            "iterations": self.iterations,
            "block_size_trades": self.block_size,
            "strategy_analyzed": strategy_key,
            "net_expectancy_ci_95": {
                "p2_5_lower_bound_gbp": round(exp_p025, 2),
                "median_gbp": round(exp_median, 2),
                "p97_5_upper_bound_gbp": round(exp_p975, 2),
                "confidence_level_pct": 95.0
            },
            "profit_factor_ci_95": {
                "p2_5_lower_bound": round(pf_p025, 2),
                "median": round(pf_median, 2),
                "p97_5_upper_bound": round(pf_p975, 2)
            },
            "empirical_sample_frequency": {
                "negative_expectancy_occurrences": f"{sum(1 for e in bootstrapped_expectancies if e <= 0)} of {self.iterations} bootstrap replications",
                "loss_over_50_trades_occurrences": f"{capital_loss_50_trades_events} of {self.iterations} bootstrap replications",
                "consecutive_5_losses_frequency_pct": round((consec_5_loss_events / float(self.iterations)) * 100.0, 2),
                "consecutive_10_losses_frequency_pct": round((consec_10_loss_events / float(self.iterations)) * 100.0, 4)
            },
            "drawdown_distribution": {
                "p95_maximum_drawdown_pct": round(dd_95th_pct, 2),
                "p95_maximum_drawdown_gbp": round(dd_95th_gbp, 2),
                "median_maximum_drawdown_pct": round(float(np.percentile(max_drawdowns_pct, 50.0)), 2),
                "median_maximum_drawdown_gbp": round(float(np.percentile(max_drawdowns_gbp, 50.0)), 2)
            }
        }

    def evaluate_adversarial_stress_matrix(self) -> Dict[str, Any]:
        """
        Runs complete adversarial execution stress matrix across Strategies A, B, and D.
        """
        stress_matrix = {}

        for s_key in ["strategy_A_decision", "strategy_B_decision", "strategy_D_decision"]:
            # 1. Normal Baseline Execution
            base = event_driven_portfolio_simulator.run_portfolio_replay(s_key, cost_multiplier=1.0, slippage_multiplier=1.0, gap_loss_multiplier=1.0)
            
            # 2. 2x Spread Stress
            stress_spread = event_driven_portfolio_simulator.run_portfolio_replay(s_key, cost_multiplier=2.0, slippage_multiplier=1.0, gap_loss_multiplier=1.0)

            # 3. 3x Slippage Stress (30 bps)
            stress_slip = event_driven_portfolio_simulator.run_portfolio_replay(s_key, cost_multiplier=1.0, slippage_multiplier=3.0, gap_loss_multiplier=1.0)

            # 4. Gap-Through-Stop Loss Stress (-1.5x stop distance)
            stress_gap = event_driven_portfolio_simulator.run_portfolio_replay(s_key, cost_multiplier=1.0, slippage_multiplier=1.0, gap_loss_multiplier=1.5)

            # 5. Compound Quad Stress (2x Spread + 3x Slippage + Gap Losses)
            stress_compound = event_driven_portfolio_simulator.run_portfolio_replay(s_key, cost_multiplier=2.0, slippage_multiplier=3.0, gap_loss_multiplier=1.5)

            stress_matrix[s_key] = {
                "baseline_execution": {
                    "net_profit_gbp": base["net_portfolio_profit_gbp"],
                    "net_return_pct": base["net_portfolio_return_pct"],
                    "expectancy_gbp": base["net_expectancy_per_trade_gbp"],
                    "profit_factor": base["profit_factor"],
                    "max_drawdown_pct": base["max_portfolio_drawdown_pct"]
                },
                "spread_stress_2x": {
                    "net_profit_gbp": stress_spread["net_portfolio_profit_gbp"],
                    "net_return_pct": stress_spread["net_portfolio_return_pct"],
                    "expectancy_gbp": stress_spread["net_expectancy_per_trade_gbp"],
                    "profit_factor": stress_spread["profit_factor"],
                    "max_drawdown_pct": stress_spread["max_portfolio_drawdown_pct"]
                },
                "slippage_stress_3x": {
                    "net_profit_gbp": stress_slip["net_portfolio_profit_gbp"],
                    "net_return_pct": stress_slip["net_portfolio_return_pct"],
                    "expectancy_gbp": stress_slip["net_expectancy_per_trade_gbp"],
                    "profit_factor": stress_slip["profit_factor"],
                    "max_drawdown_pct": stress_slip["max_portfolio_drawdown_pct"]
                },
                "gap_loss_stress_1_5x": {
                    "net_profit_gbp": stress_gap["net_portfolio_profit_gbp"],
                    "net_return_pct": stress_gap["net_portfolio_return_pct"],
                    "expectancy_gbp": stress_gap["net_expectancy_per_trade_gbp"],
                    "profit_factor": stress_gap["profit_factor"],
                    "max_drawdown_pct": stress_gap["max_portfolio_drawdown_pct"]
                },
                "compound_quad_stress": {
                    "net_profit_gbp": stress_compound["net_portfolio_profit_gbp"],
                    "net_return_pct": stress_compound["net_portfolio_return_pct"],
                    "expectancy_gbp": stress_compound["net_expectancy_per_trade_gbp"],
                    "profit_factor": stress_compound["profit_factor"],
                    "max_drawdown_pct": stress_compound["max_portfolio_drawdown_pct"]
                }
            }

        return stress_matrix


stress_monte_carlo_engine = StressMonteCarloEngine()
