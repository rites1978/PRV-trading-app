"""
PRV Capital Autonomous Quantitative Trading Engine
Unified Production FastAPI Application Entrypoint
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Load credentials from any environment variable standard
os.environ["TRADING212_API_KEY"] = os.getenv("TRADING212_API_KEY") or os.getenv("T212_API_KEY", "")
os.environ["TRADING212_API_SECRET"] = os.getenv("TRADING212_API_SECRET") or os.getenv("T212_API_SECRET", "")

# Single Unified Production Application Gateway
from src.api.routes import app

# Explicit export for Uvicorn
__all__ = ["app"]