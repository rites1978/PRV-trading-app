"""
PRV CAPITAL | BROKER PRICE-UNIT RESOLUTION

`Money` (src/core/money.py) is the canonical value type for every price in this
system. This module does NOT re-implement currency arithmetic: its single job is to
answer "which unit is this instrument quoted in at the broker?" and to hand that
answer to `Money`, which performs the conversion.

Trading212 quotes LSE instruments in their own native unit, which is NOT inferable
from the ticker name:

    CSP1_EQ   GBX      EQQQl_EQ  GBX      ISFl_EQ   GBX
    EMIMl_EQ  GBX      SGLNl_EQ  GBX      SWDAl_EQ  GBX
    IGLTl_EQ  GBP  <-- GBP-quoted despite being an LSE line
    IWDAl_EQ  USD  <-- different line entirely from SWDAl_EQ

(Authoritative source: data/trading212_instruments.json, field `currencyCode`.)

Two rules make double-scaling impossible:

  1. Broker-native prices are normalised to GBP EXACTLY ONCE, at the adapter
     boundary, via broker_price_to_gbp().
  2. GBP prices are converted to the broker payload unit EXACTLY ONCE, at
     submission, via gbp_to_broker_price().

Unit resolution is metadata-driven only. There are deliberately NO magnitude
heuristics ("if value > 50 it must be pence"), because those make the same numeric
value mean different things depending on its size. An instrument whose unit cannot
be resolved raises rather than guessing -- callers fail closed.

Note: a broker ORDER payload carries currency="GBP" (the settlement currency) while
instrument.currency is the quote unit (e.g. "GBX"). Never infer price units from the
order-level currency field.
"""
from typing import Optional

from src.core.money import Money, Currency

# Rounding applied at the broker payload boundary, preserving existing tick behaviour.
_GBX_PAYLOAD_DP = 2
_GBP_PAYLOAD_DP = 4


class UnknownInstrumentUnitError(ValueError):
    """Raised when an instrument's broker price unit cannot be authoritatively resolved."""


# ──────────────────────────── unit resolution ────────────────────────────

def _lookup_is_uk_pence(instrument: str) -> Optional[bool]:
    """
    Resolve the broker quote unit from authoritative instrument metadata.

    Returns True (GBX/minor), False (GBP/major) or None when unresolvable.
    Never guesses from the ticker string or the magnitude of any price.
    """
    if not instrument:
        return None

    # 1. Ratified Core universe is the primary authority for Core production paths.
    try:
        from src.strategies.core_compounding_v1 import core_compounding_strategy
        for inst in core_compounding_strategy.CERTIFIED_UNIVERSE:
            candidates = {
                str(inst.get("symbol", "")).upper(),
                str(inst.get("t212_ticker", "")).upper(),
                str(inst.get("t212_ticker_alt", "")).upper(),
                str(inst.get("yf_ticker", "")).upper(),
            }
            if str(instrument).upper() in candidates and "is_uk_pence" in inst:
                return bool(inst["is_uk_pence"])
    except Exception:
        pass

    # 2. Broader universe metadata for non-Core instruments.
    try:
        from src.data.universe import universe_manager
        meta = (universe_manager.get_by_t212_ticker(instrument)
                or universe_manager.get_by_symbol(instrument))
        if meta and "is_uk_pence" in meta:
            return bool(meta["is_uk_pence"])
    except Exception:
        pass

    return None


def broker_quote_currency(instrument: str) -> Currency:
    """
    Resolve the broker QUOTE currency for an instrument as a `Money` currency.
    This is the one place a ticker is turned into a unit. Raises if unresolvable.
    """
    is_pence = _lookup_is_uk_pence(instrument)
    if is_pence is None:
        raise UnknownInstrumentUnitError(
            f"PRICE_UNIT_UNRESOLVED: no authoritative price-unit metadata for '{instrument}'. "
            "Refusing to guess; a wrong guess scales prices by 100."
        )
    return Currency.GBX if is_pence else Currency.GBP


def broker_price_unit(instrument: str) -> str:
    """Return 'GBX' or 'GBP' for an instrument. Raises if unresolvable."""
    return broker_quote_currency(instrument).value


def broker_money(raw_price: float, instrument: str, source: str = "BROKER") -> Money:
    """
    Wrap a BROKER-NATIVE price as `Money` tagged with its resolved quote currency.
    This is the adapter boundary: everything downstream is a typed value, not a float.
    """
    return Money(raw_price, broker_quote_currency(instrument), source=source)


# ─────────────────── conversions (arithmetic delegated to Money) ───────────────────

def broker_price_to_gbp(raw_price: float, instrument: str) -> float:
    """
    Normalise a BROKER-NATIVE price to canonical GBP. Apply exactly once, at the
    adapter boundary. Input must be straight from the broker, never pre-scaled.
    """
    return broker_money(raw_price, instrument).to_gbp().amount


def gbp_to_broker_price(gbp_price: float, instrument: str) -> float:
    """
    Convert a canonical GBP price to the broker payload unit. Apply exactly once,
    immediately before submission. Input must already be GBP.
    """
    money = Money(gbp_price, Currency.GBP, source="INTERNAL_GBP")
    if broker_quote_currency(instrument) == Currency.GBX:
        return round(money.to_minor().amount, _GBX_PAYLOAD_DP)
    return round(money.amount, _GBP_PAYLOAD_DP)


def stop_price_gbp(entry_price_gbp: float, stop_loss_pct: float) -> float:
    """Frozen risk rule applied in canonical GBP: stop = entry * (1 - pct)."""
    entry = Money(entry_price_gbp, Currency.GBP, source="INTERNAL_GBP")
    return round((entry * (1.0 - float(stop_loss_pct))).amount, 4)


def broker_stop_from_broker_entry(raw_entry_price: float, instrument: str,
                                  stop_loss_pct: float) -> float:
    """
    Single-call helper for the common Core path: broker-native entry price in,
    broker-native stop payload out, with exactly one normalisation and exactly one
    payload conversion in between.

        EMIMl_EQ: 4145.0 GBX -> £41.45 -> £40.621 -> 4062.10 GBX
    """
    entry_gbp = broker_price_to_gbp(raw_entry_price, instrument)
    stop_gbp = stop_price_gbp(entry_gbp, stop_loss_pct)
    return gbp_to_broker_price(stop_gbp, instrument)
