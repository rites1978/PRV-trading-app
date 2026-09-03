from typing import List, Dict, Any

# Certified Production Universe: Top UK Blue Chips & Top US Liquid Equities (102 Assets)
INSTITUTIONAL_UNIVERSE: List[Dict[str, Any]] = [
    # --- Top UK Blue Chips (FTSE Leaders) ---
    {"symbol": "BARC", "name": "Barclays PLC", "yf_ticker": "BARC.L", "t212_ticker": "BARCl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "LLOY", "name": "Lloyds Banking Group", "yf_ticker": "LLOY.L", "t212_ticker": "LLOYl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "BP", "name": "BP plc", "yf_ticker": "BP.L", "t212_ticker": "BPl_EQ", "sector": "Energy", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "SHEL", "name": "Shell PLC", "yf_ticker": "SHEL.L", "t212_ticker": "SHELl_EQ", "sector": "Energy", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "AZN", "name": "AstraZeneca PLC", "yf_ticker": "AZN.L", "t212_ticker": "AZNl_EQ", "sector": "Healthcare", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "HSBA", "name": "HSBC Holdings PLC", "yf_ticker": "HSBA.L", "t212_ticker": "HSBAl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "ULVR", "name": "Unilever PLC", "yf_ticker": "ULVR.L", "t212_ticker": "ULVRl_EQ", "sector": "Consumer Staples", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "GSK", "name": "GSK plc", "yf_ticker": "GSK.L", "t212_ticker": "GSKl_EQ", "sector": "Healthcare", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "RIO", "name": "Rio Tinto PLC", "yf_ticker": "RIO.L", "t212_ticker": "RIOl_EQ", "sector": "Materials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "DGE", "name": "Diageo PLC", "yf_ticker": "DGE.L", "t212_ticker": "DGEl_EQ", "sector": "Consumer Staples", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "REL", "name": "RELX PLC", "yf_ticker": "REL.L", "t212_ticker": "RELl_EQ", "sector": "Industrials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "BATS", "name": "British American Tobacco", "yf_ticker": "BATS.L", "t212_ticker": "BATSl_EQ", "sector": "Consumer Staples", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "NG", "name": "National Grid PLC", "yf_ticker": "NG.L", "t212_ticker": "NGl_EQ", "sector": "Utilities", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "VOD", "name": "Vodafone Group PLC", "yf_ticker": "VOD.L", "t212_ticker": "VODl_EQ", "sector": "Communication", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "GLEN", "name": "Glencore PLC", "yf_ticker": "GLEN.L", "t212_ticker": "GLENl_EQ", "sector": "Materials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "LSEG", "name": "London Stock Exchange Group", "yf_ticker": "LSEG.L", "t212_ticker": "LSEGl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "PRU", "name": "Prudential PLC", "yf_ticker": "PRU.L", "t212_ticker": "PRUl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "AAL", "name": "Anglo American PLC", "yf_ticker": "AAL.L", "t212_ticker": "AALl_EQ", "sector": "Materials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "NWG", "name": "NatWest Group PLC", "yf_ticker": "NWG.L", "t212_ticker": "NWGl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "EXPN", "name": "Experian PLC", "yf_ticker": "EXPN.L", "t212_ticker": "EXPNl_EQ", "sector": "Industrials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "CPG", "name": "Compass Group PLC", "yf_ticker": "CPG.L", "t212_ticker": "CPGl_EQ", "sector": "Consumer Discretionary", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "STAN", "name": "Standard Chartered PLC", "yf_ticker": "STAN.L", "t212_ticker": "STANl_EQ", "sector": "Financials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "BA_UK", "name": "BAE Systems PLC", "yf_ticker": "BA.L", "t212_ticker": "BAl_EQ", "sector": "Industrials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "SSE", "name": "SSE PLC", "yf_ticker": "SSE.L", "t212_ticker": "SSEl_EQ", "sector": "Utilities", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "IMB", "name": "Imperial Brands PLC", "yf_ticker": "IMB.L", "t212_ticker": "IMBl_EQ", "sector": "Consumer Staples", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "FLTR", "name": "Flutter Entertainment PLC", "yf_ticker": "FLTR.L", "t212_ticker": "FLTRl_EQ", "sector": "Consumer Discretionary", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "RKT", "name": "Reckitt Benckiser Group", "yf_ticker": "RKT.L", "t212_ticker": "RKTl_EQ", "sector": "Consumer Staples", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "ANTO", "name": "Antofagasta PLC", "yf_ticker": "ANTO.L", "t212_ticker": "ANTOl_EQ", "sector": "Materials", "country": "UK", "currency": "GBP", "is_uk_pence": True},
    {"symbol": "WPP", "name": "WPP PLC", "yf_ticker": "WPP.L", "t212_ticker": "WPPl_EQ", "sector": "Communication", "country": "UK", "currency": "GBP", "is_uk_pence": True},

    # --- Top US Technology & Semiconductor Leaders ---
    {"symbol": "AAPL", "name": "Apple Inc", "yf_ticker": "AAPL", "t212_ticker": "AAPL_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MSFT", "name": "Microsoft Corp", "yf_ticker": "MSFT", "t212_ticker": "MSFT_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "NVDA", "name": "NVIDIA Corp", "yf_ticker": "NVDA", "t212_ticker": "NVDA_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "AVGO", "name": "Broadcom Inc", "yf_ticker": "AVGO", "t212_ticker": "AVGO_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "AMD", "name": "Advanced Micro Devices", "yf_ticker": "AMD", "t212_ticker": "AMD_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "CRM", "name": "Salesforce Inc", "yf_ticker": "CRM", "t212_ticker": "CRM_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "ADBE", "name": "Adobe Inc", "yf_ticker": "ADBE", "t212_ticker": "ADBE_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "CSCO", "name": "Cisco Systems Inc", "yf_ticker": "CSCO", "t212_ticker": "CSCO_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "INTC", "name": "Intel Corp", "yf_ticker": "INTC", "t212_ticker": "INTC_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "QCOM", "name": "Qualcomm Inc", "yf_ticker": "QCOM", "t212_ticker": "QCOM_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "TXN", "name": "Texas Instruments Inc", "yf_ticker": "TXN", "t212_ticker": "TXN_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "IBM", "name": "International Business Machines", "yf_ticker": "IBM", "t212_ticker": "IBM_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "NOW", "name": "ServiceNow Inc", "yf_ticker": "NOW", "t212_ticker": "NOW_US_EQ", "sector": "Technology", "country": "US", "currency": "USD", "is_uk_pence": False},

    # --- Top US Financials Leaders ---
    {"symbol": "JPM", "name": "JPMorgan Chase & Co", "yf_ticker": "JPM", "t212_ticker": "JPM_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "BAC", "name": "Bank of America Corp", "yf_ticker": "BAC", "t212_ticker": "BAC_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "WFC", "name": "Wells Fargo & Co", "yf_ticker": "WFC", "t212_ticker": "WFC_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "C", "name": "Citigroup Inc", "yf_ticker": "C", "t212_ticker": "C_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "GS", "name": "Goldman Sachs Group", "yf_ticker": "GS", "t212_ticker": "GS_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MS", "name": "Morgan Stanley", "yf_ticker": "MS", "t212_ticker": "MS_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "BLK", "name": "BlackRock Inc", "yf_ticker": "BLK", "t212_ticker": "BLK_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "AXP", "name": "American Express Co", "yf_ticker": "AXP", "t212_ticker": "AXP_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "V", "name": "Visa Inc", "yf_ticker": "V", "t212_ticker": "V_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MA", "name": "Mastercard Inc", "yf_ticker": "MA", "t212_ticker": "MA_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PNC", "name": "PNC Financial Services", "yf_ticker": "PNC", "t212_ticker": "PNC_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "USB", "name": "U.S. Bancorp", "yf_ticker": "USB", "t212_ticker": "USB_US_EQ", "sector": "Financials", "country": "US", "currency": "USD", "is_uk_pence": False},

    # --- Top US Healthcare Leaders ---
    {"symbol": "LLY", "name": "Eli Lilly and Co", "yf_ticker": "LLY", "t212_ticker": "LLY_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc", "yf_ticker": "UNH", "t212_ticker": "UNH_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "yf_ticker": "JNJ", "t212_ticker": "JNJ_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "ABBV", "name": "AbbVie Inc", "yf_ticker": "ABBV", "t212_ticker": "ABBV_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MRK", "name": "Merck & Co Inc", "yf_ticker": "MRK", "t212_ticker": "MRK_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "TMO", "name": "Thermo Fisher Scientific", "yf_ticker": "TMO", "t212_ticker": "TMO_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "ABT", "name": "Abbott Laboratories", "yf_ticker": "ABT", "t212_ticker": "ABT_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PFE", "name": "Pfizer Inc", "yf_ticker": "PFE", "t212_ticker": "PFE_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "DHR", "name": "Danaher Corp", "yf_ticker": "DHR", "t212_ticker": "DHR_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "BMY", "name": "Bristol-Myers Squibb", "yf_ticker": "BMY", "t212_ticker": "BMY_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "AMGN", "name": "Amgen Inc", "yf_ticker": "AMGN", "t212_ticker": "AMGN_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "GILD", "name": "Gilead Sciences Inc", "yf_ticker": "GILD", "t212_ticker": "GILD_US_EQ", "sector": "Healthcare", "country": "US", "currency": "USD", "is_uk_pence": False},

    # --- Top US Consumer & Retail Leaders ---
    {"symbol": "AMZN", "name": "Amazon.com Inc", "yf_ticker": "AMZN", "t212_ticker": "AMZN_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "TSLA", "name": "Tesla Inc", "yf_ticker": "TSLA", "t212_ticker": "TSLA_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "WMT", "name": "Walmart Inc", "yf_ticker": "WMT", "t212_ticker": "WMT_US_EQ", "sector": "Consumer Staples", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PG", "name": "Procter & Gamble Co", "yf_ticker": "PG", "t212_ticker": "PG_US_EQ", "sector": "Consumer Staples", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "COST", "name": "Costco Wholesale Corp", "yf_ticker": "COST", "t212_ticker": "COST_US_EQ", "sector": "Consumer Staples", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "HD", "name": "Home Depot Inc", "yf_ticker": "HD", "t212_ticker": "HD_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "KO", "name": "Coca-Cola Co", "yf_ticker": "KO", "t212_ticker": "KO_US_EQ", "sector": "Consumer Staples", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PEP", "name": "PepsiCo Inc", "yf_ticker": "PEP", "t212_ticker": "PEP_US_EQ", "sector": "Consumer Staples", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "MCD", "name": "McDonald's Corp", "yf_ticker": "MCD", "t212_ticker": "MCD_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "NKE", "name": "Nike Inc", "yf_ticker": "NKE", "t212_ticker": "NKE_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PM", "name": "Philip Morris International", "yf_ticker": "PM", "t212_ticker": "PM_US_EQ", "sector": "Consumer Staples", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "TGT", "name": "Target Corp", "yf_ticker": "TGT", "t212_ticker": "TGT_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "LOW", "name": "Lowe's Companies Inc", "yf_ticker": "LOW", "t212_ticker": "LOW_US_EQ", "sector": "Consumer Discretionary", "country": "US", "currency": "USD", "is_uk_pence": False},

    # --- Top US Energy & Industrials Leaders ---
    {"symbol": "XOM", "name": "Exxon Mobil Corp", "yf_ticker": "XOM", "t212_ticker": "XOM_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "CVX", "name": "Chevron Corp", "yf_ticker": "CVX", "t212_ticker": "CVX_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "COP", "name": "ConocoPhillips", "yf_ticker": "COP", "t212_ticker": "COP_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "SLB", "name": "Schlumberger NV", "yf_ticker": "SLB", "t212_ticker": "SLB_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "EOG", "name": "EOG Resources Inc", "yf_ticker": "EOG", "t212_ticker": "EOG_US_EQ", "sector": "Energy", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "CAT", "name": "Caterpillar Inc", "yf_ticker": "CAT", "t212_ticker": "CAT_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "UNP", "name": "Union Pacific Corp", "yf_ticker": "UNP", "t212_ticker": "UNP_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "GE", "name": "General Electric Co", "yf_ticker": "GE", "t212_ticker": "GE_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "HON", "name": "Honeywell International", "yf_ticker": "HON", "t212_ticker": "HON_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "DE", "name": "Deere & Co", "yf_ticker": "DE", "t212_ticker": "DE_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "LMT", "name": "Lockheed Martin Corp", "yf_ticker": "LMT", "t212_ticker": "LMT_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "RTX", "name": "RTX Corp", "yf_ticker": "RTX", "t212_ticker": "RTX_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "BA", "name": "Boeing Co", "yf_ticker": "BA", "t212_ticker": "BA_US_EQ", "sector": "Industrials", "country": "US", "currency": "USD", "is_uk_pence": False},

    # --- Top US Communication, Utilities, Materials, Real Estate ---
    {"symbol": "GOOGL", "name": "Alphabet Inc (Class A)", "yf_ticker": "GOOGL", "t212_ticker": "GOOGL_US_EQ", "sector": "Communication", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "META", "name": "Meta Platforms Inc", "yf_ticker": "META", "t212_ticker": "META_US_EQ", "sector": "Communication", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "NEE", "name": "NextEra Energy Inc", "yf_ticker": "NEE", "t212_ticker": "NEE_US_EQ", "sector": "Utilities", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "SO", "name": "Southern Co", "yf_ticker": "SO", "t212_ticker": "SO_US_EQ", "sector": "Utilities", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "DUK", "name": "Duke Energy Corp", "yf_ticker": "DUK", "t212_ticker": "DUK_US_EQ", "sector": "Utilities", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "LIN", "name": "Linde PLC", "yf_ticker": "LIN", "t212_ticker": "LIN_US_EQ", "sector": "Materials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "SHW", "name": "Sherwin-Williams Co", "yf_ticker": "SHW", "t212_ticker": "SHW_US_EQ", "sector": "Materials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "FCX", "name": "Freeport-McMoRan Inc", "yf_ticker": "FCX", "t212_ticker": "FCX_US_EQ", "sector": "Materials", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "PLD", "name": "Prologis Inc", "yf_ticker": "PLD", "t212_ticker": "PLD_US_EQ", "sector": "Real Estate", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "AMT", "name": "American Tower Corp", "yf_ticker": "AMT", "t212_ticker": "AMT_US_EQ", "sector": "Real Estate", "country": "US", "currency": "USD", "is_uk_pence": False},
    {"symbol": "CCI", "name": "Crown Castle Inc", "yf_ticker": "CCI", "t212_ticker": "CCI_US_EQ", "sector": "Real Estate", "country": "US", "currency": "USD", "is_uk_pence": False}
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

    def get_by_ticker(self, ticker: str) -> Dict[str, Any]:
        """Lookup by t212_ticker, symbol, or yf_ticker."""
        t = ticker.upper()
        return next((
            item for item in self.universe
            if item["t212_ticker"].upper() == t or item["symbol"].upper() == t or item.get("yf_ticker", "").upper() == t
        ), None)

    def filter_by_sector(self, sector: str) -> List[Dict[str, Any]]:
        return [item for item in self.universe if item["sector"].lower() == sector.lower()]

universe_manager = UniverseManager()
