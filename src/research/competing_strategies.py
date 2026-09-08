"""
🏛️ PRV CAPITAL | THREE COMPETING ALPHA STRATEGIES
Implements the exact logic for the alpha tournament:
1. Strategy A: Frozen V2 Baseline (Control Group — 75% quorum technical rotation, tight ratchet +0.50% / -1.00%)
2. Strategy B: Quality + Value (Institutional Greenblatt-inspired, non-financial/non-utility, low turnover)
3. Strategy C: Quality + Value + Momentum (Strategy B fundamental ranking + medium-term trend/momentum entry timing)
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple, Set
from src.research.backtest_harness import SimulatedTrade


def precompute_indicators(bars_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Pre-computes SMA20, SMA50, SMA200, RSI14, ret20d, and mom6m across all universe series for O(1) lookup."""
    enriched = {}
    for tick, df in bars_data.items():
        if df.empty or len(df) < 5:
            enriched[tick] = df
            continue
        d = df.copy()
        c = d["Close"]
        d["sma20"] = c.rolling(20, min_periods=5).mean()
        d["sma50"] = c.rolling(50, min_periods=10).mean()
        d["sma200"] = c.rolling(200, min_periods=20).mean()
        d["ret_20d"] = c.pct_change(20).fillna(0.0)
        d["mom_6m"] = c.pct_change(126).fillna(0.0)

        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=5).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=5).mean()
        rs = gain / loss.replace(0, np.nan)
        d["rsi14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)
        enriched[tick] = d
    return enriched


class StrategyAFrozenV2:
    """
    STRATEGY A — FROZEN V2 BASELINE (CONTROL GROUP)
    Runs the existing ratified V2 strategy logic:
    - Technical scoring quorum >= 75%
    - Sizing: £2,500 - £4,000 (~5-8% NAV)
    - Profit ratchet: Target reached at +0.50% net -> trailing floor locked
    - Stop loss: -1.00% gross max intended loss
    - High turnover UK stock rotation
    """
    def __init__(
        self,
        threshold: float = 75.0,
        profit_target_pct: float = 0.50,
        stop_loss_pct: float = 1.00,
        max_holding_days: int = 14,
        universe_region: str = "ALL"
    ):
        self.threshold = threshold
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_holding_days = max_holding_days
        self.universe_region = universe_region

    def __call__(self, mode: str, **kwargs) -> Any:
        if mode == "EVAL_EXIT":
            trade: SimulatedTrade = kwargs["trade"]
            bar = kwargs["current_bar"]
            current_dt: pd.Timestamp = kwargs["current_dt"]
            
            close_p = float(bar.get("Close"))
            pnl_pct = ((close_p - trade.entry_price) / trade.entry_price) * 100.0
            peak_pnl_pct = ((trade.peak_price - trade.entry_price) / trade.entry_price) * 100.0
            days_held = (current_dt - trade.entry_date).days

            # 1. Hard Stop: -1.00% gross loss limit
            if pnl_pct <= -self.stop_loss_pct:
                return True, close_p, f"V2 EXIT_HARD_STOP: Loss {pnl_pct:.2f}% breached -{self.stop_loss_pct:.2f}%"

            # 2. Ratchet Profit Protection: Once +0.50% net target reached, lock profit floor
            if peak_pnl_pct >= self.profit_target_pct:
                if pnl_pct <= 0.20:
                    return True, close_p, f"V2 EXIT_PROFIT_PROTECTION: Locked profit floor at {pnl_pct:.2f}%"

            # 3. Time-based rotation if stale
            if days_held >= self.max_holding_days:
                return True, close_p, f"V2 ROTATION_STALE: Max holding period {self.max_holding_days}d reached"

            return False, 0.0, ""

        elif mode == "GENERATE_SIGNALS":
            current_dt: pd.Timestamp = kwargs["current_dt"]
            current_idx: int = kwargs["current_idx"]
            available_slots: int = kwargs["available_slots"]
            existing_symbols: Set[str] = kwargs["existing_symbols"]
            bars_data: Dict[str, pd.DataFrame] = kwargs["bars_data"]

            signals = []
            from src.data.universe import INSTITUTIONAL_UNIVERSE
            
            for item in INSTITUTIONAL_UNIVERSE:
                sym = item["symbol"]
                if sym in existing_symbols:
                    continue
                
                country = str(item.get("country", "")).upper()
                if self.universe_region == "UK" and country != "UK":
                    continue
                if self.universe_region == "US" and country != "US":
                    continue
                
                yf_tick = item.get("yf_ticker")
                df = bars_data.get(yf_tick)
                if df is None or df.empty or current_dt not in df.index:
                    continue

                bar = df.loc[current_dt]
                last_p = float(bar.get("Close", 0.0))
                sma20 = float(bar.get("sma20", last_p))
                sma50 = float(bar.get("sma50", last_p))
                rsi = float(bar.get("rsi14", 50.0))
                ret_20d = float(bar.get("ret_20d", 0.0))

                if np.isnan(sma20) or np.isnan(sma50) or np.isnan(rsi) or last_p <= 0:
                    continue

                # V2 Technical Quorum Scoring
                score = 50.0
                if last_p > sma20:
                    score += 10.0
                if sma20 > sma50:
                    score += 10.0
                if 45.0 <= rsi <= 65.0:
                    score += 10.0
                elif rsi > 70.0:
                    score -= 5.0
                elif rsi < 30.0:
                    score -= 10.0

                if ret_20d > 0.02:
                    score += 8.0

                if score >= self.threshold:
                    signals.append({
                        "symbol": sym,
                        "yf_ticker": yf_tick,
                        "country": item.get("country", "UK"),
                        "score": score,
                        "target_capital": 3500.0,
                        "stop_price": round(last_p * (1.0 - self.stop_loss_pct / 100.0), 2),
                        "target_price": round(last_p * (1.0 + self.profit_target_pct / 100.0), 2)
                    })

            # Sort by highest technical score
            signals.sort(key=lambda x: x["score"], reverse=True)
            return signals[:available_slots]


class StrategyBQualityValue:
    """
    STRATEGY B — QUALITY + VALUE
    Greenblatt-inspired but independently implemented:
    - Filters out Financials and Utilities (non-financial, non-utility universe)
    - Quality Ranking: Return on Capital (ROC), Operating Margin, FCF Quality, Balance Sheet Strength
    - Value Ranking: Earnings Yield (EBIT/EV), Free Cash Flow Yield (FCF/MktCap), EV/EBITDA
    - Combined Rank = Rank(Quality) + Rank(Value)
    - Low turnover: Quarterly rebalancing (holding horizon ~90 days)
    - Wide stop protection: -8.0% gross stop to absorb short-term noise
    """
    def __init__(
        self,
        rebalance_days: int = 90,
        stop_loss_pct: float = 8.0,
        target_positions: int = 12,
        universe_region: str = "ALL"  # "ALL", "UK", or "US"
    ):
        self.rebalance_days = rebalance_days
        self.stop_loss_pct = stop_loss_pct
        self.target_positions = target_positions
        self.universe_region = universe_region
        self.fundamentals_cache: Dict[str, Any] = {}

    def set_fundamentals(self, data: Dict[str, Any]):
        self.fundamentals_cache = data

    def compute_ranks(self) -> Dict[str, float]:
        """Computes combined Quality + Value rankings for non-financial, non-utility universe."""
        if not self.fundamentals_cache:
            return {}

        candidates = []
        for tick, f in self.fundamentals_cache.items():
            sector = str(f.get("sector", "")).upper()
            country = str(f.get("country", "")).upper()
            
            # Exclude Financials and Utilities
            if sector in ("FINANCIALS", "FINANCIAL SERVICES", "UTILITIES"):
                continue

            if self.universe_region == "UK" and country != "UK":
                continue
            if self.universe_region == "US" and country != "US":
                continue

            roc = float(f.get("roc", 0.0) or 0.0)
            op_margin = float(f.get("operating_margin", 0.0) or 0.0)
            fcf_qual = float(f.get("fcf_quality", 0.0) or 0.0)
            debt_eq = float(f.get("debt_to_equity", 0.0) or 0.0)
            
            ey = float(f.get("earnings_yield", 0.0) or 0.0)
            fcf_y = float(f.get("fcf_yield", 0.0) or 0.0)
            ev_eb = float(f.get("ev_ebitda", 0.0) or 0.0)

            # Quality composite score
            quality_score = (roc * 0.4) + (op_margin * 0.3) + (fcf_qual * 0.2) - (min(200.0, debt_eq) * 0.001)
            # Value composite score
            value_score = (ey * 0.5) + (fcf_y * 0.5)

            candidates.append({
                "yf_ticker": tick,
                "symbol": f.get("symbol"),
                "country": country,
                "quality_score": quality_score,
                "value_score": value_score
            })

        if not candidates:
            return {}

        # Rank ascending on quality and value (highest score gets best rank)
        candidates.sort(key=lambda x: x["quality_score"], reverse=True)
        for r, c in enumerate(candidates):
            c["quality_rank"] = r + 1

        candidates.sort(key=lambda x: x["value_score"], reverse=True)
        for r, c in enumerate(candidates):
            c["value_rank"] = r + 1

        for c in candidates:
            c["combined_rank"] = c["quality_rank"] + c["value_rank"]

        # Sort by combined rank (lowest rank is best)
        candidates.sort(key=lambda x: x["combined_rank"])
        return {c["yf_ticker"]: c for c in candidates}

    def __call__(self, mode: str, **kwargs) -> Any:
        if mode == "EVAL_EXIT":
            trade: SimulatedTrade = kwargs["trade"]
            bar = kwargs["current_bar"]
            current_dt: pd.Timestamp = kwargs["current_dt"]
            
            close_p = float(bar.get("Close"))
            pnl_pct = ((close_p - trade.entry_price) / trade.entry_price) * 100.0
            days_held = (current_dt - trade.entry_date).days

            # 1. Catastrophic Downside Stop Loss
            if pnl_pct <= -self.stop_loss_pct:
                return True, close_p, f"STRAT_B STOP_LOSS: Breach -{self.stop_loss_pct:.1f}% ({pnl_pct:.2f}%)"

            # 2. Quarterly Rebalance Exit: Hold for holding horizon
            if days_held >= self.rebalance_days:
                return True, close_p, f"STRAT_B REBALANCE: Quarterly holding period {self.rebalance_days}d completed"

            return False, 0.0, ""

        elif mode == "GENERATE_SIGNALS":
            available_slots: int = kwargs["available_slots"]
            existing_symbols: Set[str] = kwargs["existing_symbols"]
            bars_data: Dict[str, pd.DataFrame] = kwargs["bars_data"]
            current_dt: pd.Timestamp = kwargs["current_dt"]

            ranked = self.compute_ranks()
            signals = []
            
            for yf_tick, item in ranked.items():
                sym = item["symbol"]
                if sym in existing_symbols:
                    continue
                
                df = bars_data.get(yf_tick)
                if df is None or df.empty or current_dt not in df.index:
                    continue

                last_p = float(df.loc[current_dt].get("Close"))
                signals.append({
                    "symbol": sym,
                    "yf_ticker": yf_tick,
                    "country": item["country"],
                    "combined_rank": item["combined_rank"],
                    "target_capital": 4000.0,
                    "stop_price": round(last_p * (1.0 - self.stop_loss_pct / 100.0), 2),
                    "target_price": 0.0
                })

                if len(signals) >= available_slots:
                    break

            return signals


class StrategyCQualityValueMomentum:
    """
    STRATEGY C — QUALITY + VALUE + MOMENTUM
    Starts with Strategy B fundamental ranking.
    Adds medium-term price/trend confirmation for entry timing:
    - 50-day SMA > 200-day SMA (trend regime filter) OR 12-1 month price momentum > 0
    - Price > 50-day SMA (timing filter)
    - Momentum improves entry timing without replacing fundamental selection.
    - Holding period: Quarterly rebalance or trend violation.
    """
    def __init__(
        self,
        rebalance_days: int = 90,
        stop_loss_pct: float = 7.0,
        target_positions: int = 12,
        universe_region: str = "ALL"
    ):
        self.strat_b = StrategyBQualityValue(
            rebalance_days=rebalance_days,
            stop_loss_pct=stop_loss_pct,
            target_positions=target_positions,
            universe_region=universe_region
        )
        self.rebalance_days = rebalance_days
        self.stop_loss_pct = stop_loss_pct

    def set_fundamentals(self, data: Dict[str, Any]):
        self.strat_b.set_fundamentals(data)

    def __call__(self, mode: str, **kwargs) -> Any:
        if mode == "EVAL_EXIT":
            trade: SimulatedTrade = kwargs["trade"]
            bar = kwargs["current_bar"]
            current_dt: pd.Timestamp = kwargs["current_dt"]
            
            close_p = float(bar.get("Close"))
            pnl_pct = ((close_p - trade.entry_price) / trade.entry_price) * 100.0
            days_held = (current_dt - trade.entry_date).days

            # 1. Stop Loss Protection
            if pnl_pct <= -self.stop_loss_pct:
                return True, close_p, f"STRAT_C STOP_LOSS: Breach -{self.stop_loss_pct:.1f}% ({pnl_pct:.2f}%)"

            # 2. Quarterly Rebalance Exit
            if days_held >= self.rebalance_days:
                return True, close_p, f"STRAT_C REBALANCE: Holding period {self.rebalance_days}d completed"

            return False, 0.0, ""

        elif mode == "GENERATE_SIGNALS":
            available_slots: int = kwargs["available_slots"]
            existing_symbols: Set[str] = kwargs["existing_symbols"]
            bars_data: Dict[str, pd.DataFrame] = kwargs["bars_data"]
            current_dt: pd.Timestamp = kwargs["current_dt"]

            # 1. Get fundamental ranks from Strategy B
            ranked = self.strat_b.compute_ranks()
            signals = []

            for yf_tick, item in ranked.items():
                sym = item["symbol"]
                if sym in existing_symbols:
                    continue

                df = bars_data.get(yf_tick)
                if df is None or df.empty or current_dt not in df.index:
                    continue

                bar = df.loc[current_dt]
                last_p = float(bar.get("Close", 0.0))
                sma50 = float(bar.get("sma50", 0.0))
                sma200 = float(bar.get("sma200", 0.0))
                mom_6m = float(bar.get("mom_6m", 0.0))

                if np.isnan(sma200) or sma200 <= 0 or last_p <= 0:
                    continue

                # Momentum & Trend Timing Filter:
                # 1. Price above 50-day SMA (medium-term uptrend)
                # 2. 50-day SMA >= 200-day SMA * 0.98 (not in secular downtrend)
                # 3. 6-month momentum positive
                trend_confirmed = (last_p > sma50) and (sma50 >= sma200 * 0.98) and (mom_6m > -0.02)
                
                if trend_confirmed:
                    signals.append({
                        "symbol": sym,
                        "yf_ticker": yf_tick,
                        "country": item["country"],
                        "combined_rank": item["combined_rank"],
                        "momentum_6m": mom_6m,
                        "target_capital": 4000.0,
                        "stop_price": round(last_p * (1.0 - self.stop_loss_pct / 100.0), 2),
                        "target_price": 0.0
                    })

                if len(signals) >= available_slots:
                    break

            return signals
