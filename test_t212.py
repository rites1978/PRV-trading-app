import os
import requests
import base64

api_key = os.getenv("T212_API_KEY", "YOUR_KEY_HERE")
api_secret = os.getenv("T212_API_SECRET", "YOUR_SECRET_HERE")
base_url = "https://demo.trading212.com/api/v0/equity"

credentials_string = f"{api_key}:{api_secret}"
encoded_creds = base64.b64encode(credentials_string.encode('utf-8')).decode('utf-8')

headers = {
    "Authorization": f"Basic {encoded_creds}",
    "Content-Type": "application/json"
}

print("Testing connection to Trading 212 Demo API...")
try:
    res = requests.get(f"{base_url}/account/cash", headers=headers, timeout=10)
    print(f"Status Code: {res.status_code}")
    print(f"Response Body: {res.text}")
except Exception as e:
    print(f"Connection failed: {e}")
