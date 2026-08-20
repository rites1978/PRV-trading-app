import yfinance as yf
from db_manager import db

class WatchlistManager:
    def __init__(self):
        pass

    def get_watchlist_data(self):
        """Fetches tracked tickers from Supabase and pulls live market data via yfinance"""
        try:
            response = db.client.table("friend_watchlist").select("*").execute()
            items = response.data if response.data else []
            
            watchlist_results = []
            for item in items:
                ticker = item.get('ticker')
                notes = item.get('notes', '')
                
                # Fetch live data
                stock = yf.Ticker(ticker)
                hist = stock.history(period="2d")
                
                if not hist.empty and len(hist) >= 1:
                    current_price = hist['Close'].iloc[-1].item()
                    prev_close = hist['Close'].iloc[-2].item() if len(hist) >= 2 else current_price
                    change_pct = ((current_price - prev_close) / prev_close) * 100
                else:
                    current_price = 0.0
                    change_pct = 0.0

                watchlist_results.append({
                    "ticker": ticker,
                    "price": current_price,
                    "change_pct": change_pct,
                    "notes": notes
                })
                
            return watchlist_results
        except Exception as e:
            print(f"⚠️ Error fetching watchlist: {e}")
            return []

    def add_ticker(self, ticker, notes=""):
        try:
            db.client.table("friend_watchlist").insert({
                "ticker": ticker.upper(),
                "notes": notes
            }).execute()
            return True
        except Exception as e:
            print(f"❌ Error adding to watchlist: {e}")
            return false
        import yfinance as yf
from db_manager import db

class WatchlistManager:
    def __init__(self):
        pass

    def get_watchlist_data(self):
        """Fetches tracked tickers from Supabase and pulls live market data via yfinance"""
        try:
            response = db.client.table("friend_watchlist").select("*").execute()
            items = response.data if response.data else []
            
            watchlist_results = []
            for item in items:
                ticker = item.get('ticker', '').upper().strip()
                notes = item.get('notes', '')
                
                # Fetch live data & company name
                stock = yf.Ticker(ticker)
                info = stock.info
                company_name = info.get('shortName', ticker)
                
                hist = stock.history(period="2d")
                if not hist.empty and len(hist) >= 1:
                    current_price = hist['Close'].iloc[-1].item()
                    prev_close = hist['Close'].iloc[-2].item() if len(hist) >= 2 else current_price
                    change_pct = ((current_price - prev_close) / prev_close) * 100
                else:
                    current_price = 0.0
                    change_pct = 0.0

                watchlist_results.append({
                    "ticker": ticker,
                    "name": company_name,
                    "price": current_price,
                    "change_pct": change_pct,
                    "notes": notes
                })
                
            return watchlist_results
        except Exception as e:
            print(f"⚠️ Error fetching watchlist: {e}")
            return []

    def add_ticker(self, ticker, notes=""):
        try:
            clean_ticker = ticker.upper().strip()
            # Validate ticker exists using yfinance
            test_stock = yf.Ticker(clean_ticker)
            hist = test_stock.history(period="1d")
            if hist.empty:
                return False, "Invalid ticker symbol or company not found."

            db.client.table("friend_watchlist").insert({
                "ticker": clean_ticker,
                "notes": notes
            }).execute()
            return True, "Successfully added"
        except Exception as e:
            return False, str(e)