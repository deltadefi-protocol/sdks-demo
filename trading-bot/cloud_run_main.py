#!/usr/bin/env python3
"""
Cloud Run Main Entry Point

This is a specialized entry point for Google Cloud Run that:
1. Starts the health server IMMEDIATELY to satisfy startup probes
2. Then starts the trading bot in the background

This separation ensures Cloud Run's HTTP requirement is met quickly.
"""

import asyncio
import os
import sys
import time
from threading import Thread

def start_health_server_immediate():
    """Start health server immediately for Cloud Run startup probe"""
    from health_server import start_health_server

    print("🏥 Starting health server for Cloud Run startup probe...")
    server = start_health_server()

    # Give it a moment to bind to port
    time.sleep(1.0)
    print("✅ Health server should be ready for Cloud Run probes")

    return server

def start_trading_bot():
    """Start the trading bot in background after health server is ready"""
    print("🤖 Starting trading bot in background...")

    # Import and run the trading bot main logic without signal handlers
    from bot.main import TradingBot
    import sys
    from bot.config import settings

    async def bot_main():
        """Bot main without signal handlers (for background thread)"""
        # Validate critical configuration
        if not settings.exchange.deltadefi_api_key:
            print("❌ DELTADEFI_API_KEY is required")
            return

        if not settings.exchange.trading_password:
            print("❌ TRADING_PASSWORD is required for order submission")
            return

        bot = TradingBot()

        try:
            await bot.run()
        except Exception as e:
            print(f"💥 Trading bot crashed: {e}")

    asyncio.run(bot_main())

def main():
    """Main entry point for Cloud Run"""
    import signal

    print("🚀 Cloud Run entry point starting...")

    # Start health server FIRST and IMMEDIATELY
    if os.getenv('PORT'):
        health_server = start_health_server_immediate()

        # Start trading bot in background thread
        bot_thread = Thread(target=start_trading_bot, daemon=False)
        bot_thread.start()

        # Setup signal handlers in main thread
        def signal_handler(signum, _frame):
            print(f"🛑 Received signal {signum} - shutting down gracefully")
            # Bot thread will exit naturally

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep main thread alive for health server
        try:
            bot_thread.join()
        except KeyboardInterrupt:
            print("🛑 Cloud Run service shutting down")
    else:
        # No PORT env var, run trading bot directly (local development)
        from bot.main import main as bot_main
        asyncio.run(bot_main())

if __name__ == "__main__":
    main()