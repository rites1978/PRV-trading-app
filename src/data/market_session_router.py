"""
PRV Capital - Market Session Router
Evaluates active exchange trading sessions dynamically from Trading212 workingSchedules.
Eliminates UK-only hardcoded market closures and enables continuous cross-market scanning.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set
from src.data.broker_discovery import broker_discovery


class MarketSessionRouter:
    """Authoritative session router determining open/closed state per exchange and instrument."""

    def __init__(self):
        self._discovery = broker_discovery

    def is_schedule_open(self, schedule_id: int, utc_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Evaluates whether a specific workingScheduleId is in an active regular OPEN session at utc_dt.
        Returns: (is_open: bool, status_reason: str)
        """
        if utc_dt is None:
            utc_dt = datetime.now(timezone.utc)
        elif utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

        info = self._discovery.get_exchange_for_schedule(schedule_id)
        if not info:
            return False, f"UNKNOWN_SCHEDULE: ID {schedule_id} not mapped to any exchange"

        sched = info.get("schedule", {})
        time_events = sched.get("timeEvents", [])
        ex_name = info.get("exchange_name", f"Exchange_{info.get('exchange_id')}")

        if not time_events:
            return False, f"NO_SCHEDULE_EVENTS: {ex_name} has no calendar events"

        iso_now = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Find the latest event at or before utc_dt
        last_event = None
        next_event = None
        for ev in time_events:
            ev_date = ev.get("date", "")
            if ev_date <= iso_now:
                last_event = ev
            elif ev_date > iso_now:
                if next_event is None:
                    next_event = ev
                    break

        if not last_event:
            first_ev = time_events[0]
            return False, f"PRE_SESSION: {ex_name} session begins at {first_ev.get('date')} ({first_ev.get('type')})"

        ev_type = last_event.get("type", "")
        # Regular trading is active when the last event was OPEN
        if ev_type == "OPEN":
            close_info = f" Closes at {next_event.get('date')}" if next_event else ""
            return True, f"MARKET_OPEN: {ex_name} regular session active.{close_info}"
        else:
            next_info = f" Next open at {next_event.get('date')}" if next_event else ""
            return False, f"MARKET_CLOSED: {ex_name} is {ev_type}.{next_info}"

    def is_instrument_open(self, instrument: Dict[str, Any], utc_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """Returns whether the instrument's exchange is currently open for regular trading."""
        sched_id = instrument.get("workingScheduleId")
        if sched_id is None:
            return False, "MISSING_SCHEDULE_ID: Instrument has no workingScheduleId"
        return self.is_schedule_open(int(sched_id), utc_dt=utc_dt)

    def get_open_markets(self, utc_dt: Optional[datetime] = None) -> List[str]:
        """Returns the list of all currently open exchange names."""
        if utc_dt is None:
            utc_dt = datetime.now(timezone.utc)

        self._discovery.initialize()
        open_exchanges: Set[str] = set()
        for sched_id, info in self._discovery._schedules_to_exchange.items():
            is_open, _ = self.is_schedule_open(sched_id, utc_dt=utc_dt)
            if is_open:
                ex_name = info.get("exchange_name")
                if ex_name:
                    open_exchanges.add(ex_name)
        return sorted(list(open_exchanges))

    def filter_open_instruments(
        self,
        instruments: List[Dict[str, Any]],
        utc_dt: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Filters a list of instruments down to only those whose exchange is currently open."""
        open_list = []
        for inst in instruments:
            is_open, _ = self.is_instrument_open(inst, utc_dt=utc_dt)
            if is_open:
                open_list.append(inst)
        return open_list


    def is_any_market_open(self, utc_dt: Optional[datetime] = None) -> bool:
        """Returns True if at least one exchange in the universe is open for regular trading."""
        return len(self.get_open_markets(utc_dt=utc_dt)) > 0


market_session_router = MarketSessionRouter()
