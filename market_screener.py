import yfinance as yf
import pandas as pd

class GlobalMarketScreener:
    def __init__(self):
        # A broader universe combining US Tech, Finance, and UK LSE giants
        self.universe = [
            "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "GOOGL", 
            "JPM", "V", "MA",
            "AZN.L", "SHEL.L", "HSBA.L", "BP.L"  # UK LSE Stocks
        ]

    def scan_for_opportunities(self):
        print("🌍 Screener: Scanning global universe for alpha setups...")
        candidates = []
        
        for ticker in self.universe:
            try:
                # Fetch 1-month of daily data
                data = yf.download(ticker, period="1mo", interval="1d", progress=False)
                if data.empty or len(data) < 20:
                    continue
                
                # Calculate RSI (14-day) and SMA
                delta = data['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs.iloc[-1].item()))
                
                current_price = data['Close'].iloc[-1].item()
                sma_20 = data['Close'].rolling(window=20).mean().iloc[-1].item()
                
                # Setup 1: Oversold Bounce (RSI < 35)
                # Setup 2: Momentum Breakout (Price > 20 SMA + RSI > 60)
                if rsi < 35:
                    candidates.append({"ticker": ticker, "setup": "Oversold Bounce", "rsi": rsi, "conviction": 8.0})
                elif current_price > sma_20 and rsi > 60:
                    candidates.append({"ticker": ticker, "setup": "Momentum Breakout", "rsi": rsi, "conviction": 7.5})
                    
            except Exception as e:
                pass # Skip broken tickers silently during scan
                
        # Sort by conviction and return the top 3 candidates for the Boardroom
        sorted_candidates = sorted(candidates, key=lambda x: x['conviction'], reverse=True)[:3]
        print(f"🎯 Screener identified {len(sorted_candidates)} prime targets for AI Boardroom.")
        return sorted_candidates

if __name__ == "__main__":
    screener = GlobalMarketScreener()
    targets = screener.scan_for_opportunities()
    for t in targets:
        print(f"Candidate: {t['ticker']} | Setup: {t['setup']} | RSI: {t['rsi']:.1f}")