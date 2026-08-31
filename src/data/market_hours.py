"""
🏛️ PRV CAPITAL | TIMEZONE & HOLIDAY AWARE MARKET HOURS MANAGER
Integrates live exchange schedules and holiday calendars for:
- London Stock Exchange (LSE): 08:00 - 16:30 London Time (Europe/London)
- New York Stock Exchange & NASDAQ (NYSE/NASDAQ): 09:30 - 16:00 New York Time (America/New_York)
"""
from datetime import datetime, time as dtime, date
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple
from src.data.exchange_calendar import exchange_calendar, ExchangeCalendar


class MarketHoursManager:
    """
    Timezone and Exchange-Holiday aware Market Hours Manager.
    Accurately determines open/closed states and closure reasons for UK and US markets.
    """
    def __init__(self):
        self.tz_london = ZoneInfo("Europe/London")
        self.tz_ny = ZoneInfo("America/New_York")
        self.calendar = exchange_calendar

    def get_uk_market_status(self, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Calculates exact status and closure reason for the London Stock Exchange (LSE).
        """
        now_uk = dt if dt is not None else datetime.now(self.tz_london)
        if now_uk.tzinfo is None:
            now_uk = now_uk.replace(tzinfo=self.tz_london)
        else:
            now_uk = now_uk.astimezone(self.tz_london)

        d = now_uk.date()
        cur_time = now_uk.time()
        is_weekend = d.weekday() >= 5
        holiday_name = self.calendar.get_uk_holiday_name(d)
        is_holiday = holiday_name is not None
        is_early_close = self.calendar.is_uk_early_close(d)
        close_time = dtime(12, 30) if is_early_close else dtime(16, 30)
        open_time = dtime(8, 0)

        is_open = False
        reason = "Regular Trading Hours"

        if is_weekend:
            reason = "Weekend"
            status = "UK MARKET CLOSED"
        elif is_holiday:
            reason = f"{holiday_name}"
            status = f"UK MARKET CLOSED ({holiday_name})"
        elif cur_time < open_time:
            reason = "Outside Trading Hours (Pre-Market, opens 08:00 London Time)"
            status = "UK MARKET CLOSED"
        elif cur_time > close_time:
            reason = f"Outside Trading Hours (Post-Market, closed {close_time.strftime('%H:%M')} London Time)"
            status = "UK MARKET CLOSED"
        else:
            is_open = True
            status = "UK MARKET OPEN"
            if is_early_close:
                reason = "Regular Trading Hours (Early Close 12:30 London Time)"

        return {
            "exchange": "London Stock Exchange (LSE)",
            "is_open": is_open,
            "status": status,
            "reason": reason,
            "is_holiday": is_holiday,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "is_early_close": is_early_close,
            "current_time": now_uk.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "trading_hours": f"08:00 - {close_time.strftime('%H:%M')} London Time"
        }

    def get_us_market_status(self, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Calculates exact status and closure reason for NYSE / NASDAQ.
        """
        now_ny = dt if dt is not None else datetime.now(self.tz_ny)
        if now_ny.tzinfo is None:
            now_ny = now_ny.replace(tzinfo=self.tz_ny)
        else:
            now_ny = now_ny.astimezone(self.tz_ny)

        d = now_ny.date()
        cur_time = now_ny.time()
        is_weekend = d.weekday() >= 5
        holiday_name = self.calendar.get_us_holiday_name(d)
        is_holiday = holiday_name is not None
        is_early_close = self.calendar.is_us_early_close(d)
        close_time = dtime(13, 0) if is_early_close else dtime(16, 0)
        open_time = dtime(9, 30)

        is_open = False
        reason = "Regular Trading Hours"

        if is_weekend:
            reason = "Weekend"
            status = "US MARKET CLOSED"
        elif is_holiday:
            reason = f"{holiday_name}"
            status = f"US MARKET CLOSED ({holiday_name})"
        elif cur_time < open_time:
            reason = "Outside Trading Hours (Pre-Market, opens 09:30 NY Time)"
            status = "US MARKET CLOSED"
        elif cur_time > close_time:
            reason = f"Outside Trading Hours (Post-Market, closed {close_time.strftime('%H:%M')} NY Time)"
            status = "US MARKET CLOSED"
        else:
            is_open = True
            status = "US MARKET OPEN"
            if is_early_close:
                reason = "Regular Trading Hours (Early Close 13:00 NY Time)"

        return {
            "exchange": "NYSE / NASDAQ",
            "is_open": is_open,
            "status": status,
            "reason": reason,
            "is_holiday": is_holiday,
            "holiday_name": holiday_name,
            "is_weekend": is_weekend,
            "is_early_close": is_early_close,
            "current_time": now_ny.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "trading_hours": f"09:30 - {close_time.strftime('%H:%M')} NY Time"
        }

    def is_uk_market_open(self, dt: Optional[datetime] = None) -> bool:
        return self.get_uk_market_status(dt)["is_open"]

    def is_us_market_open(self, dt: Optional[datetime] = None) -> bool:
        return self.get_us_market_status(dt)["is_open"]

    def is_any_market_open(self, dt_uk: Optional[datetime] = None, dt_us: Optional[datetime] = None) -> bool:
        return self.is_uk_market_open(dt_uk) or self.is_us_market_open(dt_us)

    def is_asset_market_open(self, country: str) -> bool:
        c = country.upper() if country else "US"
        if c in ["UK", "GB", "GBR", "LSE", "LONDON"]:
            return self.is_uk_market_open()
        elif c in ["US", "USA", "NYSE", "NASDAQ", "AMERICA"]:
            return self.is_us_market_open()
        return self.is_any_market_open()

    def get_market_status(self) -> Dict[str, Any]:
        """
        Returns full unified market status payload with granular reasons and headlines.
        """
        uk_stat = self.get_uk_market_status()
        us_stat = self.get_us_market_status()

        uk_open = uk_stat["is_open"]
        us_open = us_stat["is_open"]

        if uk_open and us_open:
            headline = "UK & US MARKETS OPEN"
            state = "ACTIVE"
            reason_summary = "LSE & US Exchanges in Regular Trading Hours"
        elif uk_open and not us_open:
            headline = "UK MARKET OPEN"
            state = "PARTIAL"
            reason_summary = f"UK Open • US Closed ({us_stat['reason']})"
        elif not uk_open and us_open:
            headline = "US MARKET OPEN"
            state = "PARTIAL"
            reason_summary = f"US Open • UK Closed ({uk_stat['reason']})"
        else:
            headline = "BOTH CLOSED"
            state = "CLOSED"
            reason_summary = f"UK: {uk_stat['reason']} • US: {us_stat['reason']}"

        return {
            "server_time_uk": uk_stat["current_time"],
            "server_time_ny": us_stat["current_time"],
            "uk_market_open": uk_open,
            "us_market_open": us_open,
            "any_market_open": uk_open or us_open,
            "all_markets_open": uk_open and us_open,
            "session_state": state,
            "headline": headline,
            "reason_summary": reason_summary,
            "uk": uk_stat,
            "us": us_stat
        }


market_hours = MarketHoursManager()
