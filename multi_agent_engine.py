import time
from datetime import datetime
from t212_config import calculate_net_alpha, TRADING_ENV
from market_screener import GlobalMarketScreener
from hedging_engine import HedgingEngine
from visual_trader_engine import VisualTraderEngine
from db_manager import db

class MultiAgentEngine:
    def __init__(self):
        print(f"🧠 Multi-Agent Engine Initialized [Environment: {TRADING_ENV.upper()}]")
        self.screener = GlobalMarketScreener()
        self.hedging_engine = HedgingEngine()
        self.trader = VisualTraderEngine()

    def run_technical_agent(self, ticker):
        """Simulates the Technical Analysis Agent."""
        print(f"📊 Technical Agent: Analyzing volume and price action for {ticker}...")
        # In a full build, this hooks into Polygon.io or TA-Lib
        return {"signal": "BUY", "expected_gross_return": 0.015, "report": f"Strong RSI and MACD crossover detected on {ticker}."}

    def run_macro_agent(self, ticker):
        """Simulates the Sentiment & Macro Agent."""
        print(f"📰 Macro Agent: Scanning global news and sentiment for {ticker}...")
        return {"signal": "BUY", "confidence": 8.5, "headline": f"Positive institutional options flow detected for {ticker}."}

    def execute_boardroom_cycle(self):
        print(f"\n==================================================")
        print(f"🏛️ INITIATING AI BOARDROOM CYCLE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"==================================================")

        # 1. Macro Regime Check (Are we crashing?)
        regime = self.hedging_engine.check_macro_regime()
        
        targets = []
        if regime == "BEAR":
            hedge_asset = self.hedging_engine.get_hedge_asset()
            print(f"🚨 BEAR REGIME ACTIVE: Diverting all capital to inverse hedge: {hedge_asset}")
            targets.append({"ticker": hedge_asset, "setup": "Bear Market Hedge", "conviction": 10.0})
        else:
            # 2. Bull/Neutral Market: Screen for global alpha
            targets = self.screener.scan_for_opportunities()

        if not targets:
            print("ℹ️ No viable high-conviction setups found in global scan. Holding cash.")
            return

        # 3. Deliberate on each target
        for target in targets:
            ticker = target['ticker']
            print(f"\n🎯 [BOARDROOM DELIBERATION]: {ticker} ({target.get('setup', 'Standard')})")
            
            tech_analysis = self.run_technical_agent(ticker)
            macro_analysis = self.run_macro_agent(ticker)

            # 4. FX & Fee Intelligence Check
            is_us_stock = not ticker.endswith(".L")
            gross_return = tech_analysis['expected_gross_return']
            net_alpha = calculate_net_alpha(gross_return, is_us_stock=is_us_stock)
            
            print(f"🧮 Fee Intelligence: Gross Expected: {gross_return*100:.2f}% | Net After T212 Fees: {net_alpha*100:.2f}%")

            consensus = "HOLD"
            veto = False
            
            if net_alpha <= 0.002: # We demand at least 0.2% pure profit AFTER fees
                print(f"⛔ VETO: Trade killed by Fee Intelligence. FX spreads destroy the alpha.")
                veto = True
            elif tech_analysis['signal'] == "BUY" and macro_analysis['signal'] == "BUY":
                consensus = "BUY"
                print(f"✅ CONSENSUS REACHED: Agents authorize acquisition of {ticker}.")

            # 5. Log the Deliberation to Supabase
            db.log_debate(
                ticker=ticker,
                tech_analysis=tech_analysis,
                sentiment_analysis=macro_analysis,
                consensus=consensus,
                conviction=target.get('conviction', 7.5),
                risk_veto=veto
            )

            # 6. Execute the Trade (if approved and not vetoed)
            if consensus == "BUY" and not veto:
                # Assuming T212 uses standard tickers, strip '.L' for UK stocks on T212 API if necessary, 
                # but T212 usually accepts their standard equity identifiers.
                t212_ticker = ticker.replace(".L", "") if ".L" in ticker else ticker
                self.trader.execute_market_order(
                    yf_ticker=ticker,
                    t212_ticker=t212_ticker,
                    boardroom_decision_id="cycle_auto_generated"
                )
                
            time.sleep(2) # Prevent rate-limiting if multiple targets exist

        print("\n🏁 Boardroom cycle complete. System returning to surveillance state.")

if __name__ == "__main__":
    engine = MultiAgentEngine()
    engine.execute_boardroom_cycle()
    # Inside MultiAgentEngine class...
def execute_boardroom_cycle(self):
    # ... (previous code)
    
    # NEW: News Intelligence Gatekeeper
    from news_engine import NewsEngine
    news = NewsEngine()
    
    for target in targets:
        ticker = target['ticker']
        
        # Consult News Engine
        is_safe, headline = news.is_trade_safe(ticker)
        
        if not is_safe:
            print(f"⛔ VETO: News Engine detected negative sentiment for {ticker}: {headline}")
            db.log_debate(ticker=ticker, consensus="VETOED", sentiment_analysis={"headline": headline}, risk_veto=True)
            continue # Skip to next target
            
        # ... (Proceed to Tech/Macro Agents and execution)