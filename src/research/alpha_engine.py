from typing import Dict, Any, Tuple
from src.research.fundamental_alpha import fundamental_alpha
from src.research.sector_rotation import sector_rotation
from src.research.news_sentiment import news_sentiment
from src.ai.scoring_engine import ai_scoring

class InstitutionalAlphaEngine:
    """
    Multi-Dimensional Alpha Synthesis Engine:
    Combines:
    1. Technical Price Action & Microstructure (40% Weight)
    2. Fundamental Quality & Earnings Momentum (25% Weight)
    3. Sector Relative Strength & Capital Flow (20% Weight)
    4. NLP News Sentiment Polarity (15% Weight)
    """
    def __init__(self):
        pass

    def compute_institutional_alpha(
        self,
        symbol: str,
        yf_ticker: str,
        sector: str,
        snapshot: Dict[str, Any],
        market_regime: str,
        portfolio_exposure_pct: float,
        cost_friction_pct: float
    ) -> Tuple[float, Dict[str, Any]]:
        # 1. Technical Alpha Score
        tech_score, tech_factors = ai_scoring.compute_composite_confidence(
            symbol=symbol,
            snapshot=snapshot,
            market_regime=market_regime,
            portfolio_exposure_pct=portfolio_exposure_pct,
            cost_friction_pct=cost_friction_pct
        )

        # 2. Fundamental Alpha Score
        fund_data = fundamental_alpha.fetch_fundamental_metrics(yf_ticker)
        fund_score = fund_data.get("fundamental_score", 50.0)

        # 3. Sector Relative Strength Score
        df_stock = snapshot.get("dataframe")
        sector_data = sector_rotation.evaluate_relative_strength(df_stock, sector)
        sector_score = (sector_data.get("sector_momentum_score", 50.0) * 0.5) + (sector_data.get("relative_strength_score", 50.0) * 0.5)

        # 4. News Sentiment Score
        sentiment_data = news_sentiment.fetch_stock_sentiment(symbol)
        sentiment_score = sentiment_data.get("sentiment_score", 50.0)

        # Multi-Pillar Alpha Synthesis (0 - 100)
        composite_alpha = (
            (tech_score * 0.40) +
            (fund_score * 0.25) +
            (sector_score * 0.20) +
            (sentiment_score * 0.15)
        )
        composite_alpha = round(max(0.0, min(100.0, composite_alpha)), 1)

        breakdown = {
            "symbol": symbol,
            "composite_alpha": composite_alpha,
            "technical_score": round(tech_score, 1),
            "fundamental_score": round(fund_score, 1),
            "sector_alpha_score": round(sector_score, 1),
            "sentiment_score": round(sentiment_score, 1),
            "technical_factors": tech_factors,
            "fundamental_metrics": fund_data,
            "sector_metrics": sector_data,
            "sentiment_metrics": sentiment_data
        }

        return composite_alpha, breakdown

alpha_engine = InstitutionalAlphaEngine()
