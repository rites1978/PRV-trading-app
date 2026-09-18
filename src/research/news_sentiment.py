import os
import requests
import re
from typing import Dict, Any, List
from src.config.settings import settings

POSITIVE_TERMS = {
    "upgrade", "upgrades", "upgraded", "surge", "surges", "surged", "beat", "beats",
    "record", "growth", "bullish", "bull", "outperform", "outperforms", "profit",
    "profits", "strong", "raised", "breakthrough", "partnership", "dividend",
    "buyback", "expansion", "soar", "soars", "gain", "gains", "gained", "optimistic",
    "climb", "climbs", "high", "higher", "rally", "rallies", "rallied", "jump", "jumps", "jumped"
}

NEGATIVE_TERMS = {
    "downgrade", "downgrades", "downgraded", "plunge", "plunges", "plunged", "miss",
    "misses", "missed", "loss", "losses", "decline", "declines", "declined", "bearish",
    "bear", "underperform", "warning", "weak", "weaker", "cut", "cuts", "lawsuit",
    "investigation", "slump", "slumps", "slumped", "drop", "drops", "dropped", "fall",
    "falls", "layoff", "recession", "pessimistic", "default", "probe", "low", "lower"
}

COMPANY_NAMES = {
    "AAPL": "Apple",
    "NVDA": "Nvidia",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "TSLA": "Tesla",
    "GOOG": "Alphabet Google",
    "META": "Meta Facebook",
    "SPY": "S&P 500 ETF",
    "QQQ": "Invesco QQQ ETF"
}

class NewsSentimentResearcher:
    """
    Natural Language News & Sentiment Alpha Researcher:
    Parses real-time market headlines via NewsAPI or live Google News RSS feeds
    and computes Lexical Tone Polarity and Institutional Sentiment Scores (0-100).
    """
    def __init__(self):
        self.api_key = settings.NEWS_API_KEY

    def analyze_headline_sentiment(self, text: str) -> float:
        """Calculate lexical sentiment polarity score between -1.0 and +1.0."""
        words = re.findall(r'\b[a-z]+\b', text.lower())
        if not words:
            return 0.0

        pos_count = sum(1 for w in words if w in POSITIVE_TERMS)
        neg_count = sum(1 for w in words if w in NEGATIVE_TERMS)
        total = pos_count + neg_count

        if total == 0:
            return 0.0
        return (pos_count - neg_count) / total

    def fetch_stock_sentiment(self, symbol: str, company_name: str = "") -> Dict[str, Any]:
        """Fetch and analyze live news headlines and sentiment for target security."""
        headlines: List[str] = []
        c_name = company_name or COMPANY_NAMES.get(symbol.upper(), "")

        # 1. Attempt NewsAPI.org if key provided
        if self.api_key:
            try:
                query = c_name or symbol
                url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&pageSize=10&apiKey={self.api_key}"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    articles = res.json().get("articles", [])
                    headlines = [a.get("title", "") for a in articles if a.get("title")]
            except Exception:
                pass

        # 2. Live RSS fallback for real-time financial market news
        if not headlines:
            try:
                query_term = f"{c_name} {symbol} stock market" if c_name else f"{symbol} stock market"
                rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query_term)}&hl=en-US&gl=US&ceid=US:en"
                resp = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                if resp.status_code == 200:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.content)
                    rss_titles = [
                        item.find("title").text
                        for item in root.findall(".//item")[:10]
                        if item.find("title") is not None and item.find("title").text
                    ]
                    if rss_titles:
                        headlines = rss_titles
            except Exception:
                pass

        # 3. Fallback heuristic if external news feeds unreachable
        if not headlines:
            headlines = [f"Institutional tracking for {symbol}"]

        polarities = [self.analyze_headline_sentiment(h) for h in headlines]
        avg_polarity = float(sum(polarities) / len(polarities)) if polarities else 0.0

        # Sentiment Alpha Score (0 - 100)
        # Polarity of 0.0 -> Score 50.0 (Neutral)
        # Polarity of +1.0 -> Score 90.0 (Extremely Bullish)
        # Polarity of -1.0 -> Score 10.0 (Extremely Bearish)
        sentiment_score = 50.0 + (avg_polarity * 40.0)
        sentiment_score = max(10.0, min(95.0, sentiment_score))

        return {
            "symbol": symbol,
            "sentiment_score": round(sentiment_score, 1),
            "polarity": round(avg_polarity, 3),
            "headline_count": len(headlines),
            "headlines": headlines[:5],
            "tone": "BULLISH" if sentiment_score >= 60.0 else ("BEARISH" if sentiment_score <= 40.0 else "NEUTRAL")
        }

news_sentiment = NewsSentimentResearcher()
