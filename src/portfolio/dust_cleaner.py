from typing import Dict, Any, List
from src.brokers.trading212 import broker
from src.database.db import db

class DustPositionCleaner:
    """
    Automated portfolio hygiene module:
    Identifies and liquidates legacy micro/dust positions (< £100 nominal value)
    to eliminate clutter and ensure clean capital accounting.
    """
    def __init__(self, dust_threshold_gbp: float = 100.0):
        self.dust_threshold = dust_threshold_gbp

    def identify_dust_positions(self) -> List[Dict[str, Any]]:
        """Scan active portfolio for positions below dust threshold."""
        positions = broker.get_open_positions()
        dust = []
        for pos in positions:
            ticker = pos.get("ticker", "")
            qty = float(pos.get("quantity", 0.0))
            cur_price = float(pos.get("currentPrice", 0.0))
            nominal_val = qty * cur_price
            
            if 0.0 < nominal_val < self.dust_threshold:
                dust.append({
                    "ticker": ticker,
                    "quantity": qty,
                    "currentPrice": cur_price,
                    "nominal_value": round(nominal_val, 2),
                    "ppl": float(pos.get("ppl", 0.0))
                })
        return dust

    def liquidate_dust_positions(self, is_paper: bool = False) -> Dict[str, Any]:
        """Execute automated market sell on all identified dust positions."""
        dust_list = self.identify_dust_positions()
        liquidated = []
        failed = []
        total_freed_capital = 0.0

        for item in dust_list:
            ticker = item["ticker"]
            qty = item["quantity"]
            nominal_val = item["nominal_value"]

            if not is_paper:
                res = broker.place_market_order(ticker, -qty)
                if res.get("success"):
                    liquidated.append(ticker)
                    total_freed_capital += nominal_val
                    db.record_audit({
                        "event_type": "DUST_CLEANUP_SELL",
                        "symbol": ticker,
                        "market_conditions": {"nominal_value": nominal_val},
                        "agent_votes": {"action": "CLEANUP"},
                        "confidence_score": 100.0,
                        "trade_reason": f"Liquidated micro-position (< £{self.dust_threshold:.2f}) to free portfolio capital",
                        "risk_approval": True,
                        "position_size": qty,
                        "exit_reason": "DUST_CLEANUP",
                        "final_result": "SUCCESS"
                    })
                else:
                    failed.append({"ticker": ticker, "error": res.get("error")})
            else:
                liquidated.append(ticker)
                total_freed_capital += nominal_val

        return {
            "success": True,
            "liquidated_count": len(liquidated),
            "liquidated_tickers": liquidated,
            "failed_count": len(failed),
            "failed": failed,
            "freed_capital_gbp": round(total_freed_capital, 2)
        }

dust_cleaner = DustPositionCleaner()
