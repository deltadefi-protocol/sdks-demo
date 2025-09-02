"""
Binance WebSocket client for book ticker streams using sidan-binance-py
"""

import asyncio
import json
import time
from typing import Any

from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
import structlog

from .order_manager import OrderManager

logger = structlog.get_logger()


class BinanceWebSocket:
    def __init__(
        self, symbol: str = "adausdt", order_manager: OrderManager | None = None
    ):
        self.symbol = symbol.lower()
        self.client: SpotWebsocketStreamClient | None = None
        self.running = False
        self.order_manager = order_manager
        self._on_message = None  # Allow custom message handler override
        self._message_queue = asyncio.Queue()  # Queue for cross-thread communication
        self._loop = None  # Store reference to main event loop

    async def start(self):
        """Start the WebSocket connection"""
        logger.info(
            "🔌 Connecting to Binance WebSocket using sidan-binance-py",
            symbol=self.symbol.upper(),
        )
        self.running = True
        
        # Store reference to the current event loop
        self._loop = asyncio.get_running_loop()

        try:
            # Import the suppressor from main - if not available, create a dummy one
            try:
                from . import main
                SuppressPrints = main.SuppressPrints
            except (ImportError, AttributeError):
                class SuppressPrints:
                    def __enter__(self): return self
                    def __exit__(self, exc_type, exc_val, exc_tb): pass
                    
            # Create WebSocket client with message handler (suppress any debug output)
            with SuppressPrints():
                self.client = SpotWebsocketStreamClient(
                    on_message=self._message_handler,
                    stream_url="wss://stream.binance.com:9443"  # Explicit URL to avoid debug prints
                )

                # Subscribe to book ticker for the symbol
                self.client.book_ticker(symbol=self.symbol)

            # Start message processor task
            if self._on_message:
                asyncio.create_task(self._message_processor())

            logger.info(
                "✅ Connected to Binance WebSocket successfully",
                symbol=self.symbol.upper(),
            )

        except Exception as e:
            logger.error("❌ Failed to connect to Binance WebSocket", error=str(e))
            raise

    async def stop(self):
        """Stop the WebSocket connection"""
        logger.info("🔌 Disconnecting from Binance WebSocket")
        self.running = False

        if self.client:
            self.client.stop()
            logger.info("✅ Disconnected from Binance WebSocket")

    def _message_handler(self, _, message):
        """Handle incoming WebSocket messages"""
        if not self.running:
            return

        try:
            # Parse JSON if message is a string
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message

            # Only process book ticker data (ignore other message types)
            if isinstance(data, dict) and "s" in data and "b" in data and "a" in data:
                self._handle_book_ticker(data)

        except Exception as e:
            logger.error("Error in message handler", error=str(e), message=message)

    def _handle_book_ticker(self, data: dict[str, Any]):
        """Handle book ticker data"""
        try:
            # If custom message handler is set, queue the message for processing
            if self._on_message and self._loop:
                # Use thread-safe method to put message in queue
                self._loop.call_soon_threadsafe(self._message_queue.put_nowait, data)
                return

            symbol = data.get("s", "").upper()
            bid_price = float(data.get("b", 0))
            bid_qty = float(data.get("B", 0))
            ask_price = float(data.get("a", 0))
            ask_qty = float(data.get("A", 0))

            # Print WebSocket stream info (reduced frequency to avoid spam)
            if not hasattr(self, "_last_print") or time.time() - self._last_print > 2.0:
                print(f"📈 {symbol} Book Ticker:")
                print(f"   Bid: ${bid_price:.4f} (qty: {bid_qty:.2f})")
                print(f"   Ask: ${ask_price:.4f} (qty: {ask_qty:.2f})")
                print(f"   Spread: ${ask_price - bid_price:.4f}")
                print("-" * 40)
                self._last_print = time.time()

            logger.debug(  # Changed to debug to reduce log noise
                "📊 Book ticker update",
                symbol=symbol,
                bid_price=bid_price,
                bid_qty=bid_qty,
                ask_price=ask_price,
                ask_qty=ask_qty,
                spread=ask_price - bid_price,
            )

            # Send to order manager for processing if available
            if self.order_manager:
                asyncio.create_task(self.order_manager.handle_market_data(data))

        except (KeyError, ValueError, TypeError) as e:
            logger.error("Error parsing book ticker data", error=str(e), data=data)

    async def _message_processor(self):
        """Process messages from the queue using the custom handler"""
        while self.running:
            try:
                # Wait for messages from the queue
                data = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                
                # Process the message with the custom handler
                if self._on_message:
                    await self._on_message(data)
                    
            except asyncio.TimeoutError:
                # No messages in queue, continue
                continue
            except Exception as e:
                logger.error("Error in message processor", error=str(e))
