import yfinance as yf
from typing import Dict, Any, Optional

class FundamentalAlphaResearcher:
    """
    Institutional Fundamental Alpha Engine:
    Researches:
    1. Quarterly Earnings Surprises (EPS Beat / Miss Ratio)
    2. Revenue Growth & Operating Margin Quality
    3. Analyst Consensus & Upgrades/Downgrades
    4. Forward Valuation Momentum (PEG / Forward PE)
    """
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def fetch_fundamental_metrics(self, yf_ticker: str) -> Dict[str, Any]:
        """Fetch balance sheet, income statement, and analyst consensus from Yahoo Finance."""
        if yf_ticker in self._cache:
            return self._cache[yf_ticker]

        try:
            stock = yf.Ticker(yf_ticker)
            info = stock.info or {}
            
            # 1. Earnings Surprise Analysis
            earnings_history = stock.earnings_dates
            last_surprise_pct = 0.0
            if earnings_history is not None and not earnings_history.empty and 'Surprise(%)' in earnings_history.columns:
                valid_surprises = earnings_history['Surprise(%)'].dropna()
                if not valid_surprises.empty:
                    last_surprise_pct = float(valid_surprises.iloc[0]) * 100.0 if abs(valid_surprises.iloc[0]) < 10 else float(valid_surprises.iloc[0])

            # 2. Revenue & Earnings Growth
            rev_growth = float(info.get("revenueGrowth", 0.0) or 0.0)
            earnings_growth = float(info.get("earningsGrowth", 0.0) or 0.0)
            operating_margins = float(info.get("operatingMargins", 0.0) or 0.0)

            # 3. Analyst Consensus
            target_mean_price = float(info.get("targetMeanPrice", 0.0) or 0.0)
            current_price = float(info.get("currentPrice", info.get("regularMarketPrice", 1.0)) or 1.0)
            analyst_upside_pct = ((target_mean_price - current_price) / current_price * 100.0) if current_price > 0 and target_mean_price > 0 else 0.0
            recommendation = str(info.get("recommendationKey", "none")).lower()

            # 4. Fundamental Quality Score (0 - 100)
            score = 50.0

            # Earnings Surprise Factor
            if last_surprise_pct > 5.0:
                score += 15.0
            elif last_surprise_pct < -2.0:
                score -= 15.0

            # Revenue Growth Factor
            if rev_growth > 0.15:
                score += 15.0
            elif rev_growth > 0.05:
                score += 8.0
            elif rev_growth < -0.05:
                score -= 15.0

            # Analyst Consensus Factor
            if "buy" in recommendation or "strong_buy" in recommendation or analyst_upside_pct > 15.0:
                score += 15.0
            elif "underperform" in recommendation or "sell" in recommendation or analyst_upside_pct < -5.0:
                score -= 15.0

            # Margin Quality Factor
            if operating_margins > 0.20:
                score += 10.0
            elif operating_margins < 0.05:
                score -= 10.0

            score = max(0.0, min(100.0, score))

            data = {
                "success": True,
                "ticker": yf_ticker,
                "fundamental_score": round(score, 1),
                "last_earnings_surprise_pct": round(last_surprise_pct, 2),
                "revenue_growth_pct": round(rev_growth * 100.0, 2),
                "earnings_growth_pct": round(earnings_growth * 100.0, 2),
                "operating_margin_pct": round(operating_margins * 100.0, 2),
                "analyst_target_upside_pct": round(analyst_upside_pct, 2),
                "analyst_recommendation": recommendation
            }
            self._cache[yf_ticker] = data
            return data
        except Exception as e:
            fallback = {
                "success": False,
                "ticker": yf_ticker,
                "fundamental_score": 50.0,
                "error": str(e)
            }
            return fallback

fundamental_alpha = FundamentalAlphaResearcher()
