"""
PRV Capital - Bulk Market Data Benchmark Script
Evaluates latency, memory footprint, thread count invariance, and throughput
across instrument batches (e.g. 50, 100, 500 symbols).
"""
import os
import sys
import time
import resource
import threading
from typing import List

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.broker_discovery import BrokerDiscoveryService
from src.data.technical_execution_capability import TechnicalExecutionCapabilityValidator
from src.data.bulk_market_data import BulkMarketDataProvider


def get_mem_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def run_benchmark_batch(
    provider: BulkMarketDataProvider,
    instruments: List[dict],
    sample_size: int,
    batch_size: int = 50,
    max_workers: int = 5,
    timeout: float = 8.0,
):
    print(f"\n{'='*60}")
    print(f"BENCHMARK: {sample_size} Instruments (BatchSize={batch_size}, MaxWorkers={max_workers})")
    print(f"{'='*60}")

    sample = instruments[:sample_size]
    provider.clear_cache()

    mem_before = get_mem_mb()
    threads_before = threading.active_count()
    t0 = time.time()

    results = provider.fetch_bulk_snapshots(
        sample,
        batch_size=batch_size,
        max_workers=max_workers,
        timeout=timeout
    )

    t1 = time.time()
    time.sleep(0.3)  # Allow thread cleanup settling
    threads_after = threading.active_count()
    mem_after = get_mem_mb()

    elapsed = t1 - t0
    success_count = sum(1 for s in results.values() if s.get("success"))
    success_pct = (success_count / len(sample)) * 100.0 if sample else 0.0
    mem_delta = mem_after - mem_before
    threads_delta = threads_after - threads_before

    print(f"Sample Count:     {len(sample)}")
    print(f"Elapsed Time:     {elapsed:.2f}s ({elapsed/len(sample)*1000:.1f}ms/sym)")
    print(f"Successful:       {success_count}/{len(sample)} ({success_pct:.1f}%)")
    print(f"Max RSS Memory:   {mem_before:.1f} MB -> {mem_after:.1f} MB (Delta: {mem_delta:+.1f} MB)")
    print(f"Active Threads:   {threads_before} -> {threads_after} (Delta: {threads_delta:+d})")

    if threads_delta != 0:
        print(f"WARNING: Thread leak detected! Delta: {threads_delta}")
    else:
        print("VERIFIED: Zero thread leaks!")

    return {
        "sample_size": sample_size,
        "elapsed_seconds": round(elapsed, 2),
        "success_rate_pct": round(success_pct, 1),
        "mem_delta_mb": round(mem_delta, 1),
        "threads_before": threads_before,
        "threads_after": threads_after,
    }


def main():
    print("Initializing Broker Discovery to extract tradable universe...")
    discovery = BrokerDiscoveryService()
    validator = TechnicalExecutionCapabilityValidator()

    all_tradable = discovery.get_tradable_instruments()
    print(f"Total tradable instruments discovered: {len(all_tradable)}")

    # Filter to technically supported equities/ETFs with verified feed tickers
    supported_instruments = []
    for item in all_tradable:
        is_sup, reason, details = validator.validate(item)
        if is_sup:
            supported_instruments.append(details)

    print(f"Total technically supported instruments: {len(supported_instruments)}")

    provider = BulkMarketDataProvider(
        batch_size=50,
        max_workers=5,
        request_timeout=8.0,
        cache_ttl_seconds=1800.0,
        max_cache_size=3000
    )

    benchmark_results = []
    for size in [50, 100, 500]:
        res = run_benchmark_batch(provider, supported_instruments, sample_size=size)
        benchmark_results.append(res)

    print("\n" + "="*60)
    print("BENCHMARK SUMMARY")
    print("="*60)
    for r in benchmark_results:
        print(f"Size: {r['sample_size']:<4} | Time: {r['elapsed_seconds']:>5.2f}s | Success: {r['success_rate_pct']:>5.1f}% | MemDelta: {r['mem_delta_mb']:>+5.1f}MB | Threads: {r['threads_before']}->{r['threads_after']}")


if __name__ == "__main__":
    main()
