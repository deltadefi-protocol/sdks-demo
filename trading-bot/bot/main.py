"""
Trading Bot Main Entry Point
"""
import asyncio
import signal
import sys
import time
from typing import Optional

import structlog

from .binance_ws import BinanceWebSocket
from .log_config import setup_logging
from .order_manager import OrderManager
from .rate_limiter import TokenBucketRateLimiter

# Setup logging first
setup_logging()
logger = structlog.get_logger()


class TradingBot:
    def __init__(self):
        self.binance_ws: Optional[BinanceWebSocket] = None
        self.order_manager: Optional[OrderManager] = None
        self.running = False

    async def start(self):
        """Start the trading bot"""
        logger.info("🤖 Trading Bot Starting...")
        print("Hello World! Trading Bot is initializing...")
        
        self.running = True
        
        # Initialize rate limiter for DeltaDeFi (5 orders/second)
        rate_limiter = TokenBucketRateLimiter(max_tokens=5, refill_rate=5.0)
        
        # Initialize order manager with rate limiting
        self.order_manager = OrderManager(
            rate_limiter=rate_limiter,
            order_callback=self._mock_deltadefi_order_submission
        )
        
        # Start order manager
        await self.order_manager.start()
        
        # Initialize Binance WebSocket with order manager
        self.binance_ws = BinanceWebSocket(order_manager=self.order_manager)
        
        # Start WebSocket connection
        await self.binance_ws.start()
        
        logger.info("✅ Trading Bot started successfully")

    async def stop(self):
        """Stop the trading bot gracefully"""
        logger.info("🛑 Stopping Trading Bot...")
        self.running = False
        
        if self.binance_ws:
            await self.binance_ws.stop()
        
        if self.order_manager:
            await self.order_manager.stop()
        
        logger.info("✅ Trading Bot stopped")

    async def _mock_deltadefi_order_submission(self, order):
        """
        Mock DeltaDeFi order submission - replace with actual DeltaDeFi API call
        """
        logger.info(
            "🎯 [MOCK] Submitting order to DeltaDeFi",
            order_id=order.order_id,
            symbol=order.symbol,
            type=order.order_type.value,
            price=order.price,
            quantity=order.quantity
        )
        
        # Simulate API call delay
        await asyncio.sleep(0.1)
        
        logger.info(
            "✅ [MOCK] Order submitted to DeltaDeFi successfully", 
            order_id=order.order_id
        )

    async def run(self):
        """Main run loop"""
        await self.start()
        
        try:
            # Status monitoring loop
            last_status_log = 0
            while self.running:
                current_time = time.time()
                
                # Log status every 30 seconds
                if current_time - last_status_log > 30:
                    if self.order_manager:
                        status = self.order_manager.get_status()
                        logger.info(
                            "📊 Trading Bot Status",
                            **status
                        )
                    last_status_log = current_time
                
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            await self.stop()


async def main():
    """Main entry point"""
    bot = TradingBot()
    
    # Handle shutdown signals gracefully
    def signal_handler(signum, _frame):
        logger.info(f"Received signal {signum}")
        asyncio.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.run()
    except Exception as e:
        logger.error("Bot crashed", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
