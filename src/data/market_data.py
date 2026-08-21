import yfinance as yf
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

class MarketDataProvider:
    def __init__(self):
        self._cache: Dict[str, pd.DataFrame] = {}

    def fetch_history(self, yf_ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        """Fetch historical price series from Yahoo Finance."""
        try:
            stock = yf.Ticker(yf_ticker)
            df = stock.history(period=period, interval=interval)
            if df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            print(f"[MarketData Error] Failed to fetch {yf_ticker}: {e}")
            return pd.DataFrame()

    def compute_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute full quantitative technical indicators suite."""
        if df.empty or len(df) < 30:
            return df

        data = df.copy()

        # 1. Moving Averages & Trend
        data['SMA_20'] = data['Close'].rolling(window=20).mean()
        data['SMA_50'] = data['Close'].rolling(window=50).mean()
        data['SMA_200'] = data['Close'].rolling(window=min(200, len(data))).mean()
        data['EMA_12'] = data['Close'].ewm(span=12, adjust=False).mean()
        data['EMA_26'] = data['Close'].ewm(span=26, adjust=False).mean()

        # 2. MACD (12, 26, 9)
        data['MACD'] = data['EMA_12'] - data['EMA_26']
        data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
        data['MACD_Hist'] = data['MACD'] - data['MACD_Signal']

        # 3. Relative Strength Index (RSI - 14)
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        data['RSI'] = 100 - (100 / (1 + rs))

        # 4. Bollinger Bands (20 periods, 2 std dev)
        rolling_std = data['Close'].rolling(window=20).std()
        data['BB_Middle'] = data['SMA_20']
        data['BB_Upper'] = data['BB_Middle'] + (rolling_std * 2)
        data['BB_Lower'] = data['BB_Middle'] - (rolling_std * 2)
        data['BB_Width'] = (data['BB_Upper'] - data['BB_Lower']) / data['BB_Middle']

        # 5. Average True Range (ATR - 14) & Volatility
        high_low = data['High'] - data['Low']
        high_close = (data['High'] - data['Close'].shift()).abs()
        low_close = (data['Low'] - data['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        data['ATR'] = ranges.max(axis=1).rolling(14).mean()
        data['ATR_Pct'] = data['ATR'] / data['Close']

        # 6. Volume Confirmation
        data['Vol_SMA_20'] = data['Volume'].rolling(window=20).mean()
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
        data['OBV_SMA_20'] = pd.Series(obv, index=data.index).rolling(window=20).mean()

        return data

    def get_market_snapshot(self, yf_ticker: str, is_uk_pence: bool = False) -> Dict[str, Any]:
        """Generate structured analytical market snapshot for a ticker."""
        df = self.fetch_history(yf_ticker, period="6mo", interval="1d")
        if df.empty or len(df) < 30:
            return {"success": False, "error": f"Insufficient data for {yf_ticker}"}

        df = self.compute_technical_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]

        current_price = float(last['Close'])
        unit_price = (current_price / 100.0) if is_uk_pence else current_price
        
        return {
            "success": True,
            "ticker": yf_ticker,
            "current_price": unit_price,
            "raw_price": current_price,
            "daily_return": (current_price - float(prev['Close'])) / float(prev['Close']),
            "indicators": {
                "rsi": float(last['RSI']) if not pd.isna(last['RSI']) else 50.0,
                "sma_20": (float(last['SMA_20']) / 100.0) if is_uk_pence else float(last['SMA_20']),
                "sma_50": (float(last['SMA_50']) / 100.0) if is_uk_pence else float(last['SMA_50']),
                "sma_200": (float(last['SMA_200']) / 100.0) if is_uk_pence else float(last['SMA_200']),
                "macd": float(last['MACD']),
                "macd_signal": float(last['MACD_Signal']),
                "macd_hist": float(last['MACD_Hist']),
                "bb_upper": (float(last['BB_Upper']) / 100.0) if is_uk_pence else float(last['BB_Upper']),
                "bb_lower": (float(last['BB_Lower']) / 100.0) if is_uk_pence else float(last['BB_Lower']),
                "bb_width": float(last['BB_Width']),
                "atr": (float(last['ATR']) / 100.0) if is_uk_pence else float(last['ATR']),
                "atr_pct": float(last['ATR_Pct']),
                "vol_ratio": float(last['Vol_Ratio']),
                "obv_trending_up": bool(last['OBV'] > last['OBV_SMA_20'])
            },
            "dataframe": df
        }

market_data = MarketDataProvider()
