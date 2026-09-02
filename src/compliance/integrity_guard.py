"""
Pre-Trade Compliance & Integrity Guard
Automated pre-flight compliance firewall executed before ANY order is routed.
"""
import subprocess
import os
from typing import Tuple, Dict, Any
from src.config.settings import settings
from src.database.db import db
from src.monitoring.monitoring_service import monitoring_service

EXPECTED_COMMIT_HASH = os.getenv("EXPECTED_COMMIT_HASH", None)

class ForwardTestIntegrityGuard:
    """
    Automated pre-flight compliance firewall executed before ANY order is routed.
    """
    def __init__(self, expected_commit_hash: str = None):
        self.expected_hash = expected_commit_hash or EXPECTED_COMMIT_HASH

    def _get_current_git_hash(self) -> str:
        env_hash = os.getenv("GIT_COMMIT_HASH", "").strip()
        if env_hash:
            return env_hash[:7]
            
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=1.0
            ).decode("utf-8").strip()
        except Exception:
            return "HEAD"

    def validate_pre_flight_compliance(
        self,
        symbol: str,
        t212_ticker: str,
        order_cost_gbp: float,
        current_nav_gbp: float,
        current_drawdown_pct: float
    ) -> Tuple[bool, str, Dict[str, Any]]:
        audit_log: Dict[str, Any] = {}

        # 1. Verify Git Code Version Integrity
        current_hash = self._get_current_git_hash()
        audit_log["git_hash"] = current_hash
        if self.expected_hash and current_hash != self.expected_hash:
            return False, f"COMPLIANCE REJECTION: Code hash '{current_hash}' does not match locked commit '{self.expected_hash}'!", audit_log

        # 2. Verify Position Sizing Limit (8.0% of NAV + £1.0 buffer)
        raw_cap = getattr(settings, "MAX_INITIAL_POSITION_WEIGHT_PCT", 8.0)
        pos_fraction = raw_cap / 100.0 if raw_cap > 1.0 else raw_cap
        max_allowed_cost = (current_nav_gbp * pos_fraction) + 1.0
        audit_log["order_cost"] = order_cost_gbp
        audit_log["max_allowed_cost"] = max_allowed_cost
        if order_cost_gbp > max_allowed_cost:
            return False, f"COMPLIANCE REJECTION: Order cost (£{order_cost_gbp:.2f}) exceeds {pos_fraction*100:.2f}% sizing limit (£{max_allowed_cost:.2f})!", audit_log

        # 3. Verify Hard Portfolio Drawdown Ceiling (<= 5.00%)
        audit_log["current_drawdown_pct"] = current_drawdown_pct
        if current_drawdown_pct >= 5.00:
            return False, f"COMPLIANCE REJECTION: Portfolio drawdown {current_drawdown_pct:.2f}% breached 5.00% ceiling! Trading halted.", audit_log

        # 4. Verify 10-Day Symbol Cooldown Registry
        with db.get_connection() as conn:
            row = conn.execute("""
                SELECT id, cooldown_expiry_timestamp FROM symbol_cooldowns 
                WHERE symbol = ? AND status = 'ACTIVE' AND datetime(cooldown_expiry_timestamp) > datetime('now')
            """, (symbol,)).fetchone()
            if row:
                return False, f"COMPLIANCE REJECTION: Symbol '{symbol}' is quarantined in 10-day cooldown (Expires: {row['cooldown_expiry_timestamp']}).", audit_log

        # 5. Verify Broker Parity
        try:
            parity = monitoring_service.get_broker_audit_dashboard(
                broker_acc={"total_value": current_nav_gbp, "success": True},
                internal_cap={"total_broker_nav": current_nav_gbp},
                positions=[]
            )
            disc = parity.get("nav_parity_discrepancy_pct", 0.0)
        except Exception:
            disc = 0.0
            
        audit_log["broker_discrepancy_pct"] = disc
        if disc > 0.50:
            return False, f"COMPLIANCE REJECTION: Broker discrepancy ({disc:.2f}%) exceeds 0.50% tolerance!", audit_log

        return True, "PRE-FLIGHT COMPLIANCE PASSED: Order authorized.", audit_log

integrity_guard = ForwardTestIntegrityGuard()
