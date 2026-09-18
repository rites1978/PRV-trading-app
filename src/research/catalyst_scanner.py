import os
import re
import time
import logging
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("prv.catalyst_scanner")

# Curated mapping of high-impact companies, government backing, and political catalysts to Trading212 Practice instruments
KNOWN_CATALYSTS: Dict[str, Dict[str, Any]] = {
    "DWAC": {
        "ticker": "DWAC_US_EQ",
        "symbol": "DJT",
        "feed": "DJT",
        "name": "Trump Media & Technology Group",
        "market": "US",
        "keywords": ["trump media", "truth social", "djt", "dwac", "trump family media"],
        "category": "TRUMP_DIRECT_BUSINESS",
        "default_bias": 0.40
    },
    "TSLA": {
        "ticker": "TSLA_US_EQ",
        "symbol": "TSLA",
        "feed": "TSLA",
        "name": "Tesla / Elon Musk",
        "market": "US",
        "keywords": ["tesla", "elon musk", "musk backing", "trump musk", "doge efficiency"],
        "category": "EXECUTIVE_BACKING",
        "default_bias": 0.35
    },
    "PLTR": {
        "ticker": "PLTR_US_EQ",
        "symbol": "PLTR",
        "feed": "PLTR",
        "name": "Palantir Technologies",
        "market": "US",
        "keywords": ["palantir", "defense ai", "government contract", "karp defense", "pentagon ai"],
        "category": "DEFENSE_AI_CONTRACTS",
        "default_bias": 0.35
    },
    "BA": {
        "ticker": "BA_US_EQ",
        "symbol": "BA",
        "feed": "BA",
        "name": "Boeing",
        "market": "US",
        "keywords": ["boeing contract", "air force contract", "trump boeing", "navy contract boeing"],
        "category": "DEFENSE_AEROSPACE",
        "default_bias": 0.30
    },
    "BA_UK": {
        "ticker": "BAl_EQ",
        "symbol": "BA.L",
        "feed": "BA.L",
        "name": "BAE Systems",
        "market": "UK",
        "keywords": ["bae systems", "uk defense budget", "nato defense spending", "defense backing"],
        "category": "DEFENSE_AEROSPACE",
        "default_bias": 0.30
    },
    "MSTR": {
        "ticker": "MSTR_US_EQ",
        "symbol": "MSTR",
        "feed": "MSTR",
        "name": "MicroStrategy",
        "market": "US",
        "keywords": ["microstrategy", "saylor", "bitcoin strategic reserve", "crypto backing", "trump crypto"],
        "category": "STRATEGIC_CRYPTO_BACKING",
        "default_bias": 0.35
    },
    "COIN": {
        "ticker": "COIN_US_EQ",
        "symbol": "COIN",
        "feed": "COIN",
        "name": "Coinbase Global",
        "market": "US",
        "keywords": ["coinbase", "crypto regulation", "sec crypto reform", "trump crypto policy"],
        "category": "STRATEGIC_CRYPTO_BACKING",
        "default_bias": 0.30
    },
    "LMT": {
        "ticker": "LMT_US_EQ",
        "symbol": "LMT",
        "feed": "LMT",
        "name": "Lockheed Martin",
        "market": "US",
        "keywords": ["lockheed", "f-35 contract", "missile defense", "pentagon award lockheed"],
        "category": "DEFENSE_AEROSPACE",
        "default_bias": 0.30
    },
    "XOM": {
        "ticker": "XOM_US_EQ",
        "symbol": "XOM",
        "feed": "XOM",
        "name": "ExxonMobil",
        "market": "US",
        "keywords": ["exxon", "oil deregulation", "drill baby drill", "lng export approval", "energy policy"],
        "category": "DOMESTIC_ENERGY",
        "default_bias": 0.30
    },
    "CVX": {
        "ticker": "CVX_US_EQ",
        "symbol": "CVX",
        "feed": "CVX",
        "name": "Chevron",
        "market": "US",
        "keywords": ["chevron", "oil deal", "venezuela oil", "hamm oil deal", "domestic drilling"],
        "category": "DOMESTIC_ENERGY",
        "default_bias": 0.30
    },
    "STLD": {
        "ticker": "STLD_US_EQ",
        "symbol": "STLD",
        "feed": "STLD",
        "name": "Steel Dynamics",
        "market": "US",
        "keywords": ["steel tariffs", "us steel manufacturing", "domestic steel", "trump steel"],
        "category": "MANUFACTURING_TARIFF_SHIELD",
        "default_bias": 0.30
    },
    "CNA": {
        "ticker": "CNAl_EQ",
        "symbol": "CNA.L",
        "feed": "CNA.L",
        "name": "Centrica",
        "market": "UK",
        "keywords": ["centrica", "uk energy security", "british gas profits", "energy dividend"],
        "category": "ENERGY_UTILITY",
        "default_bias": 0.25
    }
}


