import yfinance as yf
import numpy as np

class RiskEngine:
    def __init__(self, portfolio_nav):
        self.portfolio_nav = portfolio_nav
        self.risk_per_trade = 10.0  # Target risk of £10 per trade

    def calculate_position(self, ticker):
        """Calculates quantity and stop-loss based on asset volatility (ATR)."""
        stock = yf.Ticker(ticker)
        df = stock.history(period="5d", interval="1h")
        
        # Calculate ATR (14 periods)
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]
        
        # Dynamic Stop-Loss = 2 * ATR
        stop_loss_distance = 2 * atr
        
        # Position Sizing: Risk_Per_Trade / Stop_Loss_Distance
        quantity = self.risk_per_trade / stop_loss_distance
        
        return {
            "quantity": round(quantity, 2),
            "stop_loss_price": round(df['Close'].iloc[-1] - stop_loss_distance, 2),
            "atr": round(atr, 2)
        }