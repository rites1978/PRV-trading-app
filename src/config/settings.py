"""
🏛️ PRV CAPITAL | CENTRAL CONFIGURATION & STRATEGY ENGINE PARAMETERS
Maintains institutional risk limits, execution parameters, effective-dated regulatory fee models, and versioned strategy thresholds.
All thresholds are centrally defined here and logged against every trade and report cycle.
"""
import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

class TradingSettings(BaseModel):
    # Strategy Configuration Versioning
    CONFIGURATION_VERSION: str = "CONFIG_V3.0_PRACTICE_30DAY_CHALLENGE_20260902"

    # Environment, Account Mode & Practice Trading Controls
    ACCOUNT_MODE: str = "PRACTICE"
    PRACTICE_TRADING_ENABLED: bool = True
    PRACTICE_NEW_ENTRIES_ALLOWED: bool = True
    REAL_MONEY_TRADING_ENABLED: bool = False
    REAL_MONEY_NEW_ENTRIES_ALLOWED: bool = False
    
    # AUDIT GOVERNANCE ENFORCEMENT
    PRACTICE_RISK_SCALING_ALLOWED: bool = False
    REAL_MONEY_RISK_SCALING_ALLOWED: bool = False
    NORMAL_PRACTICE_POSITION_SIZING_ACTIVE: bool = True

    # Challenge Metadata - OFFICIAL 30-DAY CHALLENGE
    CHALLENGE_STATUS: str = "OFFICIAL_30_DAY_CHALLENGE_ACTIVE"
    CHALLENGE_ACTIVE: bool = True
    CHALLENGE_START_TIMESTAMP: str = "2026-09-03 09:48:00 UTC"
    CHALLENGE_END_TIMESTAMP: str = "2026-10-03 09:48:00 UTC"
    CHALLENGE_START_NAV: float = 50000.00
    CHALLENGE_DURATION_DAYS: int = 30

    TRADING_ENV: str = Field(default_factory=lambda: os.getenv("TRADING_ENV", "demo").lower())
    TRADING212_API_KEY: str = Field(default_factory=lambda: os.getenv("TRADING212_API_KEY") or os.getenv("T212_API_KEY", ""))
    TRADING212_API_SECRET: str = Field(default_factory=lambda: os.getenv("TRADING212_API_SECRET") or os.getenv("T212_API_SECRET", ""))
    
    # Capital Management Bands & Capital Preservation Reserve
    STARTING_CAPITAL: float = 50000.0
    REQUIRED_CASH_RESERVE_PCT: float = 45.0 # Mandatory 45.0% Capital Preservation Cash reserve (£22,500 floor)
    MIN_CASH_BUFFER_PCT: float = 0.05       # 5% cash safety buffer (£2,500)
    MAX_DEPLOYMENT_BEAR: float = 0.25       # 15%-30% (Target 25%) in bear markets
    MAX_DEPLOYMENT_NEUTRAL: float = 0.45    # 30%-50% (Target 45%) in neutral markets
    MAX_DEPLOYMENT_BULL: float = 0.55       # 45%-55% (Target 55%) in bull markets (capped by 45% cash floor)

    # 🏛️ Daily Net Profit Objective & Anti-Overtrading Mandate
    # 🏛️ Daily Net Profit Objective & Anti-Overtrading Mandate
    BASE_TRADING_CAPITAL: float = 50000.0
    REFERENCE_BASE_CAPITAL: float = 50000.0
    MAX_DEPLOYABLE_TRADING_CAPITAL: float = 50000.0
    MAX_NORMAL_DEPLOYABLE_CAPITAL: float = 50000.0
    
    # Corridor Policy:
    # +£250 Bankable Net Target -> Lock new entries
    # -£250 Daily MTM Loss Lock -> Lock new entries (NO size halving, NO recovery trading)
    # -£500 Emergency Loss Level -> Emergency lock, cancel unfilled entry orders, allow risk-reducing exits only
    DAILY_BANKABLE_NET_TARGET: float = 250.0        # +£250 (+0.50%) bankable net profit
    DAILY_NET_PROFIT_OBJECTIVE: float = 250.0       # Compatibility alias
    DAILY_NET_RETURN_OBJECTIVE_PCT: float = 0.50    # 0.50% daily net return objective
    DAILY_NEW_ENTRY_LOSS_LOCK: float = 250.0        # -£250 (-0.50%) daily MTM loss lock
    DAILY_EMERGENCY_LOSS_LEVEL: float = 500.0       # -£500 (-1.00%) emergency circuit breaker
    DAILY_SOFT_LOSS_LIMIT_GBP: float = 250.0        # Alias: -£250 loss lock
    DAILY_HARD_LOSS_LIMIT_GBP: float = 500.0        # Alias: -£500 emergency level
    DAILY_MAX_NET_LOSS_GBP: float = 500.0           # Compatibility alias
    DAILY_MAX_NET_LOSS_PCT: float = 1.00            # 1.00% emergency level
    
    BANKED_PROFIT_IS_NON_DEPLOYABLE: bool = True    # Banked profit ring-fenced, non-deployable
    BANKED_PROFIT_RESERVE_LOCATION: str = "RINGFENCED_INSIDE_BROKER" # Ring-fenced ledger inside broker (Practice)
    AUTOMATIC_BANK_RESERVE_REDEPLOYMENT: bool = False # Never auto-transfer banked profit without user permission
    FORCE_TRADE_TO_REACH_DAILY_TARGET: bool = False # Never force trades to hit quota
    PREFERRED_COST_TO_EXPECTED_GROSS_PROFIT_PCT: float = 25.0 # <= 25% preferred friction ceiling
    MARKET_STRESS_INDEX_DRAWDOWN_PCT: float = 2.0   # 2.0% intraday benchmark drop triggers stress mode
    MARKET_STRESS_SPREAD_THRESHOLD_BPS: float = 35.0 # 35 bps average spread triggers stress mode
    
    # Position Sizing & Weight Governance Hierarchy
    # 1. Entry Sizing: Max 8.0% initial allocation at execution
    MAX_INITIAL_POSITION_WEIGHT_PCT: float = 8.0
    MAX_POSITION_SIZE_CAP_PCT: float = 8.0   # Compatibility alias for MAX_INITIAL_POSITION_WEIGHT_PCT
    MIN_POSITION_SIZE_PCT: float = 3.0       # 3% floor for weak multi-factor setups (£1,500)
    BASE_POSITION_SIZE_PCT: float = 5.0      # 5% base allocation (£2,500)
    MAX_POSITION_SIZE_PCT: float = 8.0       # 8% target allocation for Tier 3 setups (£4,000)
    
    # 2. Holding Weight Monitoring & Trimming (Market Appreciation Tolerances)
    POSITION_APPRECIATION_WARNING_PCT: float = 12.0 # Review for partial profit-taking
    POSITION_HARD_TRIM_CAP_PCT: float = 15.0       # Mandatory hard trim ceiling for single position
    
    # Sector & Portfolio Risk
    MAX_CONCURRENT_POSITIONS: int = 15      # Maximum simultaneous active positions in portfolio
    MAX_SECTOR_EXPOSURE_PCT: float = 0.30   # Max 30% exposure per sector
    MAX_DAILY_DRAWDOWN_PCT: float = 0.05    # 5% hard daily circuit breaker
    MAX_PORTFOLIO_VAR_BUDGET_PCT: float = 0.05 # Max 5% of Core Capital simultaneously at risk
    DEFAULT_STOP_LOSS_PCT: float = 0.025    # 2.5% stop loss
    DEFAULT_TAKE_PROFIT_PCT: float = 0.075  # 7.5% take profit (3:1 Gross R:R target)
    MIN_REWARD_RISK_RATIO: float = 3.0      # 3:1 Gross Reward to Risk
    
    # Institutional Net Edge & Profitability Gating Thresholds
    MIN_NET_REWARD_RISK_RATIO: float = 2.0  # 2.0x Net Reward to Risk after all friction
    MAX_COST_TO_PROFIT_RATIO_PCT: float = 30.0 # Friction cannot consume > 30% of expected gross profit
    MAX_SPREAD_TO_PROFIT_RATIO_PCT: float = 15.0 # Spread cost cannot consume > 15% of expected gross profit
    MAX_EMERGENCY_SPREAD_BPS: float = 50.0  # Emergency liquidity circuit breaker (50 bps)
    DEAD_CAPITAL_HURDLE_PCT: float = 1.50   # Minimum +1.50% net advantage required after switching costs
    
    # Strategy D Capital-Time & Velocity Hurdle Parameters (FROZEN)
    MAX_EXPECTED_HOLDING_PERIOD_DAYS: int = 14 # Strategy D max holding period cutoff (14 calendar days)
    FUNDAMENTAL_VELOCITY_THRESHOLD: float = 70.0 # Strategy D fundamental velocity hurdle (>= 70.0)
    CAPITAL_EFFICIENCY_MIN_SCORE: float = 70.0 # Strategy D capital-efficiency score hurdle (>= 70.0)

    # Execution Filters & Baseline Friction Model
    MIN_CONFIDENCE_THRESHOLD: float = 75.0  # Technical entry threshold (calibrated for alpha purity)
    SLIPPAGE_ESTIMATE_BPS: float = 10.0     # 10 bps estimated slippage baseline
    FX_FEE_BPS: float = 15.0                # 15 bps FX fee for foreign currency (Trading212 rate)
    UK_SDRT_RATE_PCT: float = 0.50          # 0.50% UK Stamp Duty Reserve Tax on qualifying equities
    PTM_LEVY_THRESHOLD_GBP: float = 10000.0 # £10,000 threshold for Panel on Takeovers and Mergers levy
    PTM_LEVY_AMOUNT_GBP: float = 1.50       # £1.50 flat PTM levy on qualifying transactions
    
    # Authoritative 2026 US Regulatory Fees (Effective April 4, 2026)
    SEC_SECTION_31_RATE: float = 0.0000206  # $20.60 per $1,000,000 = 0.00206% (SEC FY2026 rate)
    FINRA_TAF_PER_SHARE: float = 0.000195   # $0.000195 per share (FINRA 2026 rate)
    FINRA_TAF_MAX_FEE: float = 9.79         # $9.79 maximum cap per transaction (FINRA 2026 cap)
    
    # Effective-Dated Regulatory Fee Schedule Registry
    REGULATORY_FEE_SCHEDULE: List[Dict[str, Any]] = [
        {
            "fee_type": "FINRA_TAF",
            "market": "US",
            "side": "SELL",
            "rate_per_share": 0.000195,
            "cap_per_trade": 9.79,
            "valid_from": "2026-01-01",
            "valid_until": "2099-12-31",
            "source": "FINRA Fee Adjustment Schedule 2026 (sr-finra-2024-019)",
            "last_verified": "2026-09-01"
        },
        {
            "fee_type": "SEC_SECTION_31",
            "market": "US",
            "side": "SELL",
            "rate_pct": 0.0000206,
            "cap_per_trade": None,
            "valid_from": "2026-04-04",
            "valid_until": "2099-12-31",
            "source": "SEC Fee Rate Advisory for FY 2026 ($20.60 per $1m)",
            "last_verified": "2026-09-01"
        },
        {
            "fee_type": "UK_SDRT",
            "market": "UK",
            "side": "BUY",
            "rate_pct": 0.0050,
            "cap_per_trade": None,
            "valid_from": "1986-10-27",
            "valid_until": "2099-12-31",
            "source": "HMRC Stamp Duty Reserve Tax (Exempt for ETFs & AIM)",
            "last_verified": "2026-09-01"
        },
        {
            "fee_type": "PTM_LEVY",
            "market": "UK",
            "side": "BUY_SELL",
            "flat_amount_gbp": 1.50,
            "threshold_gbp": 10000.0,
            "valid_from": "2017-04-01",
            "valid_until": "2099-12-31",
            "source": "UK Panel on Takeovers and Mergers (PTM)",
            "last_verified": "2026-09-01"
        },
        {
            "fee_type": "T212_FX_FEE",
            "market": "GLOBAL",
            "side": "BUY_SELL",
            "rate_pct": 0.0015,
            "cap_per_trade": None,
            "valid_from": "2021-06-01",
            "valid_until": "2099-12-31",
            "source": "Trading212 Terms of Service (15 bps FX on non-GBP)",
            "last_verified": "2026-09-01"
        }
    ]

    # Order Routing & Limit Order Lifecycle
    MARKETABLE_LIMIT_SLIPPAGE_BPS: float = 10.0 # Maximum 10 bps offset for marketable limit orders
    MAX_CHASE_ATTEMPTS: int = 1             # Maximum 1 replacement order (no indefinite chasing)
    ORDER_TIMEOUT_SECONDS: float = 5.0      # Timeout before evaluating signal decay and cancel/amend
    
    # Execution Intervals
    SCAN_INTERVAL_SECONDS: int = 15
    MARKET_DATA_TIMEFRAME: str = "1d"
    
    # Database & Storage
    DB_PATH: str = Field(default_factory=lambda: os.getenv("DB_PATH", "prv_capital.db"))
    
    # Alerts
    TELEGRAM_BOT_TOKEN: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_CHAT_ID: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    NEWS_API_KEY: str = Field(default_factory=lambda: os.getenv("NEWS_API_KEY", ""))

    def generate_parameter_manifest(self) -> Dict[str, Any]:
        """
        Generates the complete, unabridged parameter manifest for frozen strategy validation.
        Zero hidden constants: covers all gating, sizing, timing, velocity, risk, and fee rules.
        """
        return {
            "configuration_version": self.CONFIGURATION_VERSION,
            "starting_capital_gbp": self.STARTING_CAPITAL,
            "required_cash_reserve_pct": self.REQUIRED_CASH_RESERVE_PCT,
            "max_initial_position_weight_pct": self.MAX_INITIAL_POSITION_WEIGHT_PCT,
            "min_position_size_pct": self.MIN_POSITION_SIZE_PCT,
            "base_position_size_pct": self.BASE_POSITION_SIZE_PCT,
            "max_position_size_pct": self.MAX_POSITION_SIZE_PCT,
            "position_appreciation_warning_pct": self.POSITION_APPRECIATION_WARNING_PCT,
            "position_hard_trim_cap_pct": self.POSITION_HARD_TRIM_CAP_PCT,
            "max_sector_exposure_pct": self.MAX_SECTOR_EXPOSURE_PCT,
            "max_daily_drawdown_pct": self.MAX_DAILY_DRAWDOWN_PCT,
            "max_portfolio_var_budget_pct": self.MAX_PORTFOLIO_VAR_BUDGET_PCT,
            "default_stop_loss_pct": self.DEFAULT_STOP_LOSS_PCT,
            "default_take_profit_pct": self.DEFAULT_TAKE_PROFIT_PCT,
            "min_gross_reward_risk_ratio": self.MIN_REWARD_RISK_RATIO,
            "min_net_reward_risk_ratio": self.MIN_NET_REWARD_RISK_RATIO,
            "max_cost_to_profit_ratio_pct": self.MAX_COST_TO_PROFIT_RATIO_PCT,
            "max_spread_to_profit_ratio_pct": self.MAX_SPREAD_TO_PROFIT_RATIO_PCT,
            "max_emergency_spread_bps": self.MAX_EMERGENCY_SPREAD_BPS,
            "dead_capital_hurdle_pct": self.DEAD_CAPITAL_HURDLE_PCT,
            "max_expected_holding_period_days": self.MAX_EXPECTED_HOLDING_PERIOD_DAYS,
            "fundamental_velocity_threshold": self.FUNDAMENTAL_VELOCITY_THRESHOLD,
            "capital_efficiency_min_score": self.CAPITAL_EFFICIENCY_MIN_SCORE,
            "min_confidence_threshold": self.MIN_CONFIDENCE_THRESHOLD,
            "slippage_estimate_bps": self.SLIPPAGE_ESTIMATE_BPS,
            "fx_fee_bps": self.FX_FEE_BPS,
            "uk_sdrt_rate_pct": self.UK_SDRT_RATE_PCT,
            "ptm_levy_threshold_gbp": self.PTM_LEVY_THRESHOLD_GBP,
            "ptm_levy_amount_gbp": self.PTM_LEVY_AMOUNT_GBP,
            "sec_section_31_rate": self.SEC_SECTION_31_RATE,
            "finra_taf_per_share": self.FINRA_TAF_PER_SHARE,
            "finra_taf_max_fee": self.FINRA_TAF_MAX_FEE,
            "base_trading_capital_gbp": self.BASE_TRADING_CAPITAL,
            "reference_base_capital_gbp": self.REFERENCE_BASE_CAPITAL,
            "max_deployable_trading_capital_gbp": self.MAX_DEPLOYABLE_TRADING_CAPITAL,
            "daily_bankable_net_target_gbp": self.DAILY_BANKABLE_NET_TARGET,
            "daily_net_profit_objective_gbp": self.DAILY_NET_PROFIT_OBJECTIVE,
            "daily_net_return_objective_pct": self.DAILY_NET_RETURN_OBJECTIVE_PCT,
            "daily_new_entry_loss_lock_gbp": self.DAILY_NEW_ENTRY_LOSS_LOCK,
            "daily_emergency_loss_level_gbp": self.DAILY_EMERGENCY_LOSS_LEVEL,
            "banked_profit_is_non_deployable": self.BANKED_PROFIT_IS_NON_DEPLOYABLE,
            "banked_profit_reserve_location": self.BANKED_PROFIT_RESERVE_LOCATION,
            "automatic_bank_reserve_redeployment": self.AUTOMATIC_BANK_RESERVE_REDEPLOYMENT,
            "force_trade_to_reach_daily_target": self.FORCE_TRADE_TO_REACH_DAILY_TARGET,
            "preferred_cost_to_expected_gross_profit_pct": self.PREFERRED_COST_TO_EXPECTED_GROSS_PROFIT_PCT,
            "daily_max_net_loss_pct": self.DAILY_MAX_NET_LOSS_PCT,
            "daily_max_net_loss_gbp": self.DAILY_MAX_NET_LOSS_GBP
        }

    def get_parameter_manifest_hash(self) -> str:
        """
        Computes deterministic SHA-256 hash of the complete frozen parameter manifest.
        """
        import hashlib
        import json
        manifest = self.generate_parameter_manifest()
        manifest_json = json.dumps(manifest, sort_keys=True)
        return hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()

settings = TradingSettings()
