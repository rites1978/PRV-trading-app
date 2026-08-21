import os
from pydantic import BaseModel, Field
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

class TradingSettings(BaseModel):
    # Environment & Credentials
    TRADING_ENV: str = Field(default_factory=lambda: os.getenv("TRADING_ENV", "demo").lower())
    TRADING212_API_KEY: str = Field(default_factory=lambda: os.getenv("TRADING212_API_KEY") or os.getenv("T212_API_KEY", ""))
    TRADING212_API_SECRET: str = Field(default_factory=lambda: os.getenv("TRADING212_API_SECRET") or os.getenv("T212_API_SECRET", ""))
    
    # Capital Management
    STARTING_CAPITAL: float = 50000.0
    MIN_CASH_BUFFER_PCT: float = 0.05  # 5% cash buffer always held
    MAX_DEPLOYMENT_NEUTRAL: float = 0.25 # 25% deployment in neutral markets
    MAX_DEPLOYMENT_STRONG: float = 0.60  # 60% deployment in strong markets
    MAX_DEPLOYMENT_EXCEPTIONAL: float = 0.85 # 85% deployment in exceptional markets
    
    # Risk Limits & Sizing
    MAX_DAILY_DRAWDOWN_PCT: float = 0.05  # 5% hard daily circuit breaker
    TARGET_POSITION_SIZE_PCT: float = 0.06 # Target 6% (~£3,000) per position
    MAX_POSITION_SIZE_PCT: float = 0.08    # Max 8% (~£4,000) of Core Capital per position
    MAX_SECTOR_EXPOSURE_PCT: float = 0.30  # Max 30% exposure per sector
    MAX_CONCURRENT_POSITIONS: int = 40     # Accommodate full diversified pool
    DEFAULT_STOP_LOSS_PCT: float = 0.025   # 2.5% stop loss
    DEFAULT_TAKE_PROFIT_PCT: float = 0.075 # 7.5% take profit (3:1 R:R target)
    MIN_REWARD_RISK_RATIO: float = 3.0     # 3:1 Reward to Risk
    
    # AI Scoring & Dynamic Execution Filters
    MIN_CONFIDENCE_THRESHOLD: float = 70.0 # Institutional deployment threshold
    SLIPPAGE_ESTIMATE_BPS: float = 10.0    # 10 bps slippage
    FX_FEE_BPS: float = 15.0               # 15 bps currency conversion fee for USD/GBP
    
    # Execution Intervals
    SCAN_INTERVAL_SECONDS: int = 15        # Responsive 15-second quant cycle
    MARKET_DATA_TIMEFRAME: str = "1d"
    
    # Database & Storage
    DB_PATH: str = Field(default_factory=lambda: os.getenv("DB_PATH", "prv_capital.db"))
    
    # Alerts
    TELEGRAM_BOT_TOKEN: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_CHAT_ID: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    NEWS_API_KEY: str = Field(default_factory=lambda: os.getenv("NEWS_API_KEY", ""))

settings = TradingSettings()
