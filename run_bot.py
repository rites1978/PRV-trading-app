import time
import argparse
from bot_runner import bot_instance

def main():
    parser = argparse.ArgumentParser(description="PRV AI Autonomous Trading Engine CLI Daemon")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper", help="Execution mode: paper or live")
    parser.add_argument("--interval", type=int, default=60, help="Market scan loop interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single scan iteration and exit")
    args = parser.parse_args()

    bot = bot_instance
    bot.paper_mode = (args.mode == "paper")
    bot.scan_interval = args.interval
    bot.save_state()

    print("=" * 60)
    print("🤖 PRV AI AUTONOMOUS TRADING DAEMON")
    print(f"Mode: {'🧪 PAPER SIMULATION' if bot.paper_mode else '⚡ LIVE ORDER EXECUTION'}")
    print(f"Scan Interval: {bot.scan_interval}s")
    print(f"Min AI Confidence: {bot.min_confidence}%")
    print(f"Kill Switch Threshold: £{bot.risk.min_portfolio_threshold:,.2f}")
    print(f"Max Budget Per Trade: £{bot.risk.max_trade_amount:,.2f}")
    print("=" * 60)

    if args.once:
        print("\nExecuting single market iteration...")
        res = bot.run_single_iteration()
        print("\nResult:", res)
        return

    print("\nStarting autonomous loop (Press Ctrl+C to stop)...\n")
    bot.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping autonomous bot...")
        bot.stop()
        print("Bot stopped safely.")

if __name__ == "__main__":
    main()
