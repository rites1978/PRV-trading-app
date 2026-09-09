"""
PRV CAPITAL | RUNTIME SAFETY GUARD

Single authority for two fail-closed safety properties:

1. LIVE BROKER WRITE GUARD
   Every mutating Trading212 call (POST / DELETE) must be explicitly authorised.
   Default posture is DENY. Verification scripts and regression tests therefore
   cannot place, cancel or modify broker orders unless the operator opts in.

2. TEST DATABASE ISOLATION
   When running under a test runtime, the production SQLite database is never
   opened. The connection is redirected to a disposable per-process temp DB.

Both properties are enforced at the lowest chokepoint available so that no
caller (test, script, engine or ad-hoc import) can bypass them by accident.
"""
import os
import sys
import logging
import tempfile
from typing import Optional, Tuple

logger = logging.getLogger("runtime_guard")

# Explicit operator opt-in flags
ENV_ALLOW_LIVE_READS = "PRV_ALLOW_LIVE_BROKER_READS"
ENV_ALLOW_LIVE_WRITES = "PRV_ALLOW_LIVE_BROKER_WRITES"
ENV_ALLOW_LIVE_WRITES_IN_TESTS = "PRV_ALLOW_LIVE_BROKER_WRITES_IN_TESTS"
ENV_TEST_DB_PATH = "PRV_TEST_DB_PATH"
ENV_FORCE_TEST_RUNTIME = "PRV_FORCE_TEST_RUNTIME"

# HTTP methods that mutate broker state
MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class LiveBrokerWriteBlocked(RuntimeError):
    """Raised when a mutating broker call is attempted without explicit authorisation."""


class LiveBrokerReadBlocked(RuntimeError):
    """Raised when a live broker read is attempted from a test runtime without opt-in."""


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("true", "1", "yes")


def is_test_runtime() -> bool:
    """
    Detect a test/verification runtime.

    Production entrypoints do not import pytest or unittest, so their presence in
    sys.modules is a reliable signal for this codebase.
    """
    if _env_true(ENV_FORCE_TEST_RUNTIME):
        return True
    if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
        return True
    if "unittest" in sys.modules:
        return True
    argv0 = os.path.basename(sys.argv[0] or "")
    if argv0 in ("pytest", "py.test"):
        return True
    return False


def live_broker_writes_allowed() -> Tuple[bool, str]:
    """Return (allowed, reason). Default posture is DENY."""
    in_test = is_test_runtime()
    if in_test:
        # A write flag alone never unlocks writes: live reads must also be authorised,
        # and enabling reads must never by itself enable writes.
        if not _env_true(ENV_ALLOW_LIVE_READS):
            return False, (
                f"BLOCKED_TEST_RUNTIME: live broker writes additionally require {ENV_ALLOW_LIVE_READS}=true"
            )
        if _env_true(ENV_ALLOW_LIVE_WRITES) and _env_true(ENV_ALLOW_LIVE_WRITES_IN_TESTS):
            return True, "ALLOWED_TEST_RUNTIME_DOUBLE_OPT_IN"
        return False, (
            "BLOCKED_TEST_RUNTIME: live broker writes require BOTH "
            f"{ENV_ALLOW_LIVE_WRITES}=true AND {ENV_ALLOW_LIVE_WRITES_IN_TESTS}=true"
        )
    if _env_true(ENV_ALLOW_LIVE_WRITES):
        return True, "ALLOWED_EXPLICIT_OPT_IN"
    return False, f"BLOCKED_DEFAULT_DENY: set {ENV_ALLOW_LIVE_WRITES}=true to authorise live broker writes"


def live_broker_reads_allowed() -> Tuple[bool, str]:
    """
    Return (allowed, reason).

    Production reads are always permitted. Test runtimes are denied by default so
    regression tests cannot depend on live Practice account state.
    """
    if not is_test_runtime():
        return True, "ALLOWED_PRODUCTION_RUNTIME"
    if _env_true(ENV_ALLOW_LIVE_READS):
        return True, "ALLOWED_TEST_RUNTIME_READ_OPT_IN"
    return False, (
        f"BLOCKED_TEST_RUNTIME: live broker reads require {ENV_ALLOW_LIVE_READS}=true. "
        "Tests must use mocks/fixtures/synthetic broker state."
    )


def assert_live_broker_read_allowed(method: str, endpoint: str) -> None:
    """Fail-closed gate for non-mutating broker requests."""
    allowed, reason = live_broker_reads_allowed()
    if allowed:
        return
    msg = f"LIVE_BROKER_READ_BLOCKED: {method.upper()} {endpoint} refused. {reason}"
    logger.critical(msg)
    raise LiveBrokerReadBlocked(msg)


def live_caches_may_hydrate_from_disk() -> bool:
    """
    Disk snapshot caches mirror the live Practice account. Under a test runtime they
    are withheld unless live reads are explicitly opted into, so tests never observe
    real positions/NAV through the cache back door.
    """
    return live_broker_reads_allowed()[0]


def assert_live_broker_write_allowed(method: str, endpoint: str) -> None:
    """
    Fail-closed gate for mutating broker requests.

    Raises LiveBrokerWriteBlocked rather than returning a falsy value so a blocked
    write can never be mistaken for a broker-side rejection or silently ignored.
    """
    if str(method).upper() not in MUTATING_METHODS:
        return
    allowed, reason = live_broker_writes_allowed()
    if allowed:
        return
    msg = f"LIVE_BROKER_WRITE_BLOCKED: {method.upper()} {endpoint} refused. {reason}"
    logger.critical(msg)
    raise LiveBrokerWriteBlocked(msg)


def resolve_db_path(configured_path: str) -> str:
    """
    Return the database path to use.

    Under a test runtime the production database is never returned; an explicit
    PRV_TEST_DB_PATH is honoured, otherwise a disposable per-process temp DB is used.
    """
    if not is_test_runtime():
        return configured_path
    explicit = os.getenv(ENV_TEST_DB_PATH, "").strip()
    if explicit:
        return explicit
    isolated = os.path.join(tempfile.gettempdir(), f"prv_test_{os.getpid()}.db")
    logger.warning(
        f"TEST_DB_ISOLATION: redirecting database from '{configured_path}' to '{isolated}'"
    )
    return isolated


def runtime_mode_report(configured_db_path: Optional[str] = None) -> dict:
    """Structured description of the active safety posture (for audit output)."""
    allowed, reason = live_broker_writes_allowed()
    r_allowed, r_reason = live_broker_reads_allowed()
    return {
        "is_test_runtime": is_test_runtime(),
        "live_broker_reads_allowed": r_allowed,
        "live_broker_read_reason": r_reason,
        "live_broker_writes_allowed": allowed,
        "live_broker_write_reason": reason,
        "default_test_mode": "MOCK_ONLY_NO_LIVE_WRITES",
        "live_write_requires_explicit_opt_in": True,
        "configured_db_path": configured_db_path,
        "effective_db_path": resolve_db_path(configured_db_path) if configured_db_path else None,
    }
