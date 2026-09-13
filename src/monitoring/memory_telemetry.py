"""
PRV Capital — Process Memory Telemetry & Growth Observability
Provides cross-platform read-only memory, thread, descriptor, and cache telemetry.
Performs zero broker calls, zero DB writes, zero market-data calls, and zero execution actions.
"""
import sys
import os
import time
import logging
import threading
import resource
import ctypes
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone

logger = logging.getLogger("memory_telemetry")

# Darwin Mach Task Basic Info flavor definition
MACH_TASK_BASIC_INFO = 20

class _MachTaskBasicInfo(ctypes.Structure):
    _fields_ = [
        ('virtual_size', ctypes.c_uint64),
        ('resident_size', ctypes.c_uint64),
        ('resident_size_max', ctypes.c_uint64),
        ('user_time_sec', ctypes.c_int32),
        ('user_time_usec', ctypes.c_int32),
        ('system_time_sec', ctypes.c_int32),
        ('system_time_usec', ctypes.c_int32),
        ('policy', ctypes.c_int32),
        ('suspend_count', ctypes.c_int32),
    ]

_telemetry_thread_running = False
_telemetry_lock = threading.Lock()

# Alert threshold levels in MB
ALERT_THRESHOLDS: Tuple[float, float, float] = (300.0, 400.0, 475.0)


