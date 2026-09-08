"""
🏛️ PRV CAPITAL | HISTORICAL RESEARCH DATA LOADER & CACHE
Downloads and caches point-in-time daily bars and fundamental metrics for UK & US universes.
Ensures zero runtime network delays during backtest runs.
"""
import os
import time
import json
import logging
from datetime import datetime
import pandas as pd
import yfinance as yf
from typing import Dict, Any, List, Optional, Tuple
from src.data.universe import INSTITUTIONAL_UNIVERSE

logger = logging.getLogger("data_loader")

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "historical_prices")
FUNDAMENTALS_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "fundamentals_cache.json")


def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def get_cached_bars(yf_ticker: str, start_date: str = "2009-01-01", end_date: str = "2026-09-01") -> pd.DataFrame:
    """Loads daily bars from local CSV cache or downloads from yfinance."""
    ensure_cache_dir()
    clean_sym = yf_ticker.replace("^", "_").replace(".", "_")
    file_path = os.path.join(CACHE_DIR, f"{clean_sym}.csv")
    
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            if not df.empty:
                return df
        except Exception:
            pass

    try:
        df = yf.download(yf_ticker, start=start_date, end=end_date, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            # Flatten multiindex columns from newer yfinance
            df.columns = [c[0] for c in df.columns]
        if not df.empty:
            df.to_csv(file_path)
            return df
    except Exception as e:
        logger.warning(f"Failed to fetch historical bars for {yf_ticker}: {e}")

    return pd.DataFrame()


def download_and_cache_all_universe_bars(
    universe: Optional[List[Dict[str, Any]]] = None,
    start_date: str = "2009-01-01",
    end_date: str = "2026-09-01",
    chunk_size: int = 25
) -> Dict[str, pd.DataFrame]:
    """Downloads all universe bars in chunks using yfinance batch download and caches locally."""
    ensure_cache_dir()
    items = universe or INSTITUTIONAL_UNIVERSE
    tickers = [item.get("yf_ticker") for item in items if item.get("yf_ticker")]
    
    # Also add benchmarks
    if "^FTSE" not in tickers:
        tickers.append("^FTSE")
    if "^GSPC" not in tickers:
        tickers.append("^GSPC")

    # Check which tickers need downloading
    needed = []
    bars_map = {}
    for t in tickers:
        clean_sym = t.replace("^", "_").replace(".", "_")
        file_path = os.path.join(CACHE_DIR, f"{clean_sym}.csv")
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, index_col=0, parse_dates=True)
                if not df.empty and len(df) > 100:
                    bars_map[t] = df
                    continue
            except Exception:
                pass
        needed.append(t)

    if needed:
        logger.info(f"Downloading historical bars for {len(needed)} tickers in chunks of {chunk_size}...")
        for i in range(0, len(needed), chunk_size):
            chunk = needed[i:i + chunk_size]
            try:
                multi_df = yf.download(chunk, start=start_date, end=end_date, progress=False)
                if not multi_df.empty:
                    for t in chunk:
                        clean_sym = t.replace("^", "_").replace(".", "_")
                        file_path = os.path.join(CACHE_DIR, f"{clean_sym}.csv")
                        try:
                            if len(chunk) == 1:
                                sub_df = multi_df.copy()
                                if isinstance(sub_df.columns, pd.MultiIndex):
                                    sub_df.columns = [c[0] for c in sub_df.columns]
                            else:
                                sub_cols = {}
                                for col in ["Close", "High", "Low", "Open", "Volume"]:
                                    if col in multi_df.columns and t in multi_df[col]:
                                        sub_cols[col] = multi_df[col][t]
                                sub_df = pd.DataFrame(sub_cols).dropna()

                            if not sub_df.empty:
                                sub_df.to_csv(file_path)
                                bars_map[t] = sub_df
                        except Exception as ex:
                            logger.warning(f"Error extracting {t}: {ex}")
            except Exception as e:
                logger.warning(f"Error downloading chunk {chunk}: {e}")

    return bars_map


