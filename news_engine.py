import requests
import os

class NewsEngine:
    def __init__(self):
        # Using a reliable free news source or placeholder logic
        # You can get a free API key from NewsAPI.org
        self.api_key = os.getenv("NEWS_API_KEY")

    def get_ticker_sentiment(self, ticker):
        """
        Fetches headlines and determines sentiment score (-1.0 to +1.0)
        """
        print(f"📰 News Engine: Fetching sentiment for {ticker}...")
        # Placeholder logic: In production, this calls NewsAPI and pipes to an LLM
        # For now, we simulate the logic flow for the Boardroom.
        return {"score": 0.5, "headline": f"Positive market momentum for {ticker} reported."}

    def is_trade_safe(self, ticker):
        sentiment = self.get_ticker_sentiment(ticker)
        # Veto if sentiment score is significantly negative
        if sentiment['score'] < -0.3:
            return False, sentiment['headline']
        return True, sentiment['headline']