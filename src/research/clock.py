"""
🏛️ PRV CAPITAL | REPLAY CLOCK MODULE
Deterministic, monotonically advancing simulation clock.

Invariants:
1. Time moves strictly forward: t_{k+1} > t_k.
2. No backward jumps allowed.
3. Decision timestamp is strictly immutable within an event step.
"""
from datetime import datetime, date, timedelta
from typing import Optional, List
import pandas as pd


class ReplayClockViolationError(RuntimeError):
    """Raised when an illegal time jump or backward clock movement is attempted."""
    pass


class ReplayClock:
    """
    Monotonically advancing simulation clock.
    Controls the simulation timeline across all data feeds and agents.
    """
    def __init__(self, timeline: List[pd.Timestamp]):
        if not timeline:
            raise ValueError("ReplayClock requires a non-empty timeline.")
        # Ensure timeline is sorted and unique
        sorted_timeline = sorted(list(set(pd.to_datetime(timeline))))
        self._timeline: List[pd.Timestamp] = sorted_timeline
        self._cursor: int = 0
        self._current_time: pd.Timestamp = self._timeline[0]
        self._is_completed: bool = False

    @property
    def current_time(self) -> pd.Timestamp:
        return self._current_time

    @property
    def current_date(self) -> date:
        return self._current_time.date()

    @property
    def is_completed(self) -> bool:
        return self._is_completed

    @property
    def step_index(self) -> int:
        return self._cursor

    @property
    def total_steps(self) -> int:
        return len(self._timeline)

    def advance(self) -> Optional[pd.Timestamp]:
        """
        Advances the clock by exactly one time step.
        Returns the new current_time, or None if simulation is finished.
        """
        if self._cursor + 1 >= len(self._timeline):
            self._is_completed = True
            return None

        self._cursor += 1
        next_time = self._timeline[self._cursor]
        if next_time <= self._current_time:
            raise ReplayClockViolationError(
                f"Clock monotonicity violated: next_time {next_time} <= current_time {self._current_time}"
            )
        self._current_time = next_time
        return self._current_time

    def advance_to(self, target_time: pd.Timestamp) -> pd.Timestamp:
        """
        Advances the clock to a specific future timestamp in the timeline.
        Rejects backward jumps.
        """
        target_ts = pd.to_datetime(target_time)
        if target_ts < self._current_time:
            raise ReplayClockViolationError(
                f"Backward time jump rejected: target {target_ts} < current {self._current_time}"
            )
        if target_ts == self._current_time:
            return self._current_time

        # Find position in timeline
        while self._cursor < len(self._timeline) and self._timeline[self._cursor] < target_ts:
            self._cursor += 1

        if self._cursor >= len(self._timeline):
            self._is_completed = True
            self._current_time = self._timeline[-1]
            return self._current_time

        self._current_time = self._timeline[self._cursor]
        return self._current_time

    def reset(self):
        """Resets the clock to the beginning of the timeline."""
        self._cursor = 0
        self._current_time = self._timeline[0]
        self._is_completed = False
