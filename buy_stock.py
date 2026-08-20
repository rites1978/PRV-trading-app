import os
import requests
from dotenv import load_dotenv

# 1. Securely load your keys
load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

# 2. Set up the connection for a Market Order
url = "https://demo.trading212.com/api/v0/equity/orders/market"

# 3. Create the instructions using the correct ticker
order_instructions = {
    "ticker": "BARCl_EQ",
    "quantity": 1
}

print("Attempting to buy 1 share of Barclays...")

# 4. Send the order
response = requests.post(
    url,
    auth=(API_KEY, API_SECRET),
    json=order_instructions
)

# 5. Check the result
if response.status_code == 200:
    data = response.json()
    print("\n✅ Order Accepted by Broker!")
    print(f"Order ID: {data.get('id')}")
    print(f"Status: {data.get('status')}")
else:
    print(f"\n❌ Order Failed. Error code: {response.status_code}")
    print("Reason:", response.text)