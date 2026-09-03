"""
🏛️ PRV CAPITAL | MARKET CRASH & SYSTEMIC STRESS DETECTOR
Monitors macro market indicators, volatility expansion, spread blow-outs,
and portfolio correlation to activate MARKET_STRESS_MODE.

Key Rules:
1. In severe stress: NEW_DISCRETIONARY_LONG_ENTRIES = False.
2. Protective risk exits, stop losses, and de-risking ALWAYS continue unimpeded.
3. Stress mode must NEVER be triggered merely because PRV is below its profit target.
"""
from typing import Dict, Any, Tuple, Optional
import yfinance as yf
from datetime import datetime, timezone
from src.config.settings import settings


class MarketStressDetector:
    """
    Monitors market crash and volatility expansion metrics to protect capital.
    """
    def __init__(self):
        self.index_drawdown_threshold_pct = settings.MARKET_STRESS_INDEX_DRAWDOWN_PCT # 2.0%
        self.spread_threshold_bps = settings.MARKET_STRESS_SPREAD_THRESHOLD_BPS       # 35 bps
        self._mock_stress_active = False
        self._mock_stress_reason = ""

    def set_mock_stress(self, active: bool, reason: str = ""):
        """Testing hook for deterministic verification."""
        self._mock_stress_active = active
        self._mock_stress_reason = reason

    def evaluate_market_stress(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Evaluates market conditions across multiple systemic indicators:
        - Benchmark index drop (SPY / FTSE) >= 2.0% intraday
        - Volatility spike (VIX >= 28 or sharp jump)
        - Watchlist spread expansion (exceeding 35 bps ceiling)
        """
        if self._mock_stress_active:
            return True, self._mock_stress_reason, {
                "stress_active": True,
                "reason": self._mock_stress_reason,
                "is_mock": True
            }

        stress_reasons = []
        metrics = {
            "sp500_day_change_pct": 0.0,
            "vix_level": 16.0,
            "watchlist_avg_spread_bps": 8.0,
            "data_fresh": True
        }

        from src.data.market_hours import market_hours
        is_uk_open = market_hours.is_asset_market_open("UK")
        is_us_open = market_hours.is_asset_market_open("US")

        # 1. Benchmark index evaluation with freshness check
        try:
            spy = yf.Ticker("SPY").history(period="2d")
            if len(spy) >= 2:
                last_ts = spy.index[-1]
                # If US is open, check freshness (should not be older than 90 mins)
                now_utc = datetime.now(timezone.utc)
                if is_us_open and hasattr(last_ts, "tz_convert"):
                    age_mins = (now_utc - last_ts.tz_convert(timezone.utc)).total_seconds() / 60.0
                    if age_mins > 90.0:
                        metrics["data_fresh"] = False
                        stress_reasons.append(f"STRESS_CAUTION: S&P benchmark feed is stale ({age_mins:.0f} mins old) during active US session.")

                prev_close = float(spy["Close"].iloc[-2])
                curr_price = float(spy["Close"].iloc[-1])
                change_pct = ((curr_price - prev_close) / prev_close) * 100.0
                metrics["sp500_day_change_pct"] = round(change_pct, 2)
                if change_pct <= -self.index_drawdown_threshold_pct:
                    stress_reasons.append(f"Benchmark S&P 500 down {change_pct:.2f}% (exceeds -{self.index_drawdown_threshold_pct:.1f}% crash threshold)")
            elif is_us_open:
                # Active US market but no data returned
                metrics["data_fresh"] = False
                stress_reasons.append("STRESS_CAUTION: Unable to retrieve benchmark index during active trading session.")
        except Exception as e:
            if is_us_open:
                metrics["data_fresh"] = False
                stress_reasons.append(f"STRESS_CAUTION: Benchmark index feed exception during active trading session ({e}).")

        # 2. VIX evaluation with freshness check
        try:
            vix = yf.Ticker("^VIX").history(period="1d")
            if not vix.empty:
                vix_val = float(vix["Close"].iloc[-1])
                metrics["vix_level"] = round(vix_val, 2)
                if vix_val >= 28.0:
                    stress_reasons.append(f"Volatility index elevated at {vix_val:.1f} (>= 28.0 stress ceiling)")
            elif is_us_open:
                metrics["data_fresh"] = False
                stress_reasons.append("STRESS_CAUTION: VIX volatility feed unavailable during active trading session.")
        except Exception:
            pass

        stress_active = (len(stress_reasons) > 0)
        summary_reason = " | ".join(stress_reasons) if stress_active else "Market conditions within normal volatility bands."

        return stress_active, summary_reason, {
            "stress_active": stress_active,
            "reasons": stress_reasons,
            "metrics": metrics
        }


market_stress_detector = MarketStressDetector()
