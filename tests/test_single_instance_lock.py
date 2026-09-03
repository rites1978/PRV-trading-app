"""
Unit test for SingleInstanceLock OS-level process mutex.
Verifies that:
1. First acquire succeeds.
2. Second acquire in another instance/process fails cleanly.
3. Release allows subsequent acquire.
"""
import os
import unittest
from src.core.single_instance_lock import SingleInstanceLock

class TestSingleInstanceLock(unittest.TestCase):
    def setUp(self):
        self.test_lock_path = "/tmp/test_prv_single_instance.lock"
        if os.path.exists(self.test_lock_path):
            try:
                os.remove(self.test_lock_path)
            except Exception:
                pass

    def tearDown(self):
        if os.path.exists(self.test_lock_path):
            try:
                os.remove(self.test_lock_path)
            except Exception:
                pass

    def test_single_instance_mutual_exclusion(self):
        lock1 = SingleInstanceLock(lock_file=self.test_lock_path)
        lock2 = SingleInstanceLock(lock_file=self.test_lock_path)

        # Instance 1 acquires successfully
        self.assertTrue(lock1.acquire())
        self.assertTrue(lock1.is_locked)

        # Instance 2 tries to acquire same lockfile -> must fail!
        self.assertFalse(lock2.acquire())
        self.assertFalse(lock2.is_locked)

        # Instance 1 releases
        lock1.release()
        self.assertFalse(lock1.is_locked)

        # Now Instance 2 can acquire
        self.assertTrue(lock2.acquire())
        self.assertTrue(lock2.is_locked)
        lock2.release()

    def test_engine_aborts_on_dual_instance(self):
        from src.core.single_instance_lock import single_instance_lock
        from src.core.engine import quant_engine
        
        # Manually hold lock
        self.assertTrue(single_instance_lock.acquire())
        
        # Engine starting while lock is held must raise RuntimeError
        quant_engine.is_running = False
        with self.assertRaises(RuntimeError) as ctx:
            quant_engine.start()
        self.assertIn("Single-instance violation", str(ctx.exception))
        
        single_instance_lock.release()

if __name__ == "__main__":
    unittest.main()
