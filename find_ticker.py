import os
import requests
from dotenv import load_dotenv

# 1. Load your keys
load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

# 2. Ask for the master list of all instruments
url = "https://demo.trading212.com/api/v0/equity/metadata/instruments"

print("Downloading master instrument list from Trading 212...")
response = requests.get(url, auth=(API_KEY, API_SECRET))

# 3. Search the list for Barclays
if response.status_code == 200:
    instruments = response.json()
    print("\n✅ Master List Downloaded! Searching for Barclays...\n")
    
    for item in instruments:
        # We make the name lowercase just in case they spell it in ALL CAPS
        company_name = item.get("name", "").lower()
        
        if "barclays" in company_name:
            print(f"Company: {item.get('name')}")
            print(f"Trading 212 Ticker: {item.get('ticker')}")
            print(f"Currency: {item.get('currency')}")
            print("-" * 20)
else:
    print(f"\n❌ Failed to download list. Error: {response.status_code}")