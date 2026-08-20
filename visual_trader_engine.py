import os
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

print("⚡ PRV Visual High-Growth Trading Desk Initialized (GBP Mode)...")
print("Targeting High-Growth Tech & AI Sectors | Starting Allocation: £1,000 Sandbox\n")

UNIVERSE = {
    "NVDA": "NVDA_US_EQ",
    "MSFT": "MSFT_US_EQ",
    "TSLA": "TSLA_US_EQ",
    "PLTR": "PLTR_US_EQ",
    "AMD": "AMD_US_EQ"
}

def log_to_journal(log_entry):
    filename = "visual_trading_journal.txt"
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
    with open(filename, "a") as f:
        f.write(timestamp + log_entry + "\n")

def print_trade_receipt(action, ticker, price, shares, total_cost, reason):
    """Prints a visual, professional trade receipt to the terminal."""
    border = "=================================================="
    print(f"\n{border}")
    print(f"🧾 AI TRADING DESK EXECUTION RECEIPT")
    print(f"{border}")
    print(f"• ACTION TYPE  : {action.upper()}" )
    print(f"• ASSET TEE    : {ticker}")
    print(f"• EXEC. PRICE  : ${price:.2f} USD")
    print(f"• QUANTITY     : {shares} Share(s)")
    print(f"• EST. VALUE   : ${total_cost:.2f} USD")
    print(f"• RATIONALE    : {reason}")
    print(f"{border}\n")
    
    log_to_journal(f"RECEIPT [{action.upper()}] {ticker} @ ${price:.2f} | Reason: {reason}")

def run_visual_trading_cycle():
    print(f"\n--------------------------------------------------")
    print(f"🔄 Market Scan Cycle Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"--------------------------------------------------")
    
    opportunities = []
    
    for yf_ticker, t212_ticker in UNIVERSE.items():
        try:
            stock = yf.Ticker(yf_ticker)
            history = stock.history(period="5d", interval="1h")
            
            if not history.empty and len(history) > 10:
                current_price = history['Close'].iloc[-1]
                sma_short = history['Close'].tail(5).mean()
                sma_long = history['Close'].mean()
                
                volume_avg = history['Volume'].mean()
                current_volume = history['Volume'].iloc[-1]
                is_high_volume = current_volume > volume_avg
                
                dip_percentage = (sma_long - current_price) / sma_long
                is_bullish = sma_short > sma_long
                
                print(f"[{yf_ticker}] Price: ${current_price:.2f} | Dip: {dip_percentage*100:.2f}% | Bullish: {is_bullish} | Vol Spike: {is_high_volume}")
                
                # High-growth strategy trigger: Valid structural dip + volume confirmation
                if dip_percentage >= 0.002 and is_high_volume:
                    score = dip_percentage * 100
                    opportunities.append({
                        "yf_ticker": yf_ticker,
                        "t212_ticker": t212_ticker,
                        "price": current_price,
                        "score": score,
                        "reason": f"Caught a {dip_percentage*100:.2f}% technical dip with active volume spike during high-growth momentum scan."
                    })
        except Exception as e:
            print(f"⚠️ Feed warning on {yf_ticker}: {e}")

    if opportunities:
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        top_pick = opportunities[0]
        
        # Execute via Trading 212 API
        order_url = "https://demo.trading212.com/api/v0/equity/orders/market"
        payload = {"ticker": top_pick['t212_ticker'], "quantity": 1}
        
        response = requests.post(order_url, auth=(API_KEY, API_SECRET), json=payload)
        
        if response.status_code == 200:
            print_trade_receipt(
                action="BUY (AUTOMATED)",
                ticker=top_pick['yf_ticker'],
                price=top_pick['price'],
                shares=1,
                total_cost=top_pick['price'],
                reason=top_pick['reason']
            )
        else:
            print(f"❌ Execution Rejected by Broker: {response.text}")
    else:
        print("💤 Market is balanced. AI Portfolio Manager is holding cash, waiting for high-conviction entry points.\n")

if __name__ == "__main__":
    try:
        while True:
            run_visual_trading_cycle()
            # Scan every 5 minutes for rapid visual demonstration
            time.sleep(300)
    except KeyboardInterrupt:
        print("\n🛑 Visual Trading Desk shut down safely.")