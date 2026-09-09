"""
🏛️ PRV CAPITAL | RATIFIED PRODUCTION STRATEGY: PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1
Architecture Class: PRV Core Compounding Engine
Status: RATIFIED FOR PRACTICE PRODUCTION INTEGRATION

Cryptographic Invariants:
- Frozen Manifest SHA-256: e5026d52086a5cdf5597cccbba96233a3f263411d84dea8bd3e36891d60be361
- Research Strategy Code SHA-256: 9f4942f11bd56a87cd2c651a24eff2f64a528d46f9ba95be7bb33b7589189929

Specification:
1. Universe: CSP1, EQQQ, IWDA/SWDA, ISF, EMIM, SGLN, IGLT (London SDRT-Exempt ETFs)
2. Ranking Metric: 20-Day Annualized Sharpe Momentum = Ret20d / Vol20d
3. Trend Gate: Asset Day T-1 Close > 200-day SMA AND Sharpe Momentum > 0.0
4. Rebalance Horizon: 10 trading days (bi-weekly rotation)
5. Capital Allocation: £40,000 nominal per position (1 concurrent position max)
6. Risk Management: -2.0% protective stop loss from entry fill price
7. Execution Timing: Day T 08:00 LSE Market Open
8. Point-in-Time Causality: Evaluated strictly on completed Day T-1 close data.
"""
import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger("core_compounding_v1")

EXPECTED_MANIFEST_SHA256 = "e5026d52086a5cdf5597cccbba96233a3f263411d84dea8bd3e36891d60be361"
EXPECTED_RESEARCH_CODE_SHA256 = "9f4942f11bd56a87cd2c651a24eff2f64a528d46f9ba95be7bb33b7589189929"


