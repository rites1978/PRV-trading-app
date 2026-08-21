from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Tuple

class MarketHoursManager:
    """
    Timezone-aware Market Hours Manager:
    - UK Equities (LSE): 08:00 to 16:30 London Time (Europe/London), Mon-Fri
    - US Equities (NYSE/NASDAQ): 09:30 to 16:00 New York Time (America/New_York), Mon-Fri
    """
    def __init__(self):
        self.tz_london = ZoneInfo("Europe/London")
        self.tz_ny = ZoneInfo("America/New_York")

    def is_uk_market_open(self) -> bool:
        now_uk = datetime.now(self.tz_london)
        if now_uk.weekday() >= 5:  # Saturday or Sunday
            return False
        cur_time = now_uk.time()
        return dtime(8, 0) <= cur_time <= dtime(16, 30)

    def is_us_market_open(self) -> bool:
        now_ny = datetime.now(self.tz_ny)
        if now_ny.weekday() >= 5:  # Saturday or Sunday
            return False
        cur_time = now_ny.time()
        return dtime(9, 30) <= cur_time <= dtime(16, 0)

    def is_any_market_open(self) -> bool:
        return self.is_uk_market_open() or self.is_us_market_open()

    def is_asset_market_open(self, country: str) -> bool:
        if country.upper() in ["UK", "GB"]:
            return self.is_uk_market_open()
        elif country.upper() in ["US", "USA"]:
            return self.is_us_market_open()
        return self.is_any_market_open()

    def get_market_status(self) -> Dict[str, Any]:
        now_uk = datetime.now(self.tz_london)
        now_ny = datetime.now(self.tz_ny)
        
        uk_open = self.is_uk_market_open()
        us_open = self.is_us_market_open()
        
        return {
            "server_time_uk": now_uk.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "server_time_ny": now_ny.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "uk_market_open": uk_open,
            "us_market_open": us_open,
            "any_market_open": uk_open or us_open,
            "session_state": "ACTIVE" if (uk_open or us_open) else "CLOSED"
        }

market_hours = MarketHoursManager()
