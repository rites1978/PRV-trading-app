import yfinance as yf

class HedgingEngine:
    def __init__(self):
        # We use the S&P 500 ETF (SPY) as our global macro baseline
        self.macro_benchmark = "SPY"
        # Inverse ETF available on T212 (e.g., Short QQQ or VIX tracker)
        self.inverse_hedge_ticker = "QQQS.L" # WisdomTree NASDAQ 100 3x Daily Short

    def check_macro_regime(self):
        print(f"🛡️ Hedging Engine: Analyzing {self.macro_benchmark} macro regime...")
        try:
            # Fetch 1 year of data to calculate the 200-day moving average
            data = yf.download(self.macro_benchmark, period="1y", interval="1d", progress=False)
            if data.empty or len(data) < 200:
                return "BULL"

            current_price = data['Close'].iloc[-1].item()
            sma_200 = data['Close'].rolling(window=200).mean().iloc[-1].item()
            sma_50 = data['Close'].rolling(window=50).mean().iloc[-1].item()

            # Regime identification
            if current_price < sma_200 and sma_50 < sma_200:
                print("🚨 MACRO BEAR REGIME DETECTED: SPY trading below 200 SMA.")
                return "BEAR"
            else:
                print("✅ MACRO BULL REGIME: Global markets structurally sound.")
                return "BULL"
                
        except Exception as e:
            print(f"⚠️ Hedging engine offline due to data error: {e}")
            return "BULL" # Default to bull if API fails to prevent false shorts

    def get_hedge_asset(self):
        """Returns the ticker to buy if we need to short the market."""
        return self.inverse_hedge_ticker