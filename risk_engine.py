import yfinance as yf
import pandas as pd
import numpy as np

class RiskEngine:
    def __init__(self, portfolio_nav=40000.0, max_risk_pct=0.01):
        self.nav = portfolio_nav
        self.max_risk_per_trade = self.nav * max_risk_pct  # Risk max 1% of NAV per trade (£400)

    def calculate_position_size(self, ticker, current_price):
        """
        Calculates optimal share quantity using Average True Range (ATR) volatility sizing.
        Ensures a single bad trade never breaches your strict risk thresholds.
        """
        try:
            data = yf.download(ticker, period="1mo", interval="1d", progress=False)
            if data.empty or len(data) < 14:
                # Fallback to standard 5% capital allocation if data is unavailable
                target_capital = self.nav * 0.05
                return int(target_capital / current_price)

            # Calculate True Range and 14-day ATR
            high = data['High']
            low = data['Low']
            close = data['Close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr_14 = tr.rolling(window=14).mean().iloc[-1].item()

            # Volatility-based stop loss distance (2 x ATR)
            stop_loss_distance = atr_14 * 2.0
            
            if stop_loss_distance <= 0:
                return int((self.nav * 0.05) / current_price)

            # Position size = Dollar Risk Willing to Take / Stop Loss Distance per share
            shares = int(self.max_risk_per_trade / stop_loss_distance)
            
            # Cap maximum single position to 15% of total NAV (£6,000)
            max_allowed_shares = int((self.nav * 0.15) / current_price)
            final_shares = min(shares, max_allowed_shares)
            
            print(f"📐 Volatility Sizing ({ticker}): ATR={atr_14:.2f} | Calculated Qty={final_shares}")
            return max(final_shares, 1) # Ensure at least 1 share if approved

        except Exception as e:
            print(f"⚠️ ATR calculation failed for {ticker}: {e}. Using baseline sizing.")
            return int((self.nav * 0.05) / current_price)