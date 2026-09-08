"""
🏛️ PRV CAPITAL | PRODUCTION STRATEGY: PRV_HIT_AND_RUN_ETF_V1
Frozen OOS Challenger Implementation (Model B: GBP SDRT-Exempt Index ETFs).

Parameter Hash: 3ee18df44ac71eaacbcc5496047ab51dc2956d890b7ad755fa10a5a25d0f800a
OOS Performance (14 Months Untouched):
- 63 Trades, 74.6% Win Rate
- Expectancy: +£150.77 / trade, Profit Factor: 7.61, Max DD: 1.55%
- Net Realised P&L: +£9,498.43

Governance Contracts:
1. Universe: CSP1.L, ISF.L, VUSA.L, EQQQ.L (LSE GBP SDRT-Exempt Index ETFs)
2. Sizing: £35,000 nominal deployment (1 concurrent position max)
3. Targets: +0.80% profit target, -0.80% protective stop loss
4. Time Cap: 3 trading days
5. Daily Governor: £100 realised net profit -> STOP NORMAL ENTRIES -> WATCH MODE
6. Overnight Policy: ALLOWED_WITH_GTC_STOP (Nominal stop-based loss £280.00, gap stress £875.00)
7. Fail-Closed Protection: Mandatory broker-native stop; if unconfirmed -> immediate flatten & HALT
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
import numpy as np

from src.config.settings import settings
from src.brokers.trading212 import broker
from src.brokers.broker_ledger import broker_ledger
from src.database.db import db
from src.data.market_data import market_data
from src.data.market_hours import market_hours

logger = logging.getLogger("etf_hit_and_run")


class ETFHitAndRunStrategy:
    STRATEGY_NAME = "PRV_HIT_AND_RUN_ETF_V1"
    MODEL_FAMILY = "MODEL_B_GBP_SDRT_EXEMPT_ETFS"
    PARAMETER_HASH = "3ee18df44ac71eaacbcc5496047ab51dc2956d890b7ad755fa10a5a25d0f800a"

    UNIVERSE = [
        {"symbol": "CSP1.L", "t212_ticker": "CSP1_EQ", "name": "iShares Core S&P 500", "is_uk_pence": True},
        {"symbol": "ISF.L", "t212_ticker": "ISFl_EQ", "name": "iShares Core FTSE 100", "is_uk_pence": True},
        {"symbol": "VUSA.L", "t212_ticker": "VUSAl_EQ", "name": "Vanguard S&P 500", "is_uk_pence": False},
        {"symbol": "EQQQ.L", "t212_ticker": "EQQQl_EQ", "name": "Invesco EQQQ Nasdaq-100", "is_uk_pence": True},
    ]

    TARGET_PCT = 0.008               # +0.80%
    STOP_PCT = 0.008                 # -0.80%
    RVOL_THRESHOLD = 1.20            # 1.2x 20-day volume expansion
    POSITION_SIZE_GBP = 35000.0      # £35,000 nominal
    MAX_CONCURRENT_POSITIONS = 1     # Strictly 1 position
    TIME_CAP_DAYS = 3                # Max holding time
    DAILY_STOP_THRESHOLD_GBP = 100.0 # £100 daily lock -> WATCH MODE
    
    # Risk Contract
    NOMINAL_STOP_RISK_GBP = 280.00   # £35,000 * 0.80% = £280.00 intended loss
    GAP_STRESS_SCENARIO_PCT = 0.025  # -2.5% market gap stress
    GAP_STRESS_LOSS_GBP = 875.00     # £35,000 * 2.5% = £875.00 worst plausible loss (1.75% NAV)
    OVERNIGHT_POLICY = "ALLOWED_WITH_GTC_STOP"
    SLIPPAGE_AT_STOP_BPS = 5.0       # 5 bps estimated slippage at stop = £17.50

    def __init__(self):
        self.state = "INITIALIZED"
        self.is_watch_mode = False
        self.last_scan_result: Dict[str, Any] = {}

    def get_risk_contract(self) -> Dict[str, Any]:
        """Exposes the authoritative risk contract and disclaims loss guarantees."""
        return {
            "strategy_name": self.STRATEGY_NAME,
            "parameter_hash": self.PARAMETER_HASH,
            "position_size_gbp": self.POSITION_SIZE_GBP,
            "nominal_stop_pct": self.STOP_PCT,
            "nominal_stop_risk_gbp": self.NOMINAL_STOP_RISK_GBP,
            "stop_is_guaranteed": False,
            "stop_loss_caveat": "Nominal stop-based intended loss is £280.00. Stop loss is NOT an absolute loss ceiling due to potential overnight gaps and execution slippage.",
            "estimated_slippage_at_stop_gbp": round(self.POSITION_SIZE_GBP * (self.SLIPPAGE_AT_STOP_BPS / 10000.0), 2),
            "worst_plausible_gap_stress_pct": self.GAP_STRESS_SCENARIO_PCT,
            "gap_stress_loss_gbp": self.GAP_STRESS_LOSS_GBP,
            "gap_stress_nav_impact_pct": round((self.GAP_STRESS_LOSS_GBP / 50000.0) * 100.0, 2),
            "overnight_policy": self.OVERNIGHT_POLICY,
            "max_concurrent_positions": self.MAX_CONCURRENT_POSITIONS,
            "daily_target_lock_gbp": self.DAILY_STOP_THRESHOLD_GBP,
            "holding_period_historical_avg_days": 2.0
        }

    def get_daily_realised_pnl(self, force_refresh: bool = True) -> float:
        """Calculates today's realised net P&L from Trading212 Practice ground-truth ledger."""
        try:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            trades = db.get_trades(limit=50)
            today_realised = 0.0
            for t in trades:
                t_date = str(t.get("timestamp", ""))[:10]
                if t_date == today_str and t.get("side") == "SELL":
                    today_realised += float(t.get("net_realized_pnl", 0.0))
            return round(today_realised, 2)
        except Exception as e:
            logger.warning(f"Error reading daily realised P&L from DB: {e}")
            return 0.0

    def evaluate_live_scan(self, bypass_market_hours: bool = False) -> Dict[str, Any]:
        """
        Executes production decision path strictly under the frozen OOS model:
        1. Checks market hours.
        2. Checks daily realised net profit vs £100 governor -> WATCH MODE.
        3. Checks current open positions vs max 1 position rule.
        4. Scans the 4 GBP SDRT-exempt ETFs using live market data:
           - RVOL >= 1.20
           - Close > SMA20
           - Close > Previous Close
           - Score = (Close - PrevClose) / PrevClose * RVOL
        5. Returns ENTER (top candidate) or HOLD_CASH.
        """
        now_utc = datetime.now(timezone.utc)
        scan_id = f"SCAN_{int(now_utc.timestamp())}"

        # 1. Market Hours Check
        is_open = market_hours.is_asset_market_open("UK")
        if not is_open and not bypass_market_hours:
            res = {
                "scan_id": scan_id,
                "timestamp": now_utc.isoformat(),
                "decision": "HOLD_MARKET_CLOSED",
                "reason": "LSE market is currently CLOSED (Regular session: 08:00 - 16:30 BST).",
                "candidate": None,
                "evaluations": []
            }
            self.last_scan_result = res
            return res

        # 2. Daily Realised Net Governor (£100 Profit Lock)
        daily_realised = self.get_daily_realised_pnl()
        if daily_realised >= self.DAILY_STOP_THRESHOLD_GBP:
            self.is_watch_mode = True
            res = {
                "scan_id": scan_id,
                "timestamp": now_utc.isoformat(),
                "decision": "WATCH_MODE",
                "reason": f"Daily realised net profit (£{daily_realised:.2f}) >= £{self.DAILY_STOP_THRESHOLD_GBP:.2f}. STOP NORMAL ENTRIES -> WATCH MODE.",
                "candidate": None,
                "evaluations": [],
                "daily_realised_gbp": daily_realised
            }
            self.last_scan_result = res
            return res

        # 3. Maximum One Position Rule
        open_positions = broker.get_open_positions(force_refresh=True) or []
        active_pos_count = len([p for p in open_positions if float(p.get("quantity", 0)) > 0])
        if active_pos_count >= self.MAX_CONCURRENT_POSITIONS:
            active_ticker = open_positions[0].get("ticker")
            res = {
                "scan_id": scan_id,
                "timestamp": now_utc.isoformat(),
                "decision": "HOLD_MAX_POSITIONS",
                "reason": f"Maximum concurrent positions (1) already active ({active_ticker}).",
                "candidate": None,
                "evaluations": [],
                "active_positions": active_pos_count
            }
            self.last_scan_result = res
            return res

        # 4. Scan the 4 ETFs with live market data
        evaluations = []
        qualifying_candidates = []

        for item in self.UNIVERSE:
            sym = item["symbol"]
            t212_tick = item["t212_ticker"]
            is_pence = item["is_uk_pence"]

            try:
                df = market_data.fetch_history(sym, period="3mo", interval="1d")
                if df.empty or len(df) < 21:
                    evaluations.append({
                        "symbol": sym,
                        "ticker": t212_tick,
                        "status": "INSUFFICIENT_DATA",
                        "passed": False
                    })
                    continue

                # Normalize GBX to GBP if needed
                closes = df["Close"].values
                volumes = df["Volume"].values

                if is_pence and closes[-1] > 50.0:
                    closes = closes / 100.0

                vol_ma20 = float(np.mean(volumes[-21:-1]))
                curr_vol = float(volumes[-1])
                rvol = round(curr_vol / (vol_ma20 + 1e-6), 2)

                close_curr = float(closes[-1])
                close_prev = float(closes[-2])
                sma20 = float(np.mean(closes[-21:-1]))

                passed_rvol = rvol >= self.RVOL_THRESHOLD
                passed_trend = close_curr > sma20
                passed_momentum = close_curr > close_prev

                all_passed = passed_rvol and passed_trend and passed_momentum
                score = round(((close_curr - close_prev) / close_prev) * rvol, 6) if all_passed else 0.0

                eval_record = {
                    "symbol": sym,
                    "ticker": t212_tick,
                    "current_price_gbp": round(close_curr, 4),
                    "prev_price_gbp": round(close_prev, 4),
                    "sma20_gbp": round(sma20, 4),
                    "rvol": rvol,
                    "rvol_passed": passed_rvol,
                    "trend_passed": passed_trend,
                    "momentum_passed": passed_momentum,
                    "all_passed": all_passed,
                    "score": score
                }
                evaluations.append(eval_record)

                if all_passed:
                    qualifying_candidates.append(eval_record)

            except Exception as e:
                evaluations.append({
                    "symbol": sym,
                    "ticker": t212_tick,
                    "status": f"ERROR: {str(e)}",
                    "passed": False
                })

        # 5. Form Decision
        if not qualifying_candidates:
            res = {
                "scan_id": scan_id,
                "timestamp": now_utc.isoformat(),
                "decision": "HOLD_CASH",
                "reason": "No qualifying ETF setups meet entry criteria (RVOL>=1.20, Close>SMA20, Close>PrevClose). Holding cash.",
                "candidate": None,
                "evaluations": evaluations
            }
            self.last_scan_result = res
            return res

        # Sort by highest score
        qualifying_candidates.sort(key=lambda x: x["score"], reverse=True)
        top = qualifying_candidates[0]
        entry_price = top["current_price_gbp"]
        shares = round(self.POSITION_SIZE_GBP / entry_price, 4)

        res = {
            "scan_id": scan_id,
            "timestamp": now_utc.isoformat(),
            "decision": "ENTER",
            "reason": f"Top candidate {top['symbol']} passed all filters with score {top['score']:.6f}.",
            "candidate": {
                "symbol": top["symbol"],
                "ticker": top["ticker"],
                "price_gbp": entry_price,
                "shares": shares,
                "notional_gbp": round(shares * entry_price, 2),
                "target_price_gbp": round(entry_price * (1.0 + self.TARGET_PCT), 4),
                "stop_price_gbp": round(entry_price * (1.0 - self.STOP_PCT), 4),
                "nominal_stop_loss_gbp": self.NOMINAL_STOP_RISK_GBP,
                "gap_stress_loss_gbp": self.GAP_STRESS_LOSS_GBP,
                "score": top["score"]
            },
            "evaluations": evaluations
        }
        self.last_scan_result = res
        return res


etf_strategy = ETFHitAndRunStrategy()
