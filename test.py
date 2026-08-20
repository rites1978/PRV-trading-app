import os
import requests
from dotenv import load_dotenv

# 1. Load keys
load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

# 2. Connect to the server
url = "https://demo.trading212.com/api/v0/equity/account/summary"

response = requests.get(
    url,
    auth=(API_KEY, API_SECRET)
)

# 3. Read the correct labels from Trading 212
if response.status_code == 200:
    print("\n✅ Connection Successful!")
    data = response.json()
    
    # We now ask for "availableToTrade" instead of "free"
    available_cash = data.get("cash", {}).get("availableToTrade", 0)
    total_value = data.get("totalValue", 0)
    currency = data.get("currency")
    
    print(f"Available Cash to Trade: {available_cash} {currency}")
    print(f"Total Portfolio Value: {total_value} {currency}")
    
    # Check the Kill Switch
    if total_value < 4500:
        print("⚠️ DANGER: Portfolio has dropped below £4,500! Halting all buys.")
    else:
        print("🟢 Safe to trade. Portfolio is above the 10% drawdown limit.")

else:
    print(f"\n❌ Connection Failed. Error code: {response.status_code}")