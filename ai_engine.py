import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional

class AIEngine:
    def __init__(self):
        pass

    def fetch_market_data(self, ticker: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
        """Fetch historical candlestick data from Yahoo Finance."""
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)
            if df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            print(f"[AIEngine Error fetching {ticker}] {e}")
            return pd.DataFrame()

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators (RSI, SMA, EMA, MACD, Bollinger Bands, ATR)."""
        if df.empty or len(df) < 20:
            return df

        data = df.copy()
        
        # 1. Simple Moving Averages (SMA) & Exponential Moving Averages (EMA)
        data['SMA_20'] = data['Close'].rolling(window=20).mean()
        data['SMA_50'] = data['Close'].rolling(window=min(50, len(data))).mean()
        data['EMA_12'] = data['Close'].ewm(span=12, adjust=False).mean()
        data['EMA_26'] = data['Close'].ewm(span=26, adjust=False).mean()

        # 2. MACD (Moving Average Convergence Divergence)
        data['MACD'] = data['EMA_12'] - data['EMA_26']
        data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
        data['MACD_Hist'] = data['MACD'] - data['MACD_Signal']

        # 3. RSI (Relative Strength Index - 14)
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

        # 5. ATR (Average True Range - 14)
        high_low = data['High'] - data['Low']
        high_close = (data['High'] - data['Close'].shift()).abs()
        low_close = (data['Low'] - data['Close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        data['ATR'] = true_range.rolling(14).mean()

        return data

    def analyze_ticker(self, yf_ticker: str, is_uk_pence: bool = False) -> Dict[str, Any]:
        """
        Analyze a ticker, compute technical indicators, and produce an AI decision (BUY, SELL, HOLD).
        """
        df = self.fetch_market_data(yf_ticker, period="3mo", interval="1d")
        if df.empty or len(df) < 20:
            return {
                "success": False,
                "ticker": yf_ticker,
                "error": f"Insufficient market data for {yf_ticker}"
            }

        df = self.compute_indicators(df)
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        current_price = float(last_row['Close'])
        # UK stocks in Yahoo Finance are often in pence (e.g. BARC.L = 220p -> £2.20)
        display_price = (current_price / 100.0) if is_uk_pence else current_price
        
        rsi = float(last_row['RSI']) if not pd.isna(last_row['RSI']) else 50.0
        sma_20 = float(last_row['SMA_20']) if not pd.isna(last_row['SMA_20']) else current_price
        sma_50 = float(last_row['SMA_50']) if not pd.isna(last_row['SMA_50']) else current_price
        macd = float(last_row['MACD']) if not pd.isna(last_row['MACD']) else 0.0
        macd_signal = float(last_row['MACD_Signal']) if not pd.isna(last_row['MACD_Signal']) else 0.0
        macd_hist = float(last_row['MACD_Hist']) if not pd.isna(last_row['MACD_Hist']) else 0.0
        bb_upper = float(last_row['BB_Upper']) if not pd.isna(last_row['BB_Upper']) else current_price * 1.05
        bb_lower = float(last_row['BB_Lower']) if not pd.isna(last_row['BB_Lower']) else current_price * 0.95
        atr = float(last_row['ATR']) if not pd.isna(last_row['ATR']) else current_price * 0.02

        # -------------------------------------------------------------
        # Multi-factor AI Scoring System (-100 to +100)
        # -------------------------------------------------------------
        score = 0.0
        reasons = []

        # 1. RSI Factor
        if rsi < 30:
            score += 30
            reasons.append(f"🟢 RSI is Oversold ({rsi:.1f} < 30), indicating strong upward rebound potential.")
        elif rsi < 40:
            score += 15
            reasons.append(f"🟢 RSI is moderately low ({rsi:.1f}), showing positive risk/reward entry.")
        elif rsi > 70:
            score -= 30
            reasons.append(f"🔴 RSI is Overbought ({rsi:.1f} > 70), indicating high risk of pullback.")
        elif rsi > 60:
            score -= 15
            reasons.append(f"🔴 RSI is elevated ({rsi:.1f}), showing fading momentum.")
        else:
            reasons.append(f"⚪ RSI is neutral ({rsi:.1f}).")

        # 2. Moving Average Trend (SMA 20 vs SMA 50)
        if current_price > sma_20 and sma_20 > sma_50:
            score += 25
            reasons.append(f"🟢 Golden Trend: Price is above SMA 20 & SMA 50 (Bullish alignment).")
        elif current_price < sma_20 and sma_20 < sma_50:
            score -= 25
            reasons.append(f"🔴 Death Trend: Price is below SMA 20 & SMA 50 (Bearish alignment).")
        elif current_price > sma_20:
            score += 10
            reasons.append(f"🟢 Short-term strength: Price traded above 20-day average.")
        else:
            score -= 10
            reasons.append(f"🔴 Short-term weakness: Price traded below 20-day average.")

        # 3. MACD Momentum
        if macd > macd_signal and macd_hist > 0:
            score += 25
            reasons.append("🟢 MACD line is above signal line with expanding positive histogram.")
        elif macd < macd_signal and macd_hist < 0:
            score -= 25
            reasons.append("🔴 MACD line is below signal line with expanding negative histogram.")
        else:
            reasons.append("⚪ MACD momentum is consolidating.")

        # 4. Bollinger Bands
        if current_price <= bb_lower * 1.01:
            score += 20
            reasons.append("🟢 Price touching or near Lower Bollinger Band (Potential mean-reversion buy).")
        elif current_price >= bb_upper * 0.99:
            score -= 20
            reasons.append("🔴 Price touching or near Upper Bollinger Band (Potential resistance/exhaustion).")

        # Clamp Score
        score = max(-100.0, min(100.0, score))

        # Determine Signal & Confidence
        if score >= 35:
            signal = "BUY"
            confidence = int(min(98, 50 + (score / 2.0)))
        elif score <= -35:
            signal = "SELL"
            confidence = int(min(98, 50 + (abs(score) / 2.0)))
        else:
            signal = "HOLD"
            confidence = int(max(40, 100 - abs(score)))

        return {
            "success": True,
            "ticker": yf_ticker,
            "signal": signal,
            "confidence": confidence,
            "score": round(score, 1),
            "current_price": display_price,
            "raw_price": current_price,
            "indicators": {
                "rsi": round(rsi, 2),
                "sma_20": round(sma_20 / 100.0 if is_uk_pence else sma_20, 2),
                "sma_50": round(sma_50 / 100.0 if is_uk_pence else sma_50, 2),
                "macd": round(macd, 4),
                "macd_signal": round(macd_signal, 4),
                "bb_upper": round(bb_upper / 100.0 if is_uk_pence else bb_upper, 2),
                "bb_lower": round(bb_lower / 100.0 if is_uk_pence else bb_lower, 2),
                "atr": round(atr / 100.0 if is_uk_pence else atr, 4)
            },
            "reasons": reasons,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dataframe": df
        }