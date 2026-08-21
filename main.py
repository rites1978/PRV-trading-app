from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
import os
import requests
from requests.auth import HTTPBasicAuth
from contextlib import asynccontextmanager

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Initializing hardcoded secure connection..."

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 60: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"
    print(f"[{level.upper()}] {timestamp} - {message}")

# Hardcoded base URL to prevent any Render env var markdown corruption
T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def test_t212_connection():
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("T212 Error: Missing T212_API_KEY or T212_API_SECRET in Render settings.", "error")
        return
    
    auth = HTTPBasicAuth(T212_API_KEY, T212_API_SECRET)
    headers = {"Content-Type": "application/json"}
    
    url = f"{T212_BASE_URL}/account/info"
    log_activity(f"Testing GET request to {url}", "info")
    
    try:
        res = requests.get(url, auth=auth, headers=headers, timeout=10)
        log_activity(f"T212 Response [{res.status_code}]: {res.text}", "success" if res.status_code == 200 else "error")
        
        if res.status_code == 200:
            log_activity("🎉 AUTHENTICATION SUCCESSFUL! Connected to Trading 212 Demo.", "success")
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
