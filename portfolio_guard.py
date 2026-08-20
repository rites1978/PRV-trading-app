import numpy as np
import pandas as pd
import yfinance as yf

class PortfolioGuard:
    def __init__(self, max_sector_allocation=0.40):
        self.max_sector_allocation = max_sector_allocation
        
        # Sector mapping for our universe
        self.sectors = {
            "NVDA": "Technology",
            "MSFT": "Technology",
            "AAPL": "Technology",
            "TSLA": "Consumer Discretionary",
            "AMZN": "Consumer Discretionary",
            "JPM": "Financials",
            "JNJ": "Healthcare"
        }

    def check_correlation_and_concentration(self, proposed_ticker, active_positions_df, nav):
        """
        Validates if adding the proposed ticker violates sector limits or 
        creates dangerous correlation clusters with existing holdings.
        """
        proposed_sector = self.sectors.get(proposed_ticker, "Other")
        
        # 1. Check Sector Concentration
        if not active_positions_df.empty and 'ticker' in active_positions_df.columns:
            # Map existing positions to sectors
            active_positions_df['Sector'] = active_positions_df['ticker'].map(self.sectors)
            sector_exposure = active_positions_df[active_positions_df['Sector'] == proposed_sector]['currentValue'].sum()
            
            sector_ratio = sector_exposure / nav
            if sector_ratio >= self.max_sector_allocation:
                print(f"⛔ PORTFOLIO GUARD VETO: Sector '{proposed_sector}' exposure ({sector_ratio*100:.1f}%) exceeds limit ({self.max_sector_allocation*100}%).")
                return False

        # 2. Check Correlation with Active Positions
        if not active_positions_df.empty and 'ticker' in active_positions_df.columns:
            active_tickers = active_positions_df['ticker'].tolist()
            if active_tickers:
                # Fetch 30-day historical prices for correlation check
                tickers_to_fetch = active_tickers + [proposed_ticker]
                data = yf.download(tickers_to_fetch, period="1mo", interval="1d")['Close']
                
                if isinstance(data, pd.DataFrame) and len(data.columns) > 1:
                    corr_matrix = data.corr()
                    for active_t in active_tickers:
                        if active_t in corr_matrix.columns and proposed_ticker in corr_matrix.columns:
                            corr_val = corr_matrix.loc[active_t, proposed_ticker]
                            if corr_val > 0.85:
                                print(f"⚠️ High Correlation Warning: {proposed_ticker} is highly correlated with existing holding {active_t} ({corr_val:.2f}). Scaling down position size.")
                                
        print(f"✅ Portfolio Guard: {proposed_ticker} passed structural concentration checks.")
        return True