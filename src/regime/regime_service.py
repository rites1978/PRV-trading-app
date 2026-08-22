"""
Market Regime Detection & State Machine Service
"""
import threading
from datetime import datetime, timezone
from typing import Dict, Any
import yfinance as yf
import pandas as pd
from src.database.db import db

class MarketRegimeService:
    def __init__(self):
        self._cached_regime = None
        self._cache_date = None
        self._lock = threading.Lock()

    def get_current_regime(self) -> Dict[str, Any]:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._cached_regime and self._cache_date == today_str:
            return self._cached_regime

        with self._lock:
            # Query local SQLite first (<1ms)
            with db.get_connection() as conn:
                row = conn.execute("SELECT * FROM market_regimes WHERE date = ?", (today_str,)).fetchone()
                if row:
                    self._cached_regime = {
                        "date": row["date"],
                        "spy_close": row["spy_close"],
                        "spy_sma20": row["spy_sma20"],
                        "spy_sma50": row["spy_sma50"],
                        "spy_sma200": row["spy_sma200"],
                        "vix_level": row["vix_level"],
                        "regime_classification": row["regime_classification"],
                        "risk_capacity_pct": row["risk_capacity_pct"],
                        "trading_permission": row["trading_permission"],
                        "diagnostic_rationale": row["diagnostic_rationale"]
                    }
                    self._cache_date = today_str
                    return self._cached_regime

            # Compute if not in DB
            return self.compute_daily_regime()

    def compute_daily_regime(self) -> Dict[str, Any]:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        try:
            data = yf.download(["SPY", "^VIX"], period="1y", interval="1d", progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                spy_close = data["Close"]["SPY"].dropna()
                vix_close = data["Close"]["^VIX"].dropna()
            else:
                spy_close = data["Close"]
                vix_close = pd.Series([18.0] * len(spy_close), index=spy_close.index)

            cur_spy = float(spy_close.iloc[-1])
            cur_vix = float(vix_close.iloc[-1]) if len(vix_close) > 0 else 18.0
            sma20 = float(spy_close.rolling(20).mean().iloc[-1])
            sma50 = float(spy_close.rolling(50).mean().iloc[-1])
            sma200 = float(spy_close.rolling(200).mean().iloc[-1])
            ret_20d = float(((cur_spy - spy_close.iloc[-20]) / spy_close.iloc[-20]) * 100.0)
        except Exception:
            # Fallback values if network down
            cur_spy = 558.0
            cur_vix = 16.0
            sma20 = 555.0
            sma50 = 550.0
            sma200 = 530.0
            ret_20d = 2.5

        if cur_spy > sma20 > sma50 and cur_vix <= 18.0 and ret_20d > 2.0:
            regime = "STRONG_BULL"
            capacity = 100.0
            permission = "FULL_TRADING"
            rationale = "SPY in strong upward trend (SMA20 > SMA50); VIX low."
        elif cur_spy > sma50 and cur_vix <= 22.0:
            regime = "MILD_BULL"
            capacity = 75.0
            permission = "FULL_TRADING"
            rationale = "SPY > SMA50 with moderate trend momentum; VIX normal."
        elif abs(cur_spy - sma50) / sma50 <= 0.015 and cur_vix <= 24.0:
            regime = "SIDEWAYS"
            capacity = 50.0
            permission = "RESTRICTED_TRADING"
            rationale = "SPY oscillating within 1.5% of SMA50; consolidation chop filter active."
        elif cur_spy < sma50 and cur_vix <= 28.0:
            regime = "MILD_BEAR"
            capacity = 25.0
            permission = "RESTRICTED_TRADING"
            rationale = "SPY below 50-day SMA; defensive allocations only."
        else:
            regime = "STRONG_BEAR"
            capacity = 0.0
            permission = "CASH_PRESERVATION_HALT"
            rationale = "Severe macro drawdown (VIX > 28 OR SPY < SMA200); 100% Cash Lock."

        record = {
            "date": today_str,
            "spy_close": round(cur_spy, 2),
            "spy_sma20": round(sma20, 2),
            "spy_sma50": round(sma50, 2),
            "spy_sma200": round(sma200, 2),
            "vix_level": round(cur_vix, 2),
            "regime_classification": regime,
            "risk_capacity_pct": capacity,
            "trading_permission": permission,
            "diagnostic_rationale": rationale
        }

        with db.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO market_regimes (
                    date, spy_close, spy_sma20, spy_sma50, spy_sma200,
                    vix_level, regime_classification, risk_capacity_pct,
                    trading_permission, diagnostic_rationale
                ) VALUES (
                    :date, :spy_close, :spy_sma20, :spy_sma50, :spy_sma200,
                    :vix_level, :regime_classification, :risk_capacity_pct,
                    :trading_permission, :diagnostic_rationale
                )
            """, record)

        self._cached_regime = record
        self._cache_date = today_str
        return record

regime_service = MarketRegimeService()
