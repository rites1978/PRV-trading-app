import time
import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Any

from trading212_client import Trading212Client
from ai_engine import AIEngine
from risk_manager import RiskManager
from telegram_notifier import TelegramNotifier

STATE_FILE = "bot_state.json"
LOGS_FILE = "bot_logs.json"
HISTORY_FILE = "trade_history.json"

DEFAULT_WATCHLIST = [
    {"name": "Barclays", "yf_ticker": "BARC.L", "t212_ticker": "BARCl_EQ", "currency": "GBP", "is_uk_pence": True},
    {"name": "Lloyds Banking Group", "yf_ticker": "LLOY.L", "t212_ticker": "LLOYl_EQ", "currency": "GBP", "is_uk_pence": True},
    {"name": "BP plc", "yf_ticker": "BP.L", "t212_ticker": "BPl_EQ", "currency": "GBP", "is_uk_pence": True},
    {"name": "Apple Inc", "yf_ticker": "AAPL", "t212_ticker": "AAPL_US_EQ", "currency": "USD", "is_uk_pence": False},
    {"name": "Tesla Inc", "yf_ticker": "TSLA", "t212_ticker": "TSLA_US_EQ", "currency": "USD", "is_uk_pence": False},
    {"name": "Nvidia", "yf_ticker": "NVDA", "t212_ticker": "NVDA_US_EQ", "currency": "USD", "is_uk_pence": False},
    {"name": "Microsoft", "yf_ticker": "MSFT", "t212_ticker": "MSFT_US_EQ", "currency": "USD", "is_uk_pence": False}
]

