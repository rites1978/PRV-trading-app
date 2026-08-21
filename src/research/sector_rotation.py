import yfinance as yf
import pandas as pd
import numpy as np
from typing import Dict, Any

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Consumer Cyclical": "XLY",
    "Communication": "XLC",
    "Utilities": "XLU",
    "Basic Materials": "XLB"
}

class SectorRotationResearcher:
    """
    Sector Rotation & Relative Strength Alpha Engine:
    Tracks institutional capital flow across 10 global sector SPDR ETFs
    and measures individual equity relative strength (Alpha) vs Sector Benchmark.
    """
    def __init__(self):
        self._sector_cache: Dict[str, float] = {}

    def compute_sector_momentum(self) -> Dict[str, float]:
        """Compute 30-day relative strength of all major sectors vs S&P 500."""
        try:
            sp500 = yf.Ticker("^GSPC").history(period="3mo")
            if sp500.empty or len(sp500) < 20:
                return {s: 50.0 for s in SECTOR_ETF_MAP}

            sp_return_30d = (sp500['Close'].iloc[-1] - sp500['Close'].iloc[-20]) / sp500['Close'].iloc[-20]
            scores = {}

            for sector, etf_ticker in SECTOR_ETF_MAP.items():
                etf = yf.Ticker(etf_ticker).history(period="3mo")
                if etf.empty or len(etf) < 20:
                    scores[sector] = 50.0
                    continue

                etf_return_30d = (etf['Close'].iloc[-1] - etf['Close'].iloc[-20]) / etf['Close'].iloc[-20]
                excess_return = etf_return_30d - sp_return_30d

                # Sector Alpha Score (0 - 100)
                sector_score = 50.0 + (excess_return * 500.0) # 1% excess return = +5 score points
                scores[sector] = max(10.0, min(95.0, sector_score))

            self._sector_cache = scores
            return scores
        except Exception:
            return {s: 50.0 for s in SECTOR_ETF_MAP}

    def evaluate_relative_strength(
        self,
        stock_df: pd.DataFrame,
        sector: str
    ) -> Dict[str, Any]:
        """
        Evaluate stock relative strength against its specific sector ETF benchmark.
        """
        if not self._sector_cache:
            self.compute_sector_momentum()

        sector_momentum_score = self._sector_cache.get(sector, 50.0)
        etf_ticker = SECTOR_ETF_MAP.get(sector, "XLK")

        try:
            if stock_df.empty or len(stock_df) < 20:
                return {
                    "sector_momentum_score": sector_momentum_score,
                    "relative_strength_score": 50.0,
                    "is_sector_leader": False
                }

            stock_return_30d = (stock_df['Close'].iloc[-1] - stock_df['Close'].iloc[-20]) / stock_df['Close'].iloc[-20]
            
            etf = yf.Ticker(etf_ticker).history(period="3mo")
            etf_return = 0.0
            if not etf.empty and len(etf) >= 20:
                etf_return = (etf['Close'].iloc[-1] - etf['Close'].iloc[-20]) / etf['Close'].iloc[-20]

            stock_vs_sector_alpha = stock_return_30d - etf_return
            
            # Stock vs Sector Relative Strength Score (0 - 100)
            rs_score = 50.0 + (stock_vs_sector_alpha * 400.0)
            rs_score = max(10.0, min(95.0, rs_score))

            return {
                "sector_momentum_score": round(sector_momentum_score, 1),
                "relative_strength_score": round(rs_score, 1),
                "is_sector_leader": bool(rs_score >= 70.0),
                "stock_30d_return": round(stock_return_30d * 100, 2),
                "sector_30d_return": round(etf_return * 100, 2)
            }
        except Exception:
            return {
                "sector_momentum_score": sector_momentum_score,
                "relative_strength_score": 50.0,
                "is_sector_leader": False
            }

sector_rotation = SectorRotationResearcher()
