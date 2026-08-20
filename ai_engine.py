import yfinance as yf
import pandas as pd
import time
from datetime import datetime
import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

print("🧠 PRV Enterprise Quantitative Engine (Autonomous Buy/Sell) is LIVE...\n")

US_UNIVERSE = {
    "NVDA": "NVDA_US_EQ", "AMD": "AMD_US_EQ", "INTC": "INTC_US_EQ", 
    "AVGO": "AVGO_US_EQ", "TSM": "TSM_US_EQ", "MSFT": "MSFT_US_EQ", 
    "AAPL": "AAPL_US_EQ", "GOOGL": "GOOGL_US_EQ", "AMZN": "AMZN_US_EQ", 
    "META": "META_US_EQ", "PLTR": "PLTR_US_EQ", "TSLA": "TSLA_US_EQ", 
    "ENPH": "ENPH_US_EQ", "QS": "QS_US_EQ"
}

def manage_risk_and_scan():
    print(f"--- Market Cycle Started at {datetime.now().strftime('%H:%M:%S')} ---")
    
    # 1. RISK MANAGEMENT: Check existing open positions for Stop-Loss or Take-Profit
    portfolio_url = "https://demo.trading212.com/api/v0/equity/portfolio"
    portfolio_response = requests.get(portfolio_url, auth=(API_KEY, API_SECRET))
    
    if portfolio_response.status_code == 200:
        positions = portfolio_response.json()
        for pos in positions:
            ticker = pos.get("ticker")
            quantity = pos.get("quantity")
            avg_price = pos.get("averagePrice")
            current_price = pos.get("currentPrice")
            
            # Calculate return percentage
            return_pct = ((current_price - avg_price) / avg_price) * 100
            print(f"[Position Check] {ticker} | Return: {return_pct:.2f}%")
            
            # Risk Rule: Take profit at +1.5% OR Stop loss at -1.0%
            if return_pct >= 1.5 or return_pct <= -1.0:
                print(f"🚨 EXIT TRIGGERED for {ticker}! Return reached {return_pct:.2f}%. Selling position...")
                
                order_url = "https://demo.trading212.com/api/v0/equity/orders/market"
                # Negative quantity tells Trading 212 API to sell the asset
                sell_instructions = {
                    "ticker": ticker,
                    "quantity": -quantity 
                }
                sell_res = requests.post(order_url, auth=(API_KEY, API_SECRET), json=sell_instructions)
                if sell_res.status_code == 200:
                    print(f"✅ Successfully closed {ticker} position to lock in returns.\n")
                else:
                    print(f"❌ Failed to close position: {sell_res.text}\n")

    # 2. OPPORTUNITY SCANNING: Look for new high-conviction setups with volume filters
    opportunities = []
    for yf_ticker, t212_ticker in US_UNIVERSE.items():
        try:
            stock = yf.Ticker(yf_ticker)
            history = stock.history(period="5d", interval="1h")
            
            if not history.empty and len(history) > 15:
                current_price = history['Close'].iloc[-1]
                sma_short = history['Close'].tail(5).mean()
                sma_long = history['Close'].mean()
                
                # Volume filter: Ensure current volume exceeds the recent average
                volume_avg = history['Volume'].mean()
                current_volume = history['Volume'].iloc[-1]
                is_high_volume = current_volume > volume_avg
                
                dip_percentage = (sma_long - current_price) / sma_long
                is_bullish = sma_short > sma_long
                
                # Strict Institutional Rules: Dip + Uptrend + Volume Spike
                if dip_percentage >= 0.003 and is_bullish and is_high_volume:
                    score = dip_percentage * 100
                    opportunities.append({
                        "yf_ticker": yf_ticker, "t212_ticker": t212_ticker,
                        "price": current_price, "score": score
                    })
        except Exception:
            pass

    # Execute trade on the top-scored opportunity if no active emergency exits happened
    if opportunities:
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        top_pick = opportunities[0]
        
        print(f"🎯 NEW ENTRY FOUND: {top_pick['yf_ticker']} | Price: ${top_pick['price']:.2f} | Score: {top_pick['score']:.2f}")
        
        order_url = "https://demo.trading212.com/api/v0/equity/orders/market"
        order_instructions = {"ticker": top_pick['t212_ticker'], "quantity": 1}
        
        response = requests.post(order_url, auth=(API_KEY, API_SECURE := API_SECRET), json=order_instructions)
        if response.status_code == 200:
            print(f"✅ Autonomous Buy Order Placed Successfully!\n")
        else:
            print(f"❌ Execution Rejected: {response.text}\n")
    else:
        print("💤 Market sweep complete. No optimal entries matching strict volume/trend rules.\n")

if __name__ == "__main__":
    try:
        while True:
            manage_risk_and_scan()
            time.sleep(600) # Loop every 10 minutes
    except KeyboardInterrupt:
        print("\n🛑 PRV Enterprise Engine shut down safely.")