class CatalystScanner:
    """
    Scans live financial feeds, Google News, and market sources specifically for:
    1. Trump statements / Truth Social / Executive business endorsements & deals
    2. Federal / defense contracts & regulatory exemptions (tariffs, energy drilling, crypto reserve)
    3. High-impact breaking news catalysts for securities outside and inside the top 1000 universe.
    """

    def __init__(self):
        self._cached_catalysts: List[Dict[str, Any]] = []
        self._cache_timestamp: float = 0.0
        self._cache_ttl_seconds: float = 90.0  # 90 second cache to stay fresh without rate limits

    def scan_rss_for_catalysts(self) -> List[Dict[str, Any]]:
        """Fetch and parse live RSS feeds for Trump and executive business backing."""
        queries = [
            'Trump (stocks OR shares OR company) (backs OR endorses OR contract OR deregulation OR deal)',
            '("Truth Social" OR "Trump Media" OR "Elon Musk" OR "Palantir") (stock OR shares OR deal)',
            '("defense contract" OR "pentagon award" OR "tariff exemption") (stocks OR shares)'
        ]

        found_catalysts = []
        seen_tickers = set()

        for q in queries:
            try:
                rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-US&gl=US&ceid=US:en"
                resp = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=4)
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:15]:
                    title_node = item.find("title")
                    pub_node = item.find("pubDate")
                    if title_node is None or not title_node.text:
                        continue

                    headline = title_node.text.strip()
                    hl_lower = headline.lower()

                    # Match against known political & business backing entities
                    for key, cat_info in KNOWN_CATALYSTS.items():
                        inst_ticker = cat_info["ticker"]
                        if inst_ticker in seen_tickers:
                            continue

                        # Check if any keyword appears in headline
                        matched = any(kw in hl_lower for kw in cat_info["keywords"])
                        if matched:
                            seen_tickers.add(inst_ticker)
                            source = "Live Financial Feed"
                            clean_hl = headline
                            if " - " in headline:
                                parts = headline.rsplit(" - ", 1)
                                clean_hl = parts[0]
                                source = parts[1]

                            # Calculate elevated conviction for direct political/executive backing
                            is_trump_direct = "trump" in hl_lower or "truth social" in hl_lower or "backs" in hl_lower
                            conviction = 92 if is_trump_direct else 84

                            found_catalysts.append({
                                "ticker": inst_ticker,
                                "symbol": cat_info["symbol"],
                                "feed": cat_info["feed"],
                                "name": cat_info["name"],
                                "market": cat_info["market"],
                                "category": cat_info["category"],
                                "headline": clean_hl,
                                "source": source,
                                "sentiment_score": 0.45 if is_trump_direct else 0.30,
                                "sentiment_label": "STRONG_BULLISH",
                                "conviction_score": conviction,
                                "catalyst_tag": "TRUMP BACKING ⚡" if is_trump_direct else "POLICY CATALYST 🚀",
                                "rationale": f"High-impact catalyst: {clean_hl} [{source}]. Target authorized for immediate practice execution.",
                                "action": "BUY",
                                "badge_color": "gold" if is_trump_direct else "cyan",
                                "pub_date": pub_node.text if pub_node is not None else "",
                                "detected_at": datetime.now(timezone.utc).isoformat()
                            })
            except Exception as e:
                logger.warning(f"Error scanning RSS query '{q}': {e}")

        # Ensure core political beneficiaries are always represented if RSS is quiet
        fallback_keys = ["DWAC", "TSLA", "PLTR", "BA_UK", "MSTR"]
        for fk in fallback_keys:
            cat_info = KNOWN_CATALYSTS[fk]
            inst_ticker = cat_info["ticker"]
            if inst_ticker not in seen_tickers and len(found_catalysts) < 6:
                seen_tickers.add(inst_ticker)
                found_catalysts.append({
                    "ticker": inst_ticker,
                    "symbol": cat_info["symbol"],
                    "feed": cat_info["feed"],
                    "name": cat_info["name"],
                    "market": cat_info["market"],
                    "category": cat_info["category"],
                    "headline": f"Institutional monitoring: {cat_info['name']} policy momentum and executive backing",
                    "source": "AI Catalyst Radar",
                    "sentiment_score": cat_info["default_bias"],
                    "sentiment_label": "BULLISH",
                    "conviction_score": 88,
                    "catalyst_tag": "TRUMP / POLICY BACKING ⚡",
                    "rationale": f"Policy & executive backing candidate ({cat_info['category']}). Monitoring for rapid entry.",
                    "action": "BUY",
                    "badge_color": "gold",
                    "detected_at": datetime.now(timezone.utc).isoformat()
                })

        return found_catalysts

    def get_active_catalysts(self) -> List[Dict[str, Any]]:
        """Returns cached or fresh active catalysts."""
        now = time.time()
        if self._cached_catalysts and (now - self._cache_timestamp) < self._cache_ttl_seconds:
            return self._cached_catalysts

        try:
            catalysts = self.scan_rss_for_catalysts()
            if catalysts:
                self._cached_catalysts = catalysts
                self._cache_timestamp = now
        except Exception as e:
            logger.error(f"Failed to refresh active catalysts: {e}")

        return self._cached_catalysts or []

    def get_catalyst_tickers(self) -> List[str]:
        """Returns list of active catalyst instrument tickers."""
        catalysts = self.get_active_catalysts()
        return [c["ticker"] for c in catalysts]


catalyst_scanner = CatalystScanner()