class CoreCompoundingStrategy:
    STRATEGY_ID = "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1"
    ARCHITECTURE_CLASS = "PRV_CORE_COMPOUNDING_ENGINE"
    STATUS = "RATIFIED_FOR_PRACTICE_PRODUCTION_INTEGRATION"
    
    # Exact 7-Instrument Certified Universe
    CERTIFIED_UNIVERSE = [
        {
            "symbol": "CSP1",
            "yf_ticker": "CSP1.L",
            "t212_ticker": "CSP1_EQ",
            "isin": "IE00B5BMR087",
            "name": "iShares Core S&P 500 UCITS ETF GBP",
            "asset_class": "Equities (US S&P 500)",
            "currency": "GBX",
            "is_uk_pence": True,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        },
        {
            "symbol": "EQQQ",
            "yf_ticker": "EQQQ.L",
            "t212_ticker": "EQQQl_EQ",
            "isin": "IE0032077012",
            "name": "Invesco EQQQ Nasdaq-100 UCITS ETF GBP",
            "asset_class": "Equities (US Tech / Nasdaq)",
            "currency": "GBX",
            "is_uk_pence": True,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        },
        {
            "symbol": "IWDA",
            "yf_ticker": "IWDA.L",
            "t212_ticker": "SWDAl_EQ",
            "t212_ticker_alt": "IWDAl_EQ",
            "isin": "IE00B4L5Y983",
            "name": "iShares Core MSCI World UCITS ETF GBP",
            "asset_class": "Equities (Global Developed)",
            "currency": "GBX",
            "is_uk_pence": True,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        },
        {
            "symbol": "ISF",
            "yf_ticker": "ISF.L",
            "t212_ticker": "ISFl_EQ",
            "isin": "IE0005042456",
            "name": "iShares Core FTSE 100 UCITS ETF GBP",
            "asset_class": "Equities (UK Large Cap)",
            "currency": "GBX",
            "is_uk_pence": True,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        },
        {
            "symbol": "EMIM",
            "yf_ticker": "EMIM.L",
            "t212_ticker": "EMIMl_EQ",
            "isin": "IE00BKM4GZ66",
            "name": "iShares Core MSCI Emerging Markets IMI ETF GBP",
            "asset_class": "Equities (Emerging Markets)",
            "currency": "GBX",
            "is_uk_pence": True,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        },
        {
            "symbol": "SGLN",
            "yf_ticker": "SGLN.L",
            "t212_ticker": "SGLNl_EQ",
            "isin": "IE00B4ND3602",
            "name": "iShares Physical Gold ETC GBP",
            "asset_class": "Commodities (Physical Gold Safe Haven)",
            "currency": "GBX",
            "is_uk_pence": True,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        },
        {
            "symbol": "IGLT",
            "yf_ticker": "IGLT.L",
            "t212_ticker": "IGLTl_EQ",
            "isin": "IE00B1FZSB30",
            "name": "iShares Core UK Gilts UCITS ETF GBP",
            "asset_class": "Fixed Income (UK Gilts / Rates)",
            "currency": "GBP",
            "is_uk_pence": False,
            "sdrt_exempt": True,
            "broker_allowed_precision": 3,
            "broker_allowed_increment": 0.001
        }
    ]

    # Exact Frozen Parameters
    MOM_LOOKBACK_BARS = 20
    VOL_LOOKBACK_BARS = 20
    REBALANCE_DAYS = 10
    POSITION_SIZE_GBP = 40000.0
    MAX_CONCURRENT_POSITIONS = 1
    STOP_LOSS_PCT = 0.02
    REGIME_SMA_LOOKBACK = 200
    EXECUTION_TIME_BST = "08:00:00"

    def __init__(self):
        self.verify_cryptographic_integrity()
        self.last_ranking_evaluation: Optional[Dict[str, Any]] = None
        self.days_since_rebalance: int = 0

    @classmethod
    def verify_cryptographic_integrity(cls) -> Dict[str, str]:
        """
        Phase 1 Mandate: Validates SHA-256 hashes of manifest and strategy code.
        Fails closed on any mismatch.
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        research_file = os.path.join(base_dir, "src", "research", "strategies", "prv_core_compounding_v1.py")
        manifest_file = os.path.join(base_dir, "data", "frozen_strategy_manifest_core_v1.json")

        if not os.path.exists(research_file):
            raise FileNotFoundError(f"Research strategy file missing: {research_file}")
        if not os.path.exists(manifest_file):
            raise FileNotFoundError(f"Frozen manifest file missing: {manifest_file}")

        with open(research_file, "rb") as f:
            code_hash = hashlib.sha256(f.read()).hexdigest()
        
        with open(manifest_file, "r") as f:
            manifest_data = json.load(f)
            manifest_hash = manifest_data.get("master_manifest_sha256", "")

        if code_hash != EXPECTED_RESEARCH_CODE_SHA256:
            msg = f"CRYPTOGRAPHIC_INTEGRITY_BREACH: Strategy code SHA256 {code_hash} != Expected {EXPECTED_RESEARCH_CODE_SHA256}"
            logger.critical(msg)
            raise RuntimeError(msg)

        if manifest_hash != EXPECTED_MANIFEST_SHA256:
            msg = f"CRYPTOGRAPHIC_INTEGRITY_BREACH: Manifest SHA256 {manifest_hash} != Expected {EXPECTED_MANIFEST_SHA256}"
            logger.critical(msg)
            raise RuntimeError(msg)

        return {"code_sha256": code_hash, "manifest_sha256": manifest_hash}

    def evaluate_point_in_time_signal(
        self,
        current_t: Any,
        prev_t: Optional[Any] = None,
        historical_daily_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> Dict[str, Any]:
        """
        Authoritative Point-in-Time Signal Generator for PRV Core Compounding Engine V1.
        Strictly observes completed Day T-1 close data with ZERO lookahead.
        """
        if historical_daily_data is None:
            raise ValueError("historical_daily_data is required for signal evaluation")

        current_ts = pd.Timestamp(current_t)
        if prev_t is None:
            # Infer immediate previous bar
            any_df = next(iter(historical_daily_data.values()))
            prev_bars = any_df.loc[any_df.index < current_ts]
            if len(prev_bars) == 0:
                return {"decision": "HOLD_CASH", "selected_symbol": None, "selected_target_key": None, "rankings": []}
            prev_ts = prev_bars.index[-1]
        else:
            prev_ts = pd.Timestamp(prev_t)

        eligible = []
        full_rankings = []

        for inst in self.CERTIFIED_UNIVERSE:
            sym = inst["symbol"]
            df_key = f"{sym}_L"
            if df_key not in historical_daily_data:
                df_key = sym if sym in historical_daily_data else None

            if not df_key or df_key not in historical_daily_data:
                continue

            df = historical_daily_data[df_key]
            if prev_ts not in df.index or current_ts not in df.index:
                continue

            prev_bar = df.loc[prev_ts]
            c_prev = float(prev_bar["Close"])
            sma200 = float(prev_bar["SMA200"])
            sharpe_score = float(prev_bar["MOM_SHARPE"])

            record = {
                "symbol": sym,
                "target_key": df_key,
                "t212_ticker": inst["t212_ticker"],
                "observation_timestamp": str(prev_ts),
                "decision_timestamp": str(current_ts),
                "close_t_minus_1": round(c_prev, 4),
                "sma200": round(sma200, 4),
                "sharpe_score": round(sharpe_score, 4),
                "above_sma200": c_prev > sma200,
                "positive_sharpe": sharpe_score > 0.0,
                "eligible": (c_prev > sma200 and sharpe_score > 0.0)
            }
            full_rankings.append(record)
            if record["eligible"]:
                eligible.append((sym, df_key, inst["t212_ticker"], sharpe_score, record))

        eligible.sort(key=lambda x: x[3], reverse=True)
        full_rankings.sort(key=lambda x: x["sharpe_score"], reverse=True)

        selected_candidate = eligible[0] if eligible else None

        result = {
            "strategy_id": self.STRATEGY_ID,
            "as_of_date": str(current_ts)[:10],
            "current_timestamp": str(current_ts),
            "previous_timestamp": str(prev_ts),
            "decision_time_bst": self.EXECUTION_TIME_BST,
            "selected_symbol": selected_candidate[0] if selected_candidate else None,
            "selected_target_key": selected_candidate[1] if selected_candidate else None,
            "selected_t212_ticker": selected_candidate[2] if selected_candidate else None,
            "selected_score": round(selected_candidate[3], 4) if selected_candidate else 0.0,
            "decision": "ENTER" if selected_candidate else "HOLD_CASH",
            "position_size_gbp": self.POSITION_SIZE_GBP,
            "stop_loss_pct": self.STOP_LOSS_PCT,
            "rankings": full_rankings,
            "eligible_candidates_count": len(eligible)
        }
        self.last_ranking_evaluation = result
        return result

    def evaluate_position_lifecycle(
        self,
        current_symbol_or_key: str,
        entry_price_gbp: float,
        current_low_gbp: float,
        should_rebalance: bool,
        target_symbol_or_key: Optional[str]
    ) -> Tuple[bool, str]:
        """
        Evaluates lifecycle exit conditions:
        1. Protective Stop Loss: current Low <= entry_price * (1 - 0.02)
        2. Rebalance Rotation: should_rebalance AND current_symbol != target_symbol
        """
        clean_cur = current_symbol_or_key.replace("_L", "")
        clean_tgt = target_symbol_or_key.replace("_L", "") if target_symbol_or_key else None

        stop_price = entry_price_gbp * (1.0 - self.STOP_LOSS_PCT)
        if current_low_gbp <= stop_price:
            return True, "STOP_LOSS"

        if should_rebalance and clean_cur != clean_tgt:
            return True, "REBALANCE_ROTATION"

        return False, "HOLD"

    def get_instrument_metadata(self, symbol_or_ticker: Optional[str]) -> Dict[str, Any]:
        """Returns authoritative broker instrument metadata including allowed precision and increment."""
        if not symbol_or_ticker:
            return {"broker_allowed_precision": 3, "broker_allowed_increment": 0.001}
        clean = str(symbol_or_ticker).replace("_L", "").replace(".L", "").replace("l_EQ", "").replace("_EQ", "").upper()
        for inst in self.CERTIFIED_UNIVERSE:
            inst_sym = inst["symbol"].upper()
            inst_t212 = inst["t212_ticker"].upper()
            inst_alt = inst.get("t212_ticker_alt", "").upper()
            if clean in (inst_sym, inst_t212.replace("L_EQ", "").replace("_EQ", ""), inst_alt.replace("L_EQ", "").replace("_EQ", "")):
                return inst
        return {"broker_allowed_precision": 3, "broker_allowed_increment": 0.001}

    def floor_to_broker_increment(
        self,
        raw_qty: float,
        increment: float = 0.001,
        precision: int = 3
    ) -> float:
        """
        Floors raw quantity to the broker-supported increment without rounding upward.
        Guarantees deployable capital and risk ceiling are never exceeded.
        """
        if raw_qty <= 0 or increment <= 0:
            return 0.0
        import math
        factor = round(1.0 / increment)
        floored = math.floor(raw_qty * factor + 1e-9) / factor
        return round(floored, precision)

    def calculate_order_shares(
        self,
        entry_price_gbp: float,
        available_cash_gbp: float = 50000.0,
        total_nav_gbp: Optional[float] = None,
        symbol: Optional[str] = None
    ) -> float:
        """Calculates exact order quantity bounded by available cash, 80% NAV, and floored to broker increment."""
        if entry_price_gbp <= 0:
            return 0.0
        max_by_nav = (float(total_nav_gbp) * 0.80 - 15.0) if total_nav_gbp is not None else self.POSITION_SIZE_GBP
        deployable = min(self.POSITION_SIZE_GBP, available_cash_gbp, max_by_nav)
        if deployable <= 0:
            return 0.0
        raw_qty = deployable / entry_price_gbp
        meta = self.get_instrument_metadata(symbol) if symbol else {"broker_allowed_precision": 3, "broker_allowed_increment": 0.001}
        precision = int(meta.get("broker_allowed_precision", 3))
        increment = float(meta.get("broker_allowed_increment", 0.001))
        return self.floor_to_broker_increment(raw_qty, increment=increment, precision=precision)


core_compounding_strategy = CoreCompoundingStrategy()
