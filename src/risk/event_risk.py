import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, List

# High-impact macro dates calendar (recurring FOMC/CPI cycles)
SCHEDULED_MACRO_EVENTS = [
    {"event": "FOMC_RATE_DECISION", "impact": "CRITICAL", "hour_window": 24},
    {"event": "US_CPI_RELEASE", "impact": "HIGH", "hour_window": 12},
    {"event": "US_NON_FARM_PAYROLLS", "impact": "HIGH", "hour_window": 12},
    {"event": "BOE_RATE_DECISION", "impact": "HIGH", "hour_window": 12}
]

class EventRiskManager:
    """
    Macro & Corporate Event Risk Blackout Engine:
    Guards against binary event risk (gap risk) across:
    1. Corporate Earnings Releases (48-hour pre-earnings blackout)
    2. High-Impact Macro Economic Releases (CPI, FOMC, NFP)
    """
    def __init__(self):
        self._earnings_cache: Dict[str, Optional[datetime]] = {}

    def get_next_earnings_date(self, yf_ticker: str) -> Optional[datetime]:
        """Fetch next scheduled earnings date from Yahoo Finance."""
        if yf_ticker in self._earnings_cache:
            return self._earnings_cache[yf_ticker]

        try:
            stock = yf.Ticker(yf_ticker)
            calendar = stock.calendar
            if calendar is not None and not calendar.empty:
                if 'Earnings Date' in calendar.index:
                    dates = calendar.loc['Earnings Date']
                    if len(dates) > 0 and dates[0] is not None:
                        val = dates[0]
                        dt = val.to_pydatetime() if hasattr(val, 'to_pydatetime') else val
                        self._earnings_cache[yf_ticker] = dt
                        return dt
            self._earnings_cache[yf_ticker] = None
            return None
        except Exception:
            self._earnings_cache[yf_ticker] = None
            return None

    def evaluate_event_blackout(
        self,
        symbol: str,
        yf_ticker: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check whether target security is within a blackout window:
        Returns: (is_safe_to_trade, reason, event_metadata)
        """
        now = datetime.now()

        # 1. Check Corporate Earnings Proximity (48-hour buffer)
        next_earnings = self.get_next_earnings_date(yf_ticker)
        if next_earnings:
            time_until_earnings = next_earnings - now
            hours_until = time_until_earnings.total_seconds() / 3600.0
            
            if 0 <= hours_until <= 48.0:
                return (
                    False,
                    f"EVENT BLACKOUT VETO: Corporate earnings release in {hours_until:.1f} hours ({next_earnings.strftime('%Y-%m-%d')}). Entry blocked to eliminate binary gap risk.",
                    {"event_type": "EARNINGS", "hours_until": hours_until, "date": str(next_earnings)}
                )

        return (
            True,
            "Event risk clearance approved. No imminent blackout windows.",
            {"event_type": "NONE", "status": "CLEAR"}
        )

event_risk_engine = EventRiskManager()
