"""
🏛️ PRV CAPITAL | AUTHORITATIVE MARKET SESSION ENGINE
Maintains authoritative state machines for:
- London Stock Exchange (LSE): Europe/London (GMT / BST)
- New York Stock Exchange & NASDAQ: America/New_York (EST / EDT)

Market Session States:
- PRE_MARKET
- REGULAR
- AFTER_HOURS
- OVERNIGHT
- FULLY_CLOSED (Weekends)
- HOLIDAY (Exchange Holidays)

Mandatory Execution Rule:
NEW ENTRY EXECUTION = REGULAR SESSION ONLY
Signals generated outside regular hours transition to PENDING_REVALIDATION.
Applies unconditionally to both PRACTICE and LIVE accounts.
"""
from enum import Enum
from datetime import datetime, time as dtime, date
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, Tuple
from src.data.exchange_calendar import exchange_calendar, ExchangeCalendar


class MarketSessionState(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    AFTER_HOURS = "AFTER_HOURS"
    OVERNIGHT = "OVERNIGHT"
    FULLY_CLOSED = "FULLY_CLOSED"
    HOLIDAY = "HOLIDAY"


class MarketHoursManager:
    """
    Authoritative Market Session Engine.
    Accurately determines granular session state, holiday status, and entry execution permissions.
    """
    def __init__(self):
        self.tz_london = ZoneInfo("Europe/London")
        self.tz_ny = ZoneInfo("America/New_York")
        self.calendar = exchange_calendar

    def get_uk_session_state(self, dt: Optional[datetime] = None) -> Tuple[MarketSessionState, str, Dict[str, Any]]:
        """
        Computes LSE market session state.
        Schedule:
        - 07:00 - 08:00: PRE_MARKET
        - 08:00 - 16:30 (or 12:30 early close): REGULAR
        - 16:30 - 17:00: AFTER_HOURS
        - 17:00 - 07:00: OVERNIGHT
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
        regular_close = dtime(12, 30) if is_early_close else dtime(16, 30)
        after_hours_close = dtime(13, 0) if is_early_close else dtime(17, 0)
        pre_market_open = dtime(7, 0)
        regular_open = dtime(8, 0)

        meta = {
            "exchange": "London Stock Exchange (LSE)",
            "timezone": "Europe/London",
            "current_time": now_uk.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "is_weekend": is_weekend,
            "is_holiday": is_holiday,
            "holiday_name": holiday_name,
            "is_early_close": is_early_close,
            "regular_hours": f"08:00 - {regular_close.strftime('%H:%M')} London Time"
        }

        if is_weekend:
            return MarketSessionState.FULLY_CLOSED, "Weekend - Market is fully closed.", meta
        if is_holiday:
            return MarketSessionState.HOLIDAY, f"Exchange Holiday: {holiday_name}", meta

        if cur_time < pre_market_open or cur_time >= after_hours_close:
            return MarketSessionState.OVERNIGHT, "Overnight - Outside all active trading hours.", meta
        if pre_market_open <= cur_time < regular_open:
            return MarketSessionState.PRE_MARKET, "Pre-Market auction and order book setup.", meta
        if regular_open <= cur_time <= regular_close:
            reason = "Regular Trading Hours" if not is_early_close else "Regular Trading Hours (Early Close)"
            return MarketSessionState.REGULAR, reason, meta
        if regular_close < cur_time < after_hours_close:
            return MarketSessionState.AFTER_HOURS, "After-Hours closing auction and reporting.", meta

        return MarketSessionState.OVERNIGHT, "Overnight session.", meta

    def get_us_session_state(self, dt: Optional[datetime] = None) -> Tuple[MarketSessionState, str, Dict[str, Any]]:
        """
        Computes NYSE/NASDAQ market session state.
        Schedule:
        - 04:00 - 09:30: PRE_MARKET
        - 09:30 - 16:00 (or 13:00 early close): REGULAR
        - 16:00 - 20:00: AFTER_HOURS
        - 20:00 - 04:00: OVERNIGHT
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
        regular_close = dtime(13, 0) if is_early_close else dtime(16, 0)
        after_hours_close = dtime(17, 0) if is_early_close else dtime(20, 0)
        pre_market_open = dtime(4, 0)
        regular_open = dtime(9, 30)

        meta = {
            "exchange": "NYSE / NASDAQ",
            "timezone": "America/New_York",
            "current_time": now_ny.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "is_weekend": is_weekend,
            "is_holiday": is_holiday,
            "holiday_name": holiday_name,
            "is_early_close": is_early_close,
            "regular_hours": f"09:30 - {regular_close.strftime('%H:%M')} NY Time"
        }

        if is_weekend:
            return MarketSessionState.FULLY_CLOSED, "Weekend - Market is fully closed.", meta
        if is_holiday:
            return MarketSessionState.HOLIDAY, f"Exchange Holiday: {holiday_name}", meta

        if cur_time < pre_market_open or cur_time >= after_hours_close:
            return MarketSessionState.OVERNIGHT, "Overnight - Outside all active trading hours.", meta
        if pre_market_open <= cur_time < regular_open:
            return MarketSessionState.PRE_MARKET, "Pre-Market trading session.", meta
        if regular_open <= cur_time <= regular_close:
            reason = "Regular Trading Hours" if not is_early_close else "Regular Trading Hours (Early Close)"
            return MarketSessionState.REGULAR, reason, meta
        if regular_close < cur_time < after_hours_close:
            return MarketSessionState.AFTER_HOURS, "After-Hours trading session.", meta

        return MarketSessionState.OVERNIGHT, "Overnight session.", meta

    def can_execute_new_entry(self, country_or_exchange: str, dt: Optional[datetime] = None) -> Tuple[bool, str, MarketSessionState]:
        """
        Enforces Challenge Strategy Rule:
        NEW ENTRY EXECUTION = REGULAR SESSION ONLY
        Returns (allowed, reason, session_state).
        """
        c = (country_or_exchange or "US").upper()
        if c in ["UK", "GB", "GBR", "LSE", "LONDON"]:
            state, reason, _ = self.get_uk_session_state(dt)
        else:
            state, reason, _ = self.get_us_session_state(dt)

        if state == MarketSessionState.REGULAR:
            return True, f"REGULAR_SESSION ({reason})", state
        return False, f"HOLD_CLOSED_MARKET: Session is {state.value} ({reason}). Entry blocked.", state

    def get_uk_market_status(self, dt: Optional[datetime] = None) -> Dict[str, Any]:
        state, reason, meta = self.get_uk_session_state(dt)
        is_open = (state == MarketSessionState.REGULAR)
        if meta["is_weekend"]:
            status = "UK MARKET CLOSED"
            reason_str = "Weekend"
        elif meta["is_holiday"]:
            status = f"UK MARKET CLOSED ({meta['holiday_name']})"
            reason_str = meta["holiday_name"]
        elif state == MarketSessionState.PRE_MARKET:
            status = "UK MARKET CLOSED"
            reason_str = "Outside Trading Hours (Pre-Market, opens 08:00 London Time)"
        elif state in (MarketSessionState.AFTER_HOURS, MarketSessionState.OVERNIGHT):
            status = "UK MARKET CLOSED"
            reason_str = f"Outside Trading Hours (Post-Market, closed London Time)"
        else:
            status = "UK MARKET OPEN"
            reason_str = "Regular Trading Hours"

        return {
            "exchange": meta["exchange"],
            "session_state": state.value,
            "is_open": is_open,
            "status": status,
            "reason": reason_str,
            "is_holiday": meta["is_holiday"],
            "holiday_name": meta["holiday_name"],
            "is_weekend": meta["is_weekend"],
            "is_early_close": meta["is_early_close"],
            "current_time": meta["current_time"],
            "trading_hours": meta["regular_hours"]
        }

    def get_us_market_status(self, dt: Optional[datetime] = None) -> Dict[str, Any]:
        state, reason, meta = self.get_us_session_state(dt)
        is_open = (state == MarketSessionState.REGULAR)
        if meta["is_weekend"]:
            status = "US MARKET CLOSED"
            reason_str = "Weekend"
        elif meta["is_holiday"]:
            status = f"US MARKET CLOSED ({meta['holiday_name']})"
            reason_str = meta["holiday_name"]
        elif state == MarketSessionState.PRE_MARKET:
            status = "US MARKET CLOSED"
            reason_str = "Outside Trading Hours (Pre-Market, opens 09:30 NY Time)"
        elif state in (MarketSessionState.AFTER_HOURS, MarketSessionState.OVERNIGHT):
            status = "US MARKET CLOSED"
            reason_str = f"Outside Trading Hours (Post-Market, closed NY Time)"
        else:
            status = "US MARKET OPEN"
            reason_str = "Regular Trading Hours"

        return {
            "exchange": meta["exchange"],
            "session_state": state.value,
            "is_open": is_open,
            "status": status,
            "reason": reason_str,
            "is_holiday": meta["is_holiday"],
            "holiday_name": meta["holiday_name"],
            "is_weekend": meta["is_weekend"],
            "is_early_close": meta["is_early_close"],
            "current_time": meta["current_time"],
            "trading_hours": meta["regular_hours"]
        }

    def is_uk_market_open(self, dt: Optional[datetime] = None) -> bool:
        return self.get_uk_session_state(dt)[0] == MarketSessionState.REGULAR

    def is_us_market_open(self, dt: Optional[datetime] = None) -> bool:
        return self.get_us_session_state(dt)[0] == MarketSessionState.REGULAR

    def is_any_market_open(self, dt_uk: Optional[datetime] = None, dt_us: Optional[datetime] = None) -> bool:
        return self.is_uk_market_open(dt_uk) or self.is_us_market_open(dt_us)

    def is_asset_market_open(self, country: str, dt: Optional[datetime] = None) -> bool:
        c = (country or "US").upper()
        if c in ["UK", "GB", "GBR", "LSE", "LONDON"]:
            return self.is_uk_market_open(dt)
        elif c in ["US", "USA", "NYSE", "NASDAQ", "AMERICA"]:
            return self.is_us_market_open(dt)
        return self.is_any_market_open(dt, dt)

    def get_market_status(self) -> Dict[str, Any]:
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
            reason_summary = f"UK: {uk_stat['session_state']} • US: {us_stat['session_state']}"

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
