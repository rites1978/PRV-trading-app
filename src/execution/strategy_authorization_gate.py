"""
PRV Capital - Strategy Authorization Gate
Enforces explicit strategy authorization for any instrument before order routing.

Architecture Invariants:
1. BROKER_DISCOVERY: Ingests all instruments exposed as tradable by Trading212.
2. TECHNICAL_EXECUTION_CAPABILITY: Evaluates whether our execution stack can mechanically support the instrument.
3. STRATEGY_AUTHORIZATION: Authorizes only instruments for which a ratified strategy module has explicit mandate.

Invariant:
Technical execution capability != strategy authorization.
Any new entry order MUST satisfy:
- TECHNICAL_EXECUTION_SUPPORTED == True
- STRATEGY_ORDER_AUTHORIZED == True

If an instrument is discovered and technically executable, but no strategy is authorized
to trade it, the order router MUST reject it with:
UNAUTHORIZED_STRATEGY_SCOPE
"""
import logging
from typing import Dict, Any, Tuple, Optional, Set

logger = logging.getLogger("strategy_authorization_gate")


class StrategyAuthorizationGate:
    """Evaluates whether an instrument is explicitly authorized under a specific strategy."""

    # Exact frozen 6 instruments for PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1
    FROZEN_CORE_V1_SYMBOLS: Set[str] = {"CSP1", "EQQQ", "ISF", "EMIM", "SGLN", "IGLT"}
    FROZEN_CORE_V1_TICKERS: Set[str] = {"CSP1_EQ", "EQQQl_EQ", "ISFl_EQ", "EMIMl_EQ", "SGLNl_EQ", "IGLTl_EQ"}

    def __init__(self):
        self._auth_checks_total: int = 0
        self._auth_approved_total: int = 0
        self._auth_rejected_total: int = 0

    def is_strategy_authorized(
        self,
        strategy_id: str,
        symbol: Optional[str] = None,
        t212_ticker: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates if the specified instrument is explicitly authorized for trading
        under the requested strategy_id.
        Returns:
            (is_authorized: bool, reason: str, details: Dict[str, Any])
        """
        self._auth_checks_total += 1
        strat_norm = str(strategy_id or "").strip().upper()
        sym_norm = str(symbol or "").strip().upper()
        ticker_norm = str(t212_ticker or "").strip()

        # Gate Check: PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1
        if strat_norm in ("PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1", "CORE_V1", "ETF_V1"):
            is_in_symbols = sym_norm in self.FROZEN_CORE_V1_SYMBOLS
            is_in_tickers = ticker_norm in self.FROZEN_CORE_V1_TICKERS
            # Check without case/suffix variations
            clean_ticker = ticker_norm.replace("l_EQ", "").replace("_EQ", "").upper()
            is_clean_match = clean_ticker in self.FROZEN_CORE_V1_SYMBOLS

            if is_in_symbols or is_in_tickers or is_clean_match:
                self._auth_approved_total += 1
                return True, "STRATEGY_ORDER_AUTHORIZED", {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "authorized_scope": "FROZEN_CORE_V1_SIX_ETF",
                }
            else:
                self._auth_rejected_total += 1
                reason = (
                    f"UNAUTHORIZED_STRATEGY_SCOPE: Instrument {symbol} ({t212_ticker}) is outside "
                    f"the frozen 6-ETF universe for strategy '{strategy_id}'. "
                    f"Permitted instruments: {sorted(list(self.FROZEN_CORE_V1_SYMBOLS))}"
                )
                return False, reason, {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "rejection_code": "UNAUTHORIZED_STRATEGY_SCOPE",
                }

        # Gate Check: V2 / STRATEGY_V2
        elif strat_norm in ("V2", "STRATEGY_V2"):
            # Check strategy registry authority
            from src.strategies.registry import strategy_registry
            if not strategy_registry.can_strategy_route_orders(strategy_id):
                self._auth_rejected_total += 1
                reason = f"UNAUTHORIZED_STRATEGY_SCOPE: Strategy '{strategy_id}' is shadow benchmark only."
                return False, reason, {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "rejection_code": "STRATEGY_SHADOW_ONLY",
                }

            # If V2 is active, verify instrument is in institutional universe
            from src.data.universe import INSTITUTIONAL_UNIVERSE
            inst_symbols = {e["symbol"].upper() for e in INSTITUTIONAL_UNIVERSE}
            inst_tickers = {e["t212_ticker"] for e in INSTITUTIONAL_UNIVERSE}

            if sym_norm in inst_symbols or ticker_norm in inst_tickers:
                self._auth_approved_total += 1
                return True, "STRATEGY_ORDER_AUTHORIZED", {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "authorized_scope": "INSTITUTIONAL_EQUITY_V2",
                }
            else:
                self._auth_rejected_total += 1
                reason = f"UNAUTHORIZED_STRATEGY_SCOPE: Instrument {symbol} ({t212_ticker}) is outside V2 institutional universe."
                return False, reason, {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "rejection_code": "UNAUTHORIZED_STRATEGY_SCOPE",
                }

        # Default: Unknown or Unratified Strategy Module
        self._auth_rejected_total += 1
        reason = (
            f"UNAUTHORIZED_STRATEGY_SCOPE: No ratified strategy module authorizes trading for "
            f"{symbol} ({t212_ticker}) under strategy_id '{strategy_id}'"
        )
        return False, reason, {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "t212_ticker": t212_ticker,
            "rejection_code": "STRATEGY_MODULE_NOT_YET_DEFINED",
        }

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns strategy authorization metrics."""
        return {
            "auth_checks_total": self._auth_checks_total,
            "auth_approved_total": self._auth_approved_total,
            "auth_rejected_total": self._auth_rejected_total,
            "frozen_core_v1_universe": sorted(list(self.FROZEN_CORE_V1_SYMBOLS)),
        }


strategy_authorization_gate = StrategyAuthorizationGate()