class TradingBot:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TradingBot, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.client = Trading212Client()
        self.ai = AIEngine()
        self.risk = RiskManager()
        self.notifier = TelegramNotifier()
        
        self.is_running = False
        self.paper_mode = True # Safe default: Paper trading
        self.scan_interval = 60 # seconds
        self.min_confidence = 65 # Minimum AI confidence threshold %
        self.watchlist = DEFAULT_WATCHLIST
        
        self._thread = None
        self._stop_event = threading.Event()
        self._initialized = True
        
        self.load_state()

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                    self.paper_mode = state.get("paper_mode", True)
                    self.scan_interval = state.get("scan_interval", 60)
                    self.min_confidence = state.get("min_confidence", 65)
                    self.watchlist = state.get("watchlist", DEFAULT_WATCHLIST)
                    self.risk.min_portfolio_threshold = state.get("min_portfolio_threshold", 40000.0)
                    self.risk.max_trade_amount = state.get("max_trade_amount", 500.0)
                    self.risk.default_stop_loss_pct = state.get("stop_loss_pct", 0.03)
                    self.risk.default_take_profit_pct = state.get("take_profit_pct", 0.06)
            except Exception as e:
                print(f"[Bot State Load Error] {e}")

    def save_state(self):
        state = {
            "is_running": self.is_running,
            "paper_mode": self.paper_mode,
            "scan_interval": self.scan_interval,
            "min_confidence": self.min_confidence,
            "watchlist": self.watchlist,
            "min_portfolio_threshold": self.risk.min_portfolio_threshold,
            "max_trade_amount": self.risk.max_trade_amount,
            "stop_loss_pct": self.risk.default_stop_loss_pct,
            "take_profit_pct": self.risk.default_take_profit_pct,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"[Bot State Save Error] {e}")

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"timestamp": timestamp, "level": level, "message": message}
        print(f"[{timestamp}] [{level}] {message}")
        
        logs = []
        if os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, "r") as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        
        logs.insert(0, entry)
        logs = logs[:200] # Keep recent 200 logs
        
        try:
            with open(LOGS_FILE, "w") as f:
                json.dump(logs, f, indent=2)
        except Exception:
            pass

    def record_trade(self, trade_data: Dict[str, Any]):
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []
        
        history.insert(0, trade_data)
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            print(f"[Trade Record Error] {e}")

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self.save_state()
        self.log(f"🤖 Bot Started. Mode: {'PAPER (Simulation)' if self.paper_mode else 'LIVE EXECUTION'}")
        self.notifier.notify_alert("Autonomous Bot Started", f"Trading bot is now running in {'PAPER' if self.paper_mode else 'LIVE'} mode.")
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        self.save_state()
        self.log("🛑 Bot Stopped by user.")
        self.notifier.notify_alert("Autonomous Bot Stopped", "Trading bot has been stopped.")

    def run_single_iteration(self) -> Dict[str, Any]:
        """Execute one complete scan, risk check, and trade cycle."""
        self.log("🔄 Starting market analysis cycle...")
        
        # 1. Fetch live account summary
        account = self.client.get_account_summary()
        if not account.get("success"):
            self.log(f"❌ Failed to fetch account summary: {account.get('error')}", level="ERROR")
            return {"success": False, "error": account.get("error")}
        
        total_value = account["total_value"]
        available_cash = account["available_cash"]
        
        # 2. Risk check - Kill switch
        is_safe, risk_msg = self.risk.check_safeguards(total_value)
        if not is_safe:
            self.log(f"⚠️ {risk_msg}", level="CRITICAL")
            self.notifier.notify_alert("KILL SWITCH ACTIVATED", risk_msg)
            return {"success": False, "error": risk_msg}
        
        # 3. Check Open Positions
        positions = self.client.get_open_positions()
        holding_tickers = {p.get("ticker"): p for p in positions}
        self.log(f"📊 Account Safe. Portfolio: £{total_value:.2f} | Cash: £{available_cash:.2f} | Open Positions: {len(positions)}")

        # 4. Check Exit Conditions for Open Positions (Stop Loss / Take Profit)
        for p in positions:
            ticker = p.get("ticker")
            qty = float(p.get("quantity", 0))
            avg_price = float(p.get("averagePrice", 0))
            current_price = float(p.get("currentPrice", 0))
            
            should_exit, reason, pnl_pct = self.risk.evaluate_position_exit(avg_price, current_price)
            if should_exit and qty > 0:
                self.log(f"⚡ Exit triggered for {ticker}: {reason}", level="WARNING")
                if not self.paper_mode:
                    order_res = self.client.place_market_order(ticker, -qty)
                    if order_res.get("success"):
                        self.log(f"✅ Closed position {ticker} (Qty: {qty}) at £{current_price:.2f}")
                        self.record_trade({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "action": "SELL",
                            "ticker": ticker,
                            "quantity": qty,
                            "price": current_price,
                            "pnl_pct": round(pnl_pct * 100, 2),
                            "reason": reason,
                            "mode": "LIVE"
                        })
                        self.notifier.notify_trade("SELL", ticker, qty, current_price, reason, is_paper=False)
                    else:
                        self.log(f"❌ Failed to sell {ticker}: {order_res.get('error')}", level="ERROR")
                else:
                    self.log(f"🧪 [PAPER] Simulated SELL for {ticker} (Qty: {qty}) at £{current_price:.2f}. Reason: {reason}")
                    self.record_trade({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "action": "SELL",
                        "ticker": ticker,
                        "quantity": qty,
                        "price": current_price,
                        "pnl_pct": round(pnl_pct * 100, 2),
                        "reason": reason,
                        "mode": "PAPER"
                    })
                    self.notifier.notify_trade("SELL", ticker, qty, current_price, reason, is_paper=True)

        # 5. Scan Watchlist for Buy Signals
        signals_summary = []
        for item in self.watchlist:
            yf_ticker = item["yf_ticker"]
            t212_ticker = item["t212_ticker"]
            is_uk_pence = item.get("is_uk_pence", False)
            
            analysis = self.ai.analyze_ticker(yf_ticker, is_uk_pence=is_uk_pence)
            if not analysis.get("success"):
                continue
            
            signal = analysis["signal"]
            confidence = analysis["confidence"]
            price = analysis["current_price"]
            
            signals_summary.append({
                "ticker": t212_ticker,
                "signal": signal,
                "confidence": confidence,
                "price": price,
                "score": analysis["score"]
            })
            
            # If Signal is BUY and confidence exceeds threshold
            if signal == "BUY" and confidence >= self.min_confidence:
                already_holding = t212_ticker in holding_tickers
                quantity = self.risk.calculate_quantity(price, available_cash)
                estimated_cost = quantity * price
                
                can_buy, val_msg = self.risk.validate_buy_order(
                    total_value,
                    available_cash,
                    len(positions),
                    estimated_cost,
                    t212_ticker,
                    already_holding
                )
                
                if can_buy and quantity > 0:
                    trade_reason = f"AI Score: {analysis['score']} (Conf: {confidence}%). " + " | ".join(analysis["reasons"][:2])
                    
                    if not self.paper_mode:
                        self.log(f"🚀 Executing LIVE BUY: {quantity} shares of {t212_ticker} at ~{price:.2f}")
                        res = self.client.place_market_order(t212_ticker, quantity)
                        if res.get("success"):
                            self.log(f"✅ BUY Order Placed for {t212_ticker} (ID: {res['data'].get('id')})")
                            self.record_trade({
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "action": "BUY",
                                "ticker": t212_ticker,
                                "quantity": quantity,
                                "price": price,
                                "reason": trade_reason,
                                "mode": "LIVE"
                            })
                            self.notifier.notify_trade("BUY", t212_ticker, quantity, price, trade_reason, is_paper=False)
                            # Reduce available cash locally for subsequent checks in this loop
                            available_cash -= estimated_cost
                        else:
                            self.log(f"❌ Order failed for {t212_ticker}: {res.get('error')}", level="ERROR")
                    else:
                        self.log(f"🧪 [PAPER BUY] Simulated Buy {quantity} shares of {t212_ticker} at ~{price:.2f}")
                        self.record_trade({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "action": "BUY",
                            "ticker": t212_ticker,
                            "quantity": quantity,
                            "price": price,
                            "reason": trade_reason,
                            "mode": "PAPER"
                        })
                        self.notifier.notify_trade("BUY", t212_ticker, quantity, price, trade_reason, is_paper=True)
                else:
                    self.log(f"ℹ️ BUY signal for {t212_ticker} ({confidence}%) skipped: {val_msg}")

        self.log(f"🏁 Analysis cycle complete. Scanned {len(self.watchlist)} assets.")
        return {"success": True, "signals": signals_summary}

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self.run_single_iteration()
            except Exception as e:
                self.log(f"❌ Unexpected error in bot loop: {e}", level="ERROR")
            
            # Sleep in small increments to allow immediate stop
            for _ in range(self.scan_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

bot_instance = TradingBot()
