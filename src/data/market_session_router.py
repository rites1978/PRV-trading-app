"""
PRV Capital - Market Session Router
Evaluates active exchange trading sessions dynamically from Trading212 workingSchedules and extendedHours.
Eliminates UK-only hardcoded market closures and enables continuous cross-market scanning.
Supports: PRE_MARKET, REGULAR, AFTER_HOURS, OVERNIGHT, CLOSED, UNKNOWN.
Distinguishes REGULAR_SESSION_CLOSED from INSTRUMENT_NOT_TRADABLE_NOW.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple
from src.data.broker_discovery import broker_discovery


class MarketSessionRouter:
    """Authoritative session router determining open/closed state per exchange and instrument."""

    def __init__(self):
        self._discovery = broker_discovery

    def get_schedule_session(
        self, schedule_id: int, utc_dt: Optional[datetime] = None
    ) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        """
        Evaluates workingScheduleId at utc_dt against Trading212 exchange timeEvents.
        Returns:
            (exchange_session: str, next_event: Optional[Dict], last_event: Optional[Dict], exchange_name: str)
            where exchange_session is one of:
            PRE_MARKET, REGULAR, AFTER_HOURS, OVERNIGHT, CLOSED, UNKNOWN
        """
        if utc_dt is None:
            utc_dt = datetime.now(timezone.utc)
        elif utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

        info = self._discovery.get_exchange_for_schedule(schedule_id)
        if not info:
            return "UNKNOWN", None, None, f"Unknown_Schedule_{schedule_id}"

        sched = info.get("schedule", {})
        time_events = sched.get("timeEvents", [])
        ex_name = info.get("exchange_name", f"Exchange_{info.get('exchange_id')}")

        if not time_events:
            return "UNKNOWN", None, None, ex_name

        iso_now = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

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
            return "CLOSED", next_event, None, ex_name

        ev_type = last_event.get("type", "")
        if ev_type == "OPEN":
            session = "REGULAR"
        elif ev_type == "PRE_MARKET_OPEN":
            session = "PRE_MARKET"
        elif ev_type == "AFTER_HOURS_OPEN":
            session = "AFTER_HOURS"
        elif ev_type == "OVERNIGHT_OPEN":
            session = "OVERNIGHT"
        elif ev_type in ("CLOSE", "AFTER_HOURS_CLOSE"):
            session = "CLOSED"
        else:
            session = "UNKNOWN"

        return session, next_event, last_event, ex_name

    def is_schedule_open(self, schedule_id: int, utc_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Evaluates whether a specific workingScheduleId is in an active regular OPEN session at utc_dt.
        Preserves backward compatibility for core compounding engine.
        Returns: (is_open: bool, status_reason: str)
        """
        session, next_event, last_event, ex_name = self.get_schedule_session(schedule_id, utc_dt=utc_dt)
        if session == "UNKNOWN":
            return False, f"UNKNOWN_SCHEDULE: ID {schedule_id} not mapped to any exchange"
        if session == "REGULAR":
            close_info = f" Closes at {next_event.get('date')}" if next_event else ""
            return True, f"MARKET_OPEN: {ex_name} regular session active.{close_info}"
        else:
            ev_type = last_event.get("type", "CLOSED") if last_event else "CLOSED"
            next_info = f" Next event at {next_event.get('date')} ({next_event.get('type')})" if next_event else ""
            return False, f"MARKET_CLOSED: {ex_name} is {ev_type}.{next_info}"

    def get_instrument_session_details(
        self, instrument: Dict[str, Any], utc_dt: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Evaluates instrument tradability incorporating workingScheduleId, exchange calendar, and extendedHours.
        Separates Extended Market Hours (PRE_MARKET, AFTER_HOURS) from 24/5 Overnight Sessions (OVERNIGHT).
        Exposes:
        - SESSION_OPEN_NOW (bool)
        - EXTENDED_HOURS_ELIGIBLE (bool)
        - OVERNIGHT_ELIGIBILITY (TRUE, FALSE, UNKNOWN)
        - EXECUTION_SESSION (PRE_MARKET, REGULAR, AFTER_HOURS, OVERNIGHT, CLOSED, UNKNOWN)
        - NEXT_SESSION_TRANSITION (Dict with timestamp & event_type, or None)
        Distinguishes:
        - REGULAR_SESSION_CLOSED (bool)
        - INSTRUMENT_NOT_TRADABLE_NOW (bool)
        """
        sched_id = instrument.get("workingScheduleId")
        ext_eval = self._discovery.evaluate_extended_hours(instrument)
        extended_eligible = ext_eval["is_extended_hours_eligible"]
        extended_hours_status = ext_eval["extended_hours_status"]
        extended_hours_val = ext_eval["extended_hours"]

        # Overnight / 24-5 eligibility model
        # Trading212 Public API (/equity/metadata/instruments) does not expose an overnight/24-5 flag.
        # If explicitly present in instrument record, use it; otherwise strictly "UNKNOWN".
        raw_overnight = instrument.get("overnightHours")
        if raw_overnight is None:
            raw_overnight = instrument.get("overnightEligible")
        if raw_overnight is None:
            raw_overnight = instrument.get("is24_5")

        if raw_overnight is True:
            overnight_eligibility = "TRUE"
        elif raw_overnight is False:
            overnight_eligibility = "FALSE"
        else:
            overnight_eligibility = "UNKNOWN"

        if sched_id is None:
            return {
                "session_open_now": False,
                "extended_hours_eligible": extended_eligible,
                "extended_hours_status": extended_hours_status,
                "extended_hours": extended_hours_val,
                "overnight_eligibility": overnight_eligibility,
                "execution_session": "UNKNOWN",
                "exchange_session": "UNKNOWN",
                "exchange_name": "UNKNOWN",
                "regular_session_closed": True,
                "instrument_not_tradable_now": True,
                "next_session_transition": None,
                "status_reason": "MISSING_SCHEDULE_ID: Instrument has no workingScheduleId"
            }

        ex_session, next_ev, last_ev, ex_name = self.get_schedule_session(int(sched_id), utc_dt=utc_dt)

        next_transition = None
        if next_ev:
            next_transition = {
                "timestamp": next_ev.get("date"),
                "event_type": next_ev.get("type")
            }

        if ex_session == "REGULAR":
            return {
                "session_open_now": True,
                "extended_hours_eligible": extended_eligible,
                "extended_hours_status": extended_hours_status,
                "extended_hours": extended_hours_val,
                "overnight_eligibility": overnight_eligibility,
                "execution_session": "REGULAR",
                "exchange_session": "REGULAR",
                "exchange_name": ex_name,
                "regular_session_closed": False,
                "instrument_not_tradable_now": False,
                "next_session_transition": next_transition,
                "status_reason": f"REGULAR_SESSION_OPEN: {ex_name} regular session active"
            }
        elif ex_session in ("PRE_MARKET", "AFTER_HOURS"):
            # Extended market hours eligibility
            if extended_eligible:
                return {
                    "session_open_now": True,
                    "extended_hours_eligible": True,
                    "extended_hours_status": extended_hours_status,
                    "extended_hours": extended_hours_val,
                    "overnight_eligibility": overnight_eligibility,
                    "execution_session": ex_session,
                    "exchange_session": ex_session,
                    "exchange_name": ex_name,
                    "regular_session_closed": True,
                    "instrument_not_tradable_now": False,
                    "next_session_transition": next_transition,
                    "status_reason": f"EXTENDED_HOURS_OPEN: {ex_name} in {ex_session}; instrument eligible"
                }
            else:
                if extended_hours_status == "UNKNOWN":
                    status_reason = (
                        f"REGULAR_SESSION_CLOSED: {ex_name} in {ex_session} but extended-hours "
                        f"eligibility is UNKNOWN (INSTRUMENT_NOT_TRADABLE_NOW)"
                    )
                else:
                    status_reason = (
                        f"REGULAR_SESSION_CLOSED: {ex_name} in {ex_session} but instrument "
                        f"not extended-hours eligible (INSTRUMENT_NOT_TRADABLE_NOW)"
                    )
                return {
                    "session_open_now": False,
                    "extended_hours_eligible": False,
                    "extended_hours_status": extended_hours_status,
                    "extended_hours": extended_hours_val,
                    "overnight_eligibility": overnight_eligibility,
                    "execution_session": "CLOSED",
                    "exchange_session": ex_session,
                    "exchange_name": ex_name,
                    "regular_session_closed": True,
                    "instrument_not_tradable_now": True,
                    "next_session_transition": next_transition,
                    "status_reason": status_reason
                }
        elif ex_session == "OVERNIGHT":
            # 24/5 Overnight session eligibility: DO NOT authorize from extendedHours alone!
            if overnight_eligibility == "TRUE":
                return {
                    "session_open_now": True,
                    "extended_hours_eligible": extended_eligible,
                    "extended_hours_status": extended_hours_status,
                    "extended_hours": extended_hours_val,
                    "overnight_eligibility": "TRUE",
                    "execution_session": "OVERNIGHT",
                    "exchange_session": "OVERNIGHT",
                    "exchange_name": ex_name,
                    "regular_session_closed": True,
                    "instrument_not_tradable_now": False,
                    "next_session_transition": next_transition,
                    "status_reason": f"OVERNIGHT_OPEN: {ex_name} in OVERNIGHT; instrument verified 24/5 overnight eligible"
                }
            else:
                return {
                    "session_open_now": False,
                    "extended_hours_eligible": extended_eligible,
                    "extended_hours_status": extended_hours_status,
                    "extended_hours": extended_hours_val,
                    "overnight_eligibility": overnight_eligibility,
                    "execution_session": "CLOSED",
                    "exchange_session": "OVERNIGHT",
                    "exchange_name": ex_name,
                    "regular_session_closed": True,
                    "instrument_not_tradable_now": True,
                    "next_session_transition": next_transition,
                    "status_reason": (
                        f"OVERNIGHT_UNVERIFIED: {ex_name} in OVERNIGHT but overnight eligibility "
                        f"is {overnight_eligibility} (INSTRUMENT_NOT_TRADABLE_NOW)"
                    )
                }
        else:  # CLOSED or UNKNOWN
            return {
                "session_open_now": False,
                "extended_hours_eligible": extended_eligible,
                "extended_hours_status": extended_hours_status,
                "extended_hours": extended_hours_val,
                "overnight_eligibility": overnight_eligibility,
                "execution_session": ex_session,
                "exchange_session": ex_session,
                "exchange_name": ex_name,
                "regular_session_closed": True,
                "instrument_not_tradable_now": True,
                "next_session_transition": next_transition,
                "status_reason": f"MARKET_CLOSED: {ex_name} is {ex_session} (INSTRUMENT_NOT_TRADABLE_NOW)"
            }

    def is_instrument_open(
        self, instrument: Dict[str, Any], utc_dt: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """Returns whether the instrument is currently tradable (considering regular and extended sessions)."""
        details = self.get_instrument_session_details(instrument, utc_dt=utc_dt)
        return details["session_open_now"], details["status_reason"]

    def get_open_markets(self, utc_dt: Optional[datetime] = None) -> List[str]:
        """Returns the list of all currently open exchange names (regular or extended)."""
        if utc_dt is None:
            utc_dt = datetime.now(timezone.utc)

        self._discovery.initialize()
        open_exchanges: Set[str] = set()
        for sched_id, info in self._discovery._schedules_to_exchange.items():
            session, _, _, ex_name = self.get_schedule_session(sched_id, utc_dt=utc_dt)
            if session in ("REGULAR", "PRE_MARKET", "AFTER_HOURS", "OVERNIGHT"):
                if ex_name:
                    open_exchanges.add(ex_name)
        return sorted(list(open_exchanges))

    def filter_open_instruments(
        self,
        instruments: List[Dict[str, Any]],
        utc_dt: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Filters a list of instruments down to only those that are currently open/tradable."""
        open_list = []
        for inst in instruments:
            is_open, _ = self.is_instrument_open(inst, utc_dt=utc_dt)
            if is_open:
                open_list.append(inst)
        return open_list

    def is_any_market_open(self, utc_dt: Optional[datetime] = None) -> bool:
        """Returns True if at least one exchange in the universe is open."""
        return len(self.get_open_markets(utc_dt=utc_dt)) > 0


market_session_router = MarketSessionRouter()
