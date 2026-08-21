from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
from contextlib import asynccontextmanager

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Initializing verified Basic Auth engine..."

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 60: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"
    print(f"[{level.upper()}] {timestamp} - {message}")

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def test_t212_connection():
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("T212 Error: Missing T212_API_KEY or T212_API_SECRET in Render settings.", "error")
        return
    
    # Construct official Trading 212 Basic Auth header
    raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded_credentials = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/json"
    }
    
    url = f"{T212_BASE_URL}/account/info"
    log_activity(f"Testing authenticated connection to {url}", "info")
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        log_activity(f"T212 Response [{res.status_code}]: {res.text}", "success" if res.status_code == 200 else "error")
        
        if res.status_code == 200:
            log_activity("🎉 AUTHENTICATION SUCCESSFUL! Connected to Trading 212 Demo.", "success")
        elif res.status_code == 401:
            log_activity("⚠️ 401 UNAUTHORIZED: Please verify that your API Key and Secret were generated specifically inside 'demo.trading212.com' (Practice mode).", "warning")
    except Exception as e:
        log_activity(f"Exception: {str(e)}", "error")

async def market_scouring_agent():
    await asyncio.sleep(5)
    while True:
        test_t212_connection()
        await asyncio.sleep(300)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(market_scouring_agent())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/valuation", methods=["GET"])
def get_live_valuation():
    return {"commentary": LIVE_COMMENTARY}

@app.get("/", response_class=HTMLResponse)
def read_root():
    return f"<html><body style='background:#111;color:#fff;font-family:sans-serif;padding:40px;'><h1>T212 Auth Console</h1><pre>{LIVE_COMMENTARY}</pre></body></html>"
