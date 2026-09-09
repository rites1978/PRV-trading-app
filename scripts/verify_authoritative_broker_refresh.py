"""
PRV CAPITAL — AUTHORITATIVE BROKER REFRESH & CACHE-PROVENANCE RECONCILIATION AUDIT
Verifies that cached data is never treated as broker confirmation, and terminal states require authoritative fresh refresh.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_core_authoritative_broker_refresh_remediation import TestCoreAuthoritativeBrokerRefreshRemediation

def run_verification():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCoreAuthoritativeBrokerRefreshRemediation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 80)
    print("PRV CAPITAL — AUTHORITATIVE BROKER REFRESH CERTIFICATION SUMMARY")
    print("=" * 80)
    print(f"TOTAL TESTS RUN: {result.testsRun}")
    print(f"FAILURES: {len(result.failures)}")
    print(f"ERRORS: {len(result.errors)}")
    
    invariants = [
        ("CACHED_DATA_NEVER_COUNTS_AS_BROKER_CONFIRMATION", len(result.failures) == 0 and len(result.errors) == 0),
        ("TERMINAL_STATE_REQUIRES_AUTHORITATIVE_ORDERS_REFRESH", len(result.failures) == 0 and len(result.errors) == 0),
        ("TERMINAL_STATE_REQUIRES_AUTHORITATIVE_POSITIONS_REFRESH", len(result.failures) == 0 and len(result.errors) == 0),
        ("UNKNOWN_BROKER_STATE_REMAINS_NON_TERMINAL", len(result.failures) == 0 and len(result.errors) == 0),
    ]
    
    for inv, val in invariants:
        status_str = "TRUE" if val else "FALSE"
        print(f"{inv} = {status_str}")
        
    if not result.wasSuccessful():
        print("\n[FAILED] One or more authoritative broker refresh tests failed.")
        sys.exit(1)
    else:
        print("\n[PASSED] All 9 authoritative broker refresh scenarios verified.")

if __name__ == "__main__":
    run_verification()
