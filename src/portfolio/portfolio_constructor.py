import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple
from src.config.settings import settings

class PortfolioConstructor:
    """
    Phase 5 Multi-Factor Dynamic Position Sizing Architecture:
    1. Technical Engine generates pure Buy / No-Buy entry decision.
    2. Fundamentals, Sector Strength & News Sentiment scale position size between 3% and 8%:
       - Weak Multi-Factor Confluence (Score < 45) -> 3% Allocation (£1,500)
       - Average Multi-Factor Confluence (Score 45 - 65) -> 5% Allocation (£2,500)
       - Strong Multi-Factor Confluence (Score > 65) -> 8% Allocation (£4,000)
    3. ATR & Volatility Equalization Normalization.
    4. Pairwise Correlation & Sector Co-Movement Multiplier.
    """
    def __init__(
        self,
        min_position_pct: float = settings.MIN_POSITION_SIZE_PCT,
        base_position_pct: float = settings.BASE_POSITION_SIZE_PCT,
        max_position_pct: float = settings.MAX_POSITION_SIZE_PCT,
        target_annual_vol: float = 0.20
    ):
        self.min_position_pct = min_position_pct
        self.base_position_pct = base_position_pct
        self.max_position_pct = max_position_pct
        self.target_annual_vol = target_annual_vol

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
        """Calculate average pairwise return correlation between candidate and active holdings."""
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
        alpha_score: float = 50.0,
        current_holding_val: float = 0.0,
        active_positions_dfs: Dict[str, pd.DataFrame] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Calculates mathematically optimal share quantity using:
        Multi-Factor Dynamic Sizing (3% - 8%) + Volatility Scaling + Correlation Penalty
        """
        if price <= 0 or core_capital <= 0:
            return 0.0, 0.0, {}

        # 1. Multi-Factor Alpha Sizing Multiplier (3% to 8%)
        if alpha_score >= 65.0:
            target_pct = self.max_position_pct  # 8.0% (~£4,000) for strong confluence
            tier = "STRONG_CONFLUENCE_8_PCT"
        elif alpha_score <= 42.0:
            target_pct = self.min_position_pct  # 3.0% (~£1,500) for weak confluence
            tier = "WEAK_CONFLUENCE_3_PCT"
        else:
            # Interpolate smoothly between 3% and 8%
            interpolated = self.min_position_pct + ((alpha_score - 42.0) / 23.0) * (self.max_position_pct - self.min_position_pct)
            target_pct = max(self.min_position_pct, min(self.max_position_pct, interpolated))
            tier = "AVERAGE_CONFLUENCE_5_PCT"

        # Normalize target_pct to fraction
        target_fraction = target_pct / 100.0 if target_pct > 1.0 else target_pct
        max_fraction = self.max_position_pct / 100.0 if self.max_position_pct > 1.0 else self.max_position_pct

        raw_capital_allocation = core_capital * target_fraction

        # 2. Asset Volatility Scaling Multiplier
        annual_vol = self.compute_asset_volatility(df)
        vol_multiplier = self.target_annual_vol / max(0.08, annual_vol)
        vol_multiplier = max(0.70, min(1.30, vol_multiplier))

        # 3. Correlation-Aware Penalty Multiplier
        avg_correlation = self.compute_portfolio_correlation(df, active_positions_dfs or {})
        correlation_multiplier = max(0.50, 1.0 - (avg_correlation - 0.50)) if avg_correlation > 0.65 else 1.0

        # 4. Synthesize Target Capital
        target_position_value = raw_capital_allocation * vol_multiplier * correlation_multiplier
        target_position_value = min(target_position_value, core_capital * max_fraction)

        # 5. Scale-In Capital Delta
        needed_capital = max(0.0, target_position_value - current_holding_val)
        deployable_capital = min(needed_capital, available_cash * 0.90, remaining_capacity)

        if deployable_capital < (price * 0.5):
            return 0.0, 0.0, {
                "target_position_value": round(target_position_value, 2),
                "target_pct": round(target_pct * 100, 1),
                "sizing_tier": tier,
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
            "target_pct": round(target_pct * 100, 1),
            "sizing_tier": tier,
            "annual_vol": round(annual_vol * 100, 2),
            "vol_multiplier": round(vol_multiplier, 2),
            "avg_correlation": round(avg_correlation, 2),
            "correlation_multiplier": round(correlation_multiplier, 2)
        }

portfolio_constructor = PortfolioConstructor()
