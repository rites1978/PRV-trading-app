from typing import List, Dict, Any

# Production Universe: Top UK Blue Chips & Top US Liquid Equities
INSTITUTIONAL_UNIVERSE: List[Dict[str, Any]] = [
    # --- Top UK Blue Chips (FTSE Leaders) ---
    {"symbol": "BARC", "name": "Barclays PLC", "yf_ticker": "BARC.L", "t212_ticker": "BARCl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "LLOY", "name": "Lloyds Banking Group", "yf_ticker": "LLOY.L", "t212_ticker": "LLOYl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "BP", "name": "BP plc", "yf_ticker": "BP.L", "t212_ticker": "BPl_EQ", "sector": "Energy", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "SHEL", "name": "Shell PLC", "yf_ticker": "SHEL.L", "t212_ticker": "SHELl_EQ", "sector": "Energy", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "AZN", "name": "AstraZeneca PLC", "yf_ticker": "AZN.L", "t212_ticker": "AZNl_EQ", "sector": "Healthcare", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "HSBA", "name": "HSBC Holdings PLC", "yf_ticker": "HSBA.L", "t212_ticker": "HSBAl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "ULVR", "name": "Unilever PLC", "yf_ticker": "ULVR.L", "t212_ticker": "ULVRl_EQ", "sector": "Consumer Defensive", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "GSK", "name": "GSK plc", "yf_ticker": "GSK.L", "t212_ticker": "GSKl_EQ", "sector": "Healthcare", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "RIO", "name": "Rio Tinto PLC", "yf_ticker": "RIO.L", "t212_ticker": "RIOl_EQ", "sector": "Basic Materials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "DGE", "name": "Diageo PLC", "yf_ticker": "DGE.L", "t212_ticker": "DGEl_EQ", "sector": "Consumer Defensive", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "REL", "name": "RELX PLC", "yf_ticker": "REL.L", "t212_ticker": "RELl_EQ", "sector": "Industrials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "BATS", "name": "British American Tobacco", "yf_ticker": "BATS.L", "t212_ticker": "BATSl_EQ", "sector": "Consumer Defensive", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "NG", "name": "National Grid PLC", "yf_ticker": "NG.L", "t212_ticker": "NGl_EQ", "sector": "Utilities", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "VOD", "name": "Vodafone Group PLC", "yf_ticker": "VOD.L", "t212_ticker": "VODl_EQ", "sector": "Communication", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "GLEN", "name": "Glencore PLC", "yf_ticker": "GLEN.L", "t212_ticker": "GLENl_EQ", "sector": "Basic Materials", "country": "UK", "currency": "GBP", "is_uk_pence": True},

    # --- Top US Mega-Cap & Liquid Equities (S&P 500 & Nasdaq 100 Leaders) ---
    {"symbol": "AAPL", "name": "Apple Inc", "yf_ticker": "AAPL", "t212_ticker": "AAPL_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MSFT", "name": "Microsoft Corp", "yf_ticker": "MSFT", "t212_ticker": "MSFT_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "NVDA", "name": "NVIDIA Corp", "yf_ticker": "NVDA", "t212_ticker": "NVDA_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "AMZN", "name": "Amazon.com Inc", "yf_ticker": "AMZN", "t212_ticker": "AMZN_US_EQ", "sector": "Consumer Cyclical", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "GOOGL", "name": "Alphabet Inc (Class A)", "yf_ticker": "GOOGL", "t212_ticker": "GOOGL_US_EQ", "sector": "Communication", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "META", "name": "Meta Platforms Inc", "yf_ticker": "META", "t212_ticker": "META_US_EQ", "sector": "Communication", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "TSLA", "name": "Tesla Inc", "yf_ticker": "TSLA", "t212_ticker": "TSLA_US_EQ", "sector": "Consumer Cyclical", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "BRK.B", "name": "Berkshire Hathaway Inc", "yf_ticker": "BRK-B", "t212_ticker": "BRKb_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co", "yf_ticker": "JPM", "t212_ticker": "JPM_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "V", "name": "Visa Inc", "yf_ticker": "V", "t212_ticker": "V_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc", "yf_ticker": "UNH", "t212_ticker": "UNH_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "XOM", "name": "Exxon Mobil Corp", "yf_ticker": "XOM", "t212_ticker": "XOM_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "yf_ticker": "JNJ", "t212_ticker": "JNJ_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PG", "name": "Procter & Gamble Co", "yf_ticker": "PG", "t212_ticker": "PG_US_EQ", "sector": "Consumer Defensive", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MA", "name": "Mastercard Inc", "yf_ticker": "MA", "t212_ticker": "MA_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "HD", "name": "Home Depot Inc", "yf_ticker": "HD", "t212_ticker": "HD_US_EQ", "sector": "Consumer Cyclical", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "ABBV", "name": "AbbVie Inc", "yf_ticker": "ABBV", "t212_ticker": "ABBV_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "CVX", "name": "Chevron Corp", "yf_ticker": "CVX", "t212_ticker": "CVX_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MRK", "name": "Merck & Co Inc", "yf_ticker": "MRK", "t212_ticker": "MRK_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "KO", "name": "Coca-Cola Co", "yf_ticker": "KO", "t212_ticker": "KO_US_EQ", "sector": "Consumer Defensive", "country": "US", "currency": "USD", "is_uk_pence": False}
]

class UniverseManager:
    def __init__(self):
        self.universe = INSTITUTIONAL_UNIVERSE

    def get_all(self) -> List[Dict[str, Any]]:
        return self.universe

    def get_by_t212_ticker(self, t212_ticker: str) -> Dict[str, Any]:
        return next((item for item in self.universe if item["t212_ticker"] == t212_ticker), None)

    def get_by_symbol(self, symbol: str) -> Dict[str, Any]:
        return next((item for item in self.universe if item["symbol"] == symbol), None)

    def filter_by_sector(self, sector: str) -> List[Dict[str, Any]]:
        return [item for item in self.universe if item["sector"].lower() == sector.lower()]

universe_manager = UniverseManager()
