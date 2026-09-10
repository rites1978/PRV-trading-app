"""
PRV CAPITAL | TEST-RUNTIME EXTERNAL NETWORK GUARD

Tests must never touch the outside world. A suite run that reaches Supabase,
Yahoo Finance or any other host is not a controlled experiment: it mutates external
telemetry, depends on third-party availability, and stalls on their latency.

Installed only under a test runtime (see runtime_guard.is_test_runtime). Production
imports this module without effect unless install() is called explicitly, and
install() refuses to arm outside a test runtime.

Two layers are needed because not all traffic goes through Python sockets:

  1. socket.socket.connect / connect_ex -- catches requests, urllib3, httpx and the
     Supabase client.
  2. curl_cffi -- yfinance drives libcurl through CFFI, bypassing Python sockets
     entirely, so it is intercepted at the library boundary.

Loopback is permitted so a test may run a local server. Everything else fails
closed with ExternalNetworkBlocked, and every attempt is counted so a suite can
assert on the totals.
"""
import socket
from typing import Any, Dict, List, Optional, Tuple

from src.core.runtime_guard import is_test_runtime

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

_installed = False
_original_connect = None
_original_connect_ex = None
_original_curl_request = None

# Attempted (and refused) outbound connections, newest last.
attempts: List[Dict[str, Any]] = []


class ExternalNetworkBlocked(RuntimeError):
    """Raised when a test attempts an unapproved external network call."""


def _classify(host: str) -> str:
    h = (host or "").lower()
    if "supabase" in h:
        return "SUPABASE"
    if "yahoo" in h or "yfinance" in h or "yimg" in h:
        return "YFINANCE"
    if "trading212" in h:
        return "BROKER"
    return "OTHER"


def _is_loopback(host: str) -> bool:
    return (host or "").lower() in _LOOPBACK_HOSTS


def _record(host: str, port: Any, via: str) -> None:
    attempts.append({"host": host, "port": port, "via": via, "kind": _classify(host)})


def _refuse(host: str, port: Any, via: str) -> "ExternalNetworkBlocked":
    _record(host, port, via)
    return ExternalNetworkBlocked(
        f"EXTERNAL_NETWORK_BLOCKED: test runtime attempted {via} connection to "
        f"{host}:{port} ({_classify(host)}). Stub or mock this dependency."
    )


def _guarded_connect(self, address, *args, **kwargs):
    host, port = (address[0], address[1]) if isinstance(address, (tuple, list)) and len(address) >= 2 else (str(address), None)
    if _is_loopback(host):
        return _original_connect(self, address, *args, **kwargs)
    raise _refuse(host, port, "socket")


def _guarded_connect_ex(self, address, *args, **kwargs):
    host, port = (address[0], address[1]) if isinstance(address, (tuple, list)) and len(address) >= 2 else (str(address), None)
    if _is_loopback(host):
        return _original_connect_ex(self, address, *args, **kwargs)
    raise _refuse(host, port, "socket")


def _guarded_curl_request(self, method, url, *args, **kwargs):
    from urllib.parse import urlparse
    host = urlparse(str(url)).hostname or str(url)
    if _is_loopback(host):
        return _original_curl_request(self, method, url, *args, **kwargs)
    raise _refuse(host, urlparse(str(url)).port, "curl_cffi")


def install() -> Tuple[bool, str]:
    """Arm the guard. Refuses outside a test runtime so production is untouched."""
    global _installed, _original_connect, _original_connect_ex, _original_curl_request
    if _installed:
        return True, "already installed"
    if not is_test_runtime():
        return False, "not a test runtime; external network guard not installed"

    _original_connect = socket.socket.connect
    _original_connect_ex = socket.socket.connect_ex
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex

    try:
        from curl_cffi import requests as _curl_requests
        _original_curl_request = _curl_requests.Session.request
        _curl_requests.Session.request = _guarded_curl_request
    except Exception:
        _original_curl_request = None

    _installed = True
    return True, "external network guard installed"


def uninstall() -> None:
    """Restore the real transports (used by the guard's own tests)."""
    global _installed, _original_connect, _original_connect_ex, _original_curl_request
    if not _installed:
        return
    socket.socket.connect = _original_connect
    socket.socket.connect_ex = _original_connect_ex
    if _original_curl_request is not None:
        from curl_cffi import requests as _curl_requests
        _curl_requests.Session.request = _original_curl_request
    _installed = False


def is_installed() -> bool:
    return _installed


def counts() -> Dict[str, int]:
    """Refused-attempt counts by classification."""
    out = {"SUPABASE": 0, "YFINANCE": 0, "BROKER": 0, "OTHER": 0, "TOTAL": 0}
    for a in attempts:
        out[a["kind"]] = out.get(a["kind"], 0) + 1
        out["TOTAL"] += 1
    return out


def reset_counts() -> None:
    attempts.clear()
