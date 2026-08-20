import time
import subprocess
from datetime import datetime

print("🚀 PRV Capital Autonomous Daemon Initialized (Target NAV: £40,000)")
print("System running in 24/7 background mode. Press Ctrl+C to terminate.")

def run_trading_cycle():
    print(f"\n[DAEMON EXECUTION] Starting hourly cycle at {datetime.now()}")
    try:
        # Trigger the multi-agent engine execution
        result = subprocess.run(["python3", "multi_agent_engine.py"], capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(f"Errors: {result.stderr}")
    except Exception as e:
        print(f"❌ Daemon cycle execution error: {e}")

if __name__ == "__main__":
    while True:
        run_trading_cycle()
        # Sleep for 1 hour (3600 seconds) before the next institutional cycle
        print("⏳ Waiting for next hourly cycle...")
        time.sleep(3600)
        import time
import subprocess
from datetime import datetime
from portfolio_rebalancer import PortfolioRebalancer

print("🚀 PRV Capital Autonomous Daemon Initialized (Target NAV: £40,000)")
print("System running in 24/7 background mode. Press Ctrl+C to terminate.")

def run_trading_cycle():
    print(f"\n[DAEMON EXECUTION] Starting hourly cycle at {datetime.now()}")
    try:
        # 1. Run the Multi-Agent Boardroom & Execution Engine
        result = subprocess.run(["python3", "multi_agent_engine.py"], capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(f"Boardroom Errors: {result.stderr}")
            
        # 2. Run the Portfolio Risk Audit & Rebalancer
        print("🔍 Running automated portfolio risk audit...")
        rebalancer = PortfolioRebalancer()
        rebalancer.audit_portfolio()
        
    except Exception as e:
        print(f"❌ Daemon cycle execution error: {e}")

if __name__ == "__main__":
    while True:
        run_trading_cycle()
        # Sleep for 1 hour (3600 seconds) before the next institutional cycle
        print("⏳ Waiting for next hourly cycle...")
        time.sleep(3600)