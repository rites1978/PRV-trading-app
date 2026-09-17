"""
PRV Capital - Quote Source Authority Registry
Defines explicit source-authority permissions for market data feeds.

Invariants:
- A source must have can_establish_current_freshness == True to establish quote freshness as CURRENT.
- A source must have can_establish_execution_quote == True for an order to be executable.
- Arbitrary payload flags (quote_freshness_status = CURRENT, is_current = True, is_execution_grade = True)
  must NEVER override source authority.
- Bulk screeners (e.g. Yahoo Finance) are BULK_SCREEN_ONLY and can NEVER establish freshness or execution quotes.
- In production, CURRENT_EXECUTION_GRADE_SOURCE_COUNT is currently 0 (fail-closed for new entries).
"""
from dataclasses import dataclass
from typing import Dict, Optional, List


@dataclass(frozen=True)
class QuoteSourceAuthority:
    source_id: str
    role: str
    can_establish_execution_quote: bool
    can_establish_current_freshness: bool
    status: str = "UNVERIFIED"


class QuoteSourceAuthorityRegistry:
    """
    Central authoritative registry defining data-source rights and role capabilities.
    """

    _KNOWN_SOURCES: Dict[str, QuoteSourceAuthority] = {
        "TRADING212_FEED": QuoteSourceAuthority(
            source_id="TRADING212_FEED",
            role="BROKER_FEED",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        ),
        "TRADING212": QuoteSourceAuthority(
            source_id="TRADING212",
            role="BROKER_FEED",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        ),
        "YAHOO": QuoteSourceAuthority(
            source_id="YAHOO",
            role="BULK_SCREEN_ONLY",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        ),
        "YFINANCE": QuoteSourceAuthority(
            source_id="YFINANCE",
            role="BULK_SCREEN_ONLY",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        ),
        "BULK_SCREEN": QuoteSourceAuthority(
            source_id="BULK_SCREEN",
            role="BULK_SCREEN_ONLY",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        ),
        "BULK_SCREEN_ONLY": QuoteSourceAuthority(
            source_id="BULK_SCREEN_ONLY",
            role="BULK_SCREEN_ONLY",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        ),
    }

    # Dynamically registered execution sources (e.g. verified broker stream or explicit test mock harness)
    _EXECUTION_SOURCES: Dict[str, QuoteSourceAuthority] = {}

    @classmethod
    def get_source_authority(cls, source_id: Optional[str]) -> QuoteSourceAuthority:
        """
        Resolves authority for a source identifier.
        Unrecognised or absent sources default strictly to UNAUTHORISED_SOURCE (fail-closed).
        """
        if not source_id:
            return QuoteSourceAuthority(
                source_id="UNKNOWN",
                role="UNAUTHORISED_SOURCE",
                can_establish_execution_quote=False,
                can_establish_current_freshness=False,
                status="UNVERIFIED"
            )
        sid = str(source_id).strip().upper()
        if sid in cls._EXECUTION_SOURCES:
            return cls._EXECUTION_SOURCES[sid]
        if sid in cls._KNOWN_SOURCES:
            return cls._KNOWN_SOURCES[sid]
        return QuoteSourceAuthority(
            source_id=sid,
            role="UNAUTHORISED_SOURCE",
            can_establish_execution_quote=False,
            can_establish_current_freshness=False,
            status="UNVERIFIED"
        )

    @classmethod
    def get_execution_grade_source_count(cls) -> int:
        """Returns the number of active attached execution-grade sources."""
        return len(cls._EXECUTION_SOURCES)

    @classmethod
    def register_execution_source(cls, source: QuoteSourceAuthority) -> None:
        """Registers a specifically verified execution-grade source."""
        cls._EXECUTION_SOURCES[source.source_id.upper()] = source

    @classmethod
    def unregister_execution_source(cls, source_id: str) -> None:
        cls._EXECUTION_SOURCES.pop(source_id.upper(), None)

    @classmethod
    def clear_execution_sources(cls) -> None:
        cls._EXECUTION_SOURCES.clear()

    @classmethod
    def get_all_registered_sources(cls) -> List[QuoteSourceAuthority]:
        all_sources = dict(cls._KNOWN_SOURCES)
        all_sources.update(cls._EXECUTION_SOURCES)
        return list(all_sources.values())
