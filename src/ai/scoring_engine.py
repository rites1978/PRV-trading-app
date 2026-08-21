from typing import Dict, Any, Tuple
from src.config.settings import settings
from src.database.db import db

class AIScoringEngine:
    """
    PRV Capital 8-Factor Quantitative Confidence Scoring Engine:
    Weights:
    1. Trend Strength: 20%
    2. Relative Strength (RSI): 15%
    3. Momentum (MACD): 15%
    4. Volume Confirmation: 15%
    5. Volatility Conditions: 10%
    6. Market Regime: 10%
    7. Portfolio Exposure: 10%
    8. Trading Cost Impact: 5%
    Total Weight = 100%
    """
    def __init__(self):
        pass

    def evaluate_factor_scores(
        self,
        snapshot: Dict[str, Any],
        market_regime: str,
        portfolio_exposure_pct: float,
        cost_friction_pct: float
    ) -> Dict[str, float]:
        indicators = snapshot["indicators"]
        current_price = snapshot["current_price"]
        
        # 1. Trend Strength (0 to 100)
        sma20 = indicators["sma_20"]
        sma50 = indicators["sma_50"]
        sma200 = indicators["sma_200"]
        trend_score = 50.0
        if current_price > sma20 > sma50 > sma200:
            trend_score = 95.0
        elif current_price > sma20 > sma50:
            trend_score = 80.0
        elif current_price > sma20:
            trend_score = 65.0
        elif current_price < sma20 < sma50 < sma200:
            trend_score = 10.0
        elif current_price < sma20 < sma50:
            trend_score = 25.0
        else:
            trend_score = 45.0

        # 2. Relative Strength / RSI (0 to 100)
        rsi = indicators["rsi"]
        if 40 <= rsi <= 55:
            # Bullish accumulation zone with upward room
            rsi_score = 90.0
        elif 30 <= rsi < 40:
            # Oversold rebound opportunity
            rsi_score = 85.0
        elif 55 < rsi <= 68:
            # Healthy bullish momentum
            rsi_score = 75.0
        elif rsi < 30:
            # Deep oversold
            rsi_score = 60.0
        else: # rsi > 70
            # Overbought risk
            rsi_score = 20.0

        # 3. Momentum / MACD (0 to 100)
        macd = indicators["macd"]
        macd_sig = indicators["macd_signal"]
        macd_hist = indicators["macd_hist"]
        if macd > macd_sig and macd_hist > 0:
            momentum_score = 90.0 if macd > 0 else 75.0
        elif macd < macd_sig and macd_hist < 0:
            momentum_score = 20.0 if macd < 0 else 35.0
        else:
            momentum_score = 50.0

        # 4. Volume Confirmation (0 to 100)
        vol_ratio = indicators["vol_ratio"]
        obv_up = indicators["obv_trending_up"]
        if vol_ratio > 1.2 and obv_up:
            volume_score = 95.0
        elif obv_up:
            volume_score = 75.0
        elif vol_ratio > 1.2:
            volume_score = 60.0
        else:
            volume_score = 35.0

        # 5. Volatility Conditions (0 to 100)
        bb_width = indicators["bb_width"]
        bb_lower = indicators["bb_lower"]
        bb_upper = indicators["bb_upper"]
        # Favorable: Price bouncing off lower band or expanding band breakout
        if current_price <= bb_lower * 1.01:
            volatility_score = 85.0
        elif bb_lower < current_price < bb_upper and bb_width < 0.10:
            # Volatility squeeze breakout ready
            volatility_score = 80.0
        elif current_price >= bb_upper * 0.99:
            volatility_score = 30.0
        else:
            volatility_score = 65.0

        # 6. Market Regime (0 to 100)
        if market_regime == "EXCEPTIONAL":
            regime_score = 95.0
        elif market_regime == "STRONG":
            regime_score = 75.0
        else:
            regime_score = 45.0

        # 7. Portfolio Exposure Score (0 to 100) - Higher score when under-allocated to deploy idle cash
        if portfolio_exposure_pct < 20.0:
            exposure_score = 95.0  # Strongly incentivise intelligent deployment
        elif portfolio_exposure_pct < 50.0:
            exposure_score = 80.0
        elif portfolio_exposure_pct < 75.0:
            exposure_score = 60.0
        else:
            exposure_score = 30.0

        # 8. Trading Cost Impact (0 to 100)
        if cost_friction_pct < 0.15:
            cost_score = 95.0
        elif cost_friction_pct < 0.30:
            cost_score = 80.0
        elif cost_friction_pct < 0.50:
            cost_score = 60.0
        else:
            cost_score = 25.0

        return {
            "trend_strength": round(trend_score, 1),
            "relative_strength": round(rsi_score, 1),
            "momentum": round(momentum_score, 1),
            "volume_confirmation": round(volume_score, 1),
            "volatility_condition": round(volatility_score, 1),
            "market_regime": round(regime_score, 1),
            "portfolio_exposure": round(exposure_score, 1),
            "trading_cost_impact": round(cost_score, 1)
        }

    def compute_composite_confidence(
        self,
        symbol: str,
        snapshot: Dict[str, Any],
        market_regime: str,
        portfolio_exposure_pct: float,
        cost_friction_pct: float
    ) -> Tuple[float, Dict[str, float]]:
        """
        Compute total weighted confidence score (0 to 100).
        """
        factors = self.evaluate_factor_scores(snapshot, market_regime, portfolio_exposure_pct, cost_friction_pct)
        
        composite = (
            factors["trend_strength"] * 0.20 +
            factors["relative_strength"] * 0.15 +
            factors["momentum"] * 0.15 +
            factors["volume_confirmation"] * 0.15 +
            factors["volatility_condition"] * 0.10 +
            factors["market_regime"] * 0.10 +
            factors["portfolio_exposure"] * 0.10 +
            factors["trading_cost_impact"] * 0.05
        )
        
        composite = round(max(0.0, min(100.0, composite)), 1)
        
        # Persist score breakdown to database
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO confidence_scores (
                        symbol, trend_strength, relative_strength, momentum,
                        volume_confirmation, volatility_condition, market_regime,
                        portfolio_exposure, trading_cost_impact, composite_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol, factors["trend_strength"], factors["relative_strength"],
                    factors["momentum"], factors["volume_confirmation"],
                    factors["volatility_condition"], factors["market_regime"],
                    factors["portfolio_exposure"], factors["trading_cost_impact"],
                    composite
                ))
                conn.commit()
        except Exception:
            pass

        return composite, factors

ai_scoring = AIScoringEngine()