def get_process_memory_info() -> Tuple[float, Optional[float], Optional[int]]:
    """
    Read-only collection of process RSS (MB), Peak RSS (MB), and open file descriptor count.
    Supports Linux /proc/self filesystem and macOS Darwin task_info with zero external deps.
    """
    rss_mb: float = 0.0
    peak_mb: Optional[float] = None
    open_fds: Optional[int] = None

    # 1. Linux /proc/self/status & /proc/self/fd
    if os.path.exists("/proc/self/status"):
        try:
            rss_kb = None
            hwm_kb = None
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = float(line.split()[1])
                    elif line.startswith("VmHWM:"):
                        hwm_kb = float(line.split()[1])
            if rss_kb is not None:
                rss_mb = round(rss_kb / 1024.0, 2)
            if hwm_kb is not None:
                peak_mb = round(hwm_kb / 1024.0, 2)
            if os.path.exists("/proc/self/fd"):
                try:
                    open_fds = len(os.listdir("/proc/self/fd"))
                except Exception:
                    open_fds = None
            if rss_mb > 0.0:
                return rss_mb, peak_mb, open_fds
        except Exception:
            pass

    # 2. Darwin task_info via mach_task_self
    if sys.platform == "darwin":
        try:
            info = _MachTaskBasicInfo()
            count = ctypes.c_uint32(ctypes.sizeof(info) // 4)
            r = ctypes.CDLL(None).task_info(
                ctypes.CDLL(None).mach_task_self(),
                MACH_TASK_BASIC_INFO,
                ctypes.byref(info),
                ctypes.byref(count)
            )
            if r == 0:
                rss_mb = round(info.resident_size / (1024.0 * 1024.0), 2)
                peak_mb = round(info.resident_size_max / (1024.0 * 1024.0), 2)
                if os.path.exists("/dev/fd"):
                    try:
                        open_fds = len(os.listdir("/dev/fd"))
                    except Exception:
                        open_fds = None
                return rss_mb, peak_mb, open_fds
        except Exception:
            pass

    # 3. Fallback: resource.getrusage
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        factor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
        peak_mb = round(usage.ru_maxrss / factor, 2)
        rss_mb = peak_mb
    except Exception:
        pass

    return rss_mb, peak_mb, open_fds


def check_memory_growth_alerts(rss_mb: float) -> List[str]:
    """
    Log a warning only if process RSS crosses 300 MB, 400 MB, or 475 MB.
    Does not restart the service.
    Does not trigger trading actions.
    Does not cancel orders.
    Telemetry only.
    """
    alerts = []
    if rss_mb >= 475.0:
        msg = f"MEMORY_GROWTH_ALERT: Critical RSS threshold crossed: {rss_mb:.2f} MB >= 475 MB (approaching container 512 MB limit)"
        logger.warning(msg)
        alerts.append(msg)
    elif rss_mb >= 400.0:
        msg = f"MEMORY_GROWTH_ALERT: High RSS threshold crossed: {rss_mb:.2f} MB >= 400 MB"
        logger.warning(msg)
        alerts.append(msg)
    elif rss_mb >= 300.0:
        msg = f"MEMORY_GROWTH_ALERT: Elevated RSS threshold crossed: {rss_mb:.2f} MB >= 300 MB"
        logger.warning(msg)
        alerts.append(msg)
    return alerts


def get_memory_telemetry() -> Dict[str, Any]:
    """
    Collect current read-only runtime memory telemetry.
    Safe for production diagnostic endpoints:
    - Zero broker calls
    - Zero database reads/writes
    - Zero market-data network calls
    - Zero execution actions
    """
    rss_mb, peak_mb, open_fds = get_process_memory_info()
    thread_count = threading.active_count()

    # In-memory broker rate-limiter call history length (strictly in-memory attribute read)
    call_history_len = 0
    broker_cache_position_count = 0
    try:
        from src.brokers.trading212 import broker
        if hasattr(broker, "rate_limiter") and hasattr(broker.rate_limiter, "call_history"):
            call_history_len = len(broker.rate_limiter.call_history)
        if hasattr(broker, "_cached_positions") and broker._cached_positions is not None:
            broker_cache_position_count = len(broker._cached_positions)
    except Exception:
        pass

    # In-memory market data cache sizes (strictly in-memory dict read)
    market_data_cache_size = 0
    try:
        from src.data.market_data import market_data
        cache_count = len(getattr(market_data, "_cache", {}))
        snap_count = len(getattr(market_data, "_snapshot_cache", {}))
        market_data_cache_size = cache_count + snap_count
    except Exception:
        pass

    # Alert evaluation
    alerts = check_memory_growth_alerts(rss_mb)

    status = "HEALTHY"
    if rss_mb >= 475.0:
        status = "CRITICAL"
    elif rss_mb >= 400.0:
        status = "HIGH"
    elif rss_mb >= 300.0:
        status = "ELEVATED"

    return {
        "status": status,
        "mem_rss_mb": rss_mb,
        "mem_peak_rss_mb": peak_mb,
        "thread_count": thread_count,
        "open_fd_count": open_fds,
        "call_history_len": call_history_len,
        "broker_cache_position_count": broker_cache_position_count,
        "market_data_cache_size": market_data_cache_size,
        "MEM_RSS_MB": rss_mb,
        "MEM_PEAK_RSS_MB": peak_mb,
        "THREAD_COUNT": thread_count,
        "OPEN_FD_COUNT": open_fds,
        "CALL_HISTORY_LEN": call_history_len,
        "BROKER_CACHE_POSITION_COUNT": broker_cache_position_count,
        "MARKET_DATA_CACHE_SIZE": market_data_cache_size,
        "alerts": alerts,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def record_and_log_telemetry() -> Dict[str, Any]:
    """Record telemetry and output 5-minute production log line."""
    data = get_memory_telemetry()
    log_msg = (
        f"MEM_TELEMETRY: MEM_RSS_MB={data['mem_rss_mb']:.2f} | "
        f"MEM_PEAK_RSS_MB={data['mem_peak_rss_mb'] if data['mem_peak_rss_mb'] is not None else 'N/A'} | "
        f"THREAD_COUNT={data['thread_count']} | "
        f"OPEN_FD_COUNT={data['open_fd_count'] if data['open_fd_count'] is not None else 'UNSUPPORTED'} | "
        f"CALL_HISTORY_LEN={data['call_history_len']} | "
        f"BROKER_CACHE_POSITION_COUNT={data['broker_cache_position_count']} | "
        f"MARKET_DATA_CACHE_SIZE={data['market_data_cache_size']}"
    )
    logger.info(log_msg)
    return data


def start_memory_telemetry_worker(interval_seconds: int = 300, force: bool = False) -> bool:
    """
    Start background daemon thread logging memory telemetry every 5 minutes (300 seconds).
    Non-blocking, read-only.
    Idempotent: at most one daemon thread per process.
    Refuses in test runtime unless force=True.
    """
    if not force:
        if "unittest" in sys.modules or os.getenv("PRV_TESTING", "").lower() in ("true", "1", "yes"):
            return False

    global _telemetry_thread_running
    with _telemetry_lock:
        if _telemetry_thread_running:
            return False
        _telemetry_thread_running = True

    def _worker():
        try:
            record_and_log_telemetry()
        except Exception:
            pass

        while True:
            time.sleep(interval_seconds)
            try:
                record_and_log_telemetry()
            except Exception:
                pass

    try:
        thread = threading.Thread(target=_worker, daemon=True, name="memory-telemetry")
        thread.start()
        return True
    except Exception as e:
        with _telemetry_lock:
            _telemetry_thread_running = False
        logger.error(f"Failed to start memory telemetry thread: {e}")
        return False
