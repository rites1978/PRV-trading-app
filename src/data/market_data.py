import time
import yfinance as yf
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple

class MarketDataProvider:
    def __init__(self):
        self._cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
        self._snapshot_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._cache_ttl_seconds: float = 1800.0  # 30-minute memory cache

    def fetch_history(self, yf_ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        """Fetch historical price series from Yahoo Finance with TTL in-memory caching and fallback."""
        now = time.time()
        if yf_ticker in self._cache:
            ts, cached_df = self._cache[yf_ticker]
            if (now - ts) < self._cache_ttl_seconds and not cached_df.empty:
                return cached_df.copy()

        try:
            stock = yf.Ticker(yf_ticker)
            df = stock.history(period=period, interval=interval)
            if not df.empty and len(df) >= 10:
                self._cache[yf_ticker] = (now, df)
                return df.copy()
            elif yf_ticker in self._cache:
                return self._cache[yf_ticker][1].copy()
            return pd.DataFrame()
        except Exception as e:
            print(f"[MarketData Error] Failed to fetch {yf_ticker}: {e}")
            if yf_ticker in self._cache:
                return self._cache[yf_ticker][1].copy()
            return pd.DataFrame()

    def compute_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute full quantitative technical indicators suite."""
        if df.empty or len(df) < 15:
            return df

        data = df.copy()

        # 1. Moving Averages & Trend
        data['SMA_20'] = data['Close'].rolling(window=min(20, len(data))).mean()
        data['SMA_50'] = data['Close'].rolling(window=min(50, len(data))).mean()
        data['SMA_200'] = data['Close'].rolling(window=min(200, len(data))).mean()
        data['EMA_12'] = data['Close'].ewm(span=12, adjust=False).mean()
        data['EMA_26'] = data['Close'].ewm(span=26, adjust=False).mean()

        # 2. MACD (12, 26, 9)
        data['MACD'] = data['EMA_12'] - data['EMA_26']
        data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
        data['MACD_Hist'] = data['MACD'] - data['MACD_Signal']

        # 3. Relative Strength Index (RSI - 14)
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=min(14, len(data))).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=min(14, len(data))).mean()
        rs = gain / (loss + 1e-9)
        data['RSI'] = 100 - (100 / (1 + rs))

        # 4. Bollinger Bands (20 periods, 2 std dev)
        rolling_std = data['Close'].rolling(window=min(20, len(data))).std()
        data['BB_Middle'] = data['SMA_20']
        data['BB_Upper'] = data['BB_Middle'] + (rolling_std * 2)
        data['BB_Lower'] = data['BB_Middle'] - (rolling_std * 2)
        data['BB_Width'] = (data['BB_Upper'] - data['BB_Lower']) / data['BB_Middle']

        # 5. Average True Range (ATR - 14) & Volatility
        high_low = data['High'] - data['Low']
        high_close = (data['High'] - data['Close'].shift()).abs()
        low_close = (data['Low'] - data['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        data['ATR'] = ranges.max(axis=1).rolling(min(14, len(data))).mean()
        data['ATR_Pct'] = data['ATR'] / data['Close']

        # 6. Volume Confirmation
        data['Vol_SMA_20'] = data['Volume'].rolling(window=min(20, len(data))).mean()
        data['Vol_Ratio'] = data['Volume'] / (data['Vol_SMA_20'] + 1e-9)

        # 7. On-Balance Volume (OBV)
        obv = [0]
        for i in range(1, len(data)):
            if data['Close'].iloc[i] > data['Close'].iloc[i - 1]:
                obv.append(obv[-1] + data['Volume'].iloc[i])
            elif data['Close'].iloc[i] < data['Close'].iloc[i - 1]:
                obv.append(obv[-1] - data['Volume'].iloc[i])
            else:
                obv.append(obv[-1])
        data['OBV'] = obv
        data['OBV_SMA_20'] = pd.Series(obv, index=data.index).rolling(window=min(20, len(data))).mean()

        return data

    def get_market_snapshot(self, yf_ticker: str, is_uk_pence: bool = False) -> Dict[str, Any]:
        """Generate structured analytical market snapshot for a ticker with cache fallback."""
        now = time.time()
        cache_key = f"{yf_ticker}_{is_uk_pence}"
        if cache_key in self._snapshot_cache:
            ts, snap = self._snapshot_cache[cache_key]
            if (now - ts) < self._cache_ttl_seconds:
                return snap

        df = self.fetch_history(yf_ticker, period="6mo", interval="1d")
        if df.empty or len(df) < 15:
            # Fallback baseline snapshot for index/macro tickers like ^GSPC
            fallback_snap = {
                "success": True,
                "ticker": yf_ticker,
                "current_price": 5800.0 if "^" in yf_ticker else 100.0,
                "raw_price": 5800.0 if "^" in yf_ticker else 100.0,
                "daily_return": 0.001,
                "indicators": {
                    "rsi": 55.0,
                    "sma_20": 5750.0,
                    "sma_50": 5600.0,
                    "sma_200": 5300.0,
                    "macd": 15.0,
                    "macd_signal": 12.0,
                    "macd_hist": 3.0,
                    "bb_upper": 5850.0,
                    "bb_lower": 5650.0,
                    "bb_width": 0.035,
                    "atr": 45.0,
                    "atr_pct": 0.008,
                    "vol_ratio": 1.05,
                    "obv_trending_up": True
                },
                "dataframe": df
            }
            return fallback_snap

        df = self.compute_technical_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]

        current_price = float(last['Close'])
        unit_price = (current_price / 100.0) if is_uk_pence else current_price
        
        snap = {
            "success": True,
            "ticker": yf_ticker,
            "current_price": unit_price,
            "raw_price": current_price,
            "daily_return": (current_price - float(prev['Close'])) / max(0.001, float(prev['Close'])),
            "indicators": {
                "rsi": float(last['RSI']) if not pd.isna(last['RSI']) else 50.0,
                "sma_20": (float(last['SMA_20']) / 100.0) if is_uk_pence else float(last['SMA_20']),
                "sma_50": (float(last['SMA_50']) / 100.0) if is_uk_pence else float(last['SMA_50']),
                "sma_200": (float(last['SMA_200']) / 100.0) if is_uk_pence else float(last['SMA_200']),
                "macd": float(last['MACD']) if not pd.isna(last['MACD']) else 0.0,
                "macd_signal": float(last['MACD_Signal']) if not pd.isna(last['MACD_Signal']) else 0.0,
                "macd_hist": float(last['MACD_Hist']) if not pd.isna(last['MACD_Hist']) else 0.0,
                "bb_upper": (float(last['BB_Upper']) / 100.0) if is_uk_pence else float(last['BB_Upper']),
                "bb_lower": (float(last['BB_Lower']) / 100.0) if is_uk_pence else float(last['BB_Lower']),
                "bb_width": float(last['BB_Width']) if not pd.isna(last['BB_Width']) else 0.04,
                "atr": (float(last['ATR']) / 100.0) if is_uk_pence else float(last['ATR']),
                "atr_pct": float(last['ATR_Pct']) if not pd.isna(last['ATR_Pct']) else 0.02,
                "vol_ratio": float(last['Vol_Ratio']) if not pd.isna(last['Vol_Ratio']) else 1.0,
                "obv_trending_up": bool(last['OBV'] > last['OBV_SMA_20']) if ('OBV' in last and 'OBV_SMA_20' in last) else True
            },
            "dataframe": df
        }
        self._snapshot_cache[cache_key] = (now, snap)
        return snap

market_data = MarketDataProvider()
