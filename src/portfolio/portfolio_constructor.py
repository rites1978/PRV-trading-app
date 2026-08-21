import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple
from src.config.settings import settings

class PortfolioConstructor:
    """
    Institutional Portfolio Construction & Dynamic Position Sizing:
    1. ATR-Adjusted Volatility Risk Sizing (Equal-Risk Contribution)
    2. Asset Volatility Scaling (Normalizes high vs low beta assets)
    3. Pairwise Correlation & Sector Co-Movement Penalty
    """
    def __init__(
        self,
        risk_per_trade_pct: float = 0.01,  # 1% risk per trade (£500 on £50k)
        atr_multiplier: float = 2.0,       # 2x ATR stop distance
        target_annual_vol: float = 0.20,    # 20% annual target volatility
        max_position_cap_pct: float = 0.08 # 8% max cap per position (£4,000)
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.atr_multiplier = atr_multiplier
        self.target_annual_vol = target_annual_vol
        self.max_position_cap_pct = max_position_cap_pct

    def compute_asset_volatility(self, df: pd.DataFrame) -> float:
        """Calculate annualized historical volatility from daily returns."""
        if df.empty or len(df) < 20:
            return self.target_annual_vol
        returns = df['Close'].pct_change().dropna()
        daily_std = returns.std()
        return float(daily_std * np.sqrt(252)) if not pd.isna(daily_std) else self.target_annual_vol

    def compute_portfolio_correlation(
        self,
        candidate_df: pd.DataFrame,
        active_positions_dfs: Dict[str, pd.DataFrame]
    ) -> float:
        """
        Calculate average pairwise return correlation between candidate and active holdings.
        Returns correlation in range [-1.0, 1.0].
        """
        if not active_positions_dfs or candidate_df.empty:
            return 0.0

        correlations = []
        cand_returns = candidate_df['Close'].pct_change().dropna()

        for ticker, pos_df in active_positions_dfs.items():
            if pos_df.empty:
                continue
            pos_returns = pos_df['Close'].pct_change().dropna()
            combined = pd.concat([cand_returns, pos_returns], axis=1).dropna()
            if len(combined) >= 15:
                corr = combined.iloc[:, 0].corr(combined.iloc[:, 1])
                if not pd.isna(corr):
                    correlations.append(corr)

        return float(np.mean(correlations)) if correlations else 0.0

    def calculate_optimal_position_size(
        self,
        symbol: str,
        price: float,
        atr: float,
        df: pd.DataFrame,
        core_capital: float,
        available_cash: float,
        remaining_capacity: float,
        current_holding_val: float = 0.0,
        active_positions_dfs: Dict[str, pd.DataFrame] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Calculates mathematically optimal share quantity using:
        ATR Risk Sizing + Volatility Scaling + Correlation Penalty
        """
        if price <= 0 or core_capital <= 0:
            return 0.0, 0.0, {}

        # 1. Base ATR Risk Sizing
        # Nominal risk dollar budget (e.g. 1% of Core Capital = £500)
        risk_dollar_budget = core_capital * self.risk_per_trade_pct
        effective_atr = max(atr, price * 0.015) # Floor ATR at 1.5% of price
        stop_distance = self.atr_multiplier * effective_atr
        
        # Raw shares by risk budget: Q = Risk$ / StopDistance
        raw_units_by_risk = risk_dollar_budget / stop_distance
        raw_capital_allocation = raw_units_by_risk * price

        # 2. Asset Volatility Scaling Multiplier
        annual_vol = self.compute_asset_volatility(df)
        vol_multiplier = self.target_annual_vol / max(0.08, annual_vol)
        vol_multiplier = max(0.60, min(1.40, vol_multiplier)) # Bound between 0.6x and 1.4x

        # 3. Correlation-Aware Penalty Multiplier
        avg_correlation = self.compute_portfolio_correlation(df, active_positions_dfs or {})
        if avg_correlation > 0.65:
            # Penalize highly correlated additions to prevent sector crowding
            correlation_multiplier = max(0.45, 1.0 - (avg_correlation - 0.50))
        else:
            correlation_multiplier = 1.0

        # 4. Synthesize Optimal Capital Allocation
        optimal_target_capital = raw_capital_allocation * vol_multiplier * correlation_multiplier
        
        # Upper Bound Cap: Max 8% of Core Capital (~£4,000)
        max_position_cap = core_capital * self.max_position_cap_pct
        target_position_value = min(optimal_target_capital, max_position_cap)
        
        # 5. Calculate Scale-In Delta
        needed_capital = max(0.0, target_position_value - current_holding_val)
        
        # Constrain by available cash buffer and dynamic regime deployment capacity
        deployable_capital = min(needed_capital, available_cash * 0.90, remaining_capacity)
        
        if deployable_capital < (price * 0.5):
            return 0.0, 0.0, {
                "target_position_value": round(target_position_value, 2),
                "annual_vol": round(annual_vol * 100, 2),
                "vol_multiplier": round(vol_multiplier, 2),
                "avg_correlation": round(avg_correlation, 2),
                "correlation_multiplier": round(correlation_multiplier, 2)
            }

        units = deployable_capital / price
        final_units = round(units, 2) if units >= 1.0 else round(units, 4)
        actual_cost = final_units * price

        return final_units, actual_cost, {
            "target_position_value": round(target_position_value, 2),
            "annual_vol": round(annual_vol * 100, 2),
            "vol_multiplier": round(vol_multiplier, 2),
            "avg_correlation": round(avg_correlation, 2),
            "correlation_multiplier": round(correlation_multiplier, 2),
            "stop_distance": round(stop_distance, 4)
        }

portfolio_constructor = PortfolioConstructor()
