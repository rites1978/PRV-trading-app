from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
from contextlib import asynccontextmanager

app = FastAPI()

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def get_t212_auth_headers():
    raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

@app.get("/api/diagnostic")
def run_diagnostic():
    headers = get_t212_auth_headers()
    results = []

    # Test 1: Verify Authentication & Account Read
    try:
        r1 = requests.get(f"{T212_BASE_URL}/account/info", headers=headers, timeout=10)
        results.append(f"--- TEST 1: AUTHENTICATION ---\nHTTP Status: {r1.status_code}\nResponse Body: {r1.text}")
    except Exception as e:
        results.append(f"--- TEST 1: ERROR ---\n{str(e)}")

    # Test 2: Verify Instrument Mapping (Does AAPL_US_EQ exist?)
    payload = {
        "ticker": "AAPL_US_EQ",
        "quantity": 1.0
    }
    
    # Test 3: The Exact Order Payload Rejection
    try:
        r3 = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=headers, timeout=10)
        results.append(f"--- TEST 2: MARKET ORDER EXECUTION ---\nPayload Sent: {payload}\nHTTP Status: {r3.status_code}\nResponse Body: {r3.text}")
    except Exception as e:
        results.append(f"--- TEST 2: ERROR ---\n{str(e)}")

    return {"diagnostic_log": "\n\n".join(results)}

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PRV Diagnostic Tool</title>
    <style>
        body { background: #0b0f19; color: #f3f4f6; font-family: monospace; padding: 40px; }
        .card { background: #111827; border: 1px solid #1f2937; padding: 24px; border-radius: 12px; }
        button { background: #ef4444; color: white; font-weight: bold; padding: 12px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; margin-bottom: 20px; }
        button:hover { background: #dc2626; }
        pre { background: #030712; padding: 20px; border: 1px solid #374151; border-radius: 8px; color: #34d399; white-space: pre-wrap; word-wrap: break-word; }
    </style>
</head>
<body>
    <div class="card">
        <h1 style="color: #ef4444; font-family: sans-serif;">PRV Hard Diagnostic Mode</h1>
        <p style="font-family: sans-serif;">Click the button below to force a raw API call and bypass all UI formatting. Copy the output exactly as it appears.</p>
        <button onclick="runDiag()">Run API Diagnostic</button>
        <pre id="output">Waiting for diagnostic run...</pre>
    </div>
    <script>
        async function runDiag() {
            document.getElementById('output').innerText = "Running API calls to Trading 212...";
            try {
                const res = await fetch('/api/diagnostic');
                const data = await res.json();
                document.getElementById('output').innerText = data.diagnostic_log;
            } catch(e) {
                document.getElementById('output').innerText = "Network failure: " + e;
            }
        }
    </script>
</body>
</html>
"""