def get_all_universe_bars(universe: Optional[List[Dict[str, Any]]] = None) -> Dict[str, pd.DataFrame]:
    """Pre-loads daily bars for all universe assets from local cache, downloading if needed."""
    return download_and_cache_all_universe_bars(universe)


def load_fundamentals_cache() -> Dict[str, Dict[str, Any]]:
    """Loads cached fundamental quality & value metrics for universe assets."""
    if os.path.exists(FUNDAMENTALS_CACHE_PATH):
        try:
            with open(FUNDAMENTALS_CACHE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_fundamentals_cache(data: Dict[str, Dict[str, Any]]):
    ensure_cache_dir()
    with open(FUNDAMENTALS_CACHE_PATH, "w") as f:
        json.dump(data, f, indent=2)


def fetch_and_cache_fundamentals(universe: Optional[List[Dict[str, Any]]] = None, force: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Fetches fundamental financial metrics for Strategy B & C ranking:
    Quality:
      - operating_margin
      - return_on_capital (ROIC / ROCE approximation via EBIT / tangible operating assets or ROE/ROA)
      - free_cash_flow_quality (FCF / Operating Cash Flow or FCF / Net Income)
      - debt_to_equity / debt_to_ebitda
    Value:
      - earnings_yield (EBIT / EV or 1 / Forward PE)
      - fcf_yield (FCF / Market Cap)
      - ev_to_ebitda
    """
    cached = load_fundamentals_cache()
    if cached and not force and len(cached) >= 70:
        return cached

    items = universe or INSTITUTIONAL_UNIVERSE
    result = dict(cached)
    needed = [item for item in items if force or item.get("yf_ticker") not in result]

    logger.info(f"Fetching fundamentals for {len(needed)} assets...")
    count = 0
    for item in needed:
        yf_tick = item.get("yf_ticker", "")
        if not yf_tick:
            continue
        try:
            t = yf.Ticker(yf_tick)
            info = t.info or {}

            op_margin = float(info.get("operatingMargins", 0.0) or 0.0)
            roe = float(info.get("returnOnEquity", 0.0) or 0.0)
            roa = float(info.get("returnOnAssets", 0.0) or 0.0)
            debt_equity = float(info.get("debtToEquity", 0.0) or 0.0)
            fcf = float(info.get("freeCashflow", 0.0) or 0.0)
            ocf = float(info.get("operatingCashflow", 0.0) or 0.0)
            ebitda = float(info.get("ebitda", 0.0) or 0.0)
            ev = float(info.get("enterpriseValue", 0.0) or 0.0)
            mkt_cap = float(info.get("marketCap", 0.0) or 1.0)
            trailing_pe = float(info.get("trailingPE", 0.0) or 0.0)
            forward_pe = float(info.get("forwardPE", 0.0) or 0.0)

            fcf_quality = (fcf / max(1.0, ocf)) if ocf > 0 else 0.0
            roc = max(roe, roa * 2.0)

            fcf_yield = (fcf / max(1.0, mkt_cap)) if mkt_cap > 0 else 0.0
            earnings_yield = (1.0 / forward_pe) if forward_pe > 0 else ((1.0 / trailing_pe) if trailing_pe > 0 else 0.0)
            ev_ebitda = (ev / max(1.0, ebitda)) if ebitda > 0 and ev > 0 else 0.0

            result[yf_tick] = {
                "symbol": item.get("symbol"),
                "country": item.get("country"),
                "sector": item.get("sector"),
                "operating_margin": op_margin,
                "roc": roc,
                "fcf_quality": fcf_quality,
                "debt_to_equity": debt_equity,
                "earnings_yield": earnings_yield,
                "fcf_yield": fcf_yield,
                "ev_ebitda": ev_ebitda,
                "forward_pe": forward_pe,
                "trailing_pe": trailing_pe,
                "updated_at": datetime.now().isoformat()
            }
            count += 1
            if count % 10 == 0:
                save_fundamentals_cache(result)
            time.sleep(0.05)
        except Exception as e:
            logger.warning(f"Error fetching fundamentals for {yf_tick}: {e}")

    save_fundamentals_cache(result)
    return result
