"""
Order management with rate limiting, batching, and data aggregation
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any

import structlog

from .rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger()


class OrderPriority(Enum):
    """Order priority levels"""

    STOP_LOSS = 1  # Highest priority - risk management
    TAKE_PROFIT = 2  # High priority - profit taking
    LIMIT = 3  # Normal priority - regular trades
    MARKET = 4  # Lower priority - can wait for better timing


class OrderType(Enum):
    """Order types"""

    BUY = "buy"
    SELL = "sell"
    CANCEL = "cancel"


@dataclass
class PendingOrder:
    """Represents a pending order to be submitted to DeltaDeFi"""

    order_type: OrderType
    symbol: str
    price: float
    quantity: float
    priority: OrderPriority
    timestamp: float = field(default_factory=time.time)
    order_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


@dataclass
class MarketData:
    """Aggregated market data"""

    symbol: str
    bid_price: float
    ask_price: float
    bid_qty: float
    ask_qty: float
    timestamp: float
    spread: float = field(init=False)

    def __post_init__(self):
        self.spread = self.ask_price - self.bid_price


class DataAggregator:
    """
    Aggregates high-frequency market data to reduce order noise
    """

    def __init__(
        self,
        time_window: float = 0.2,  # 200ms aggregation window
        price_threshold: float = 0.001,
    ):  # 0.1% price change threshold
        self.time_window = time_window
        self.price_threshold = price_threshold
        self.last_data: dict[str, MarketData] = {}
        self.data_buffer: dict[str, list[MarketData]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def add_data(self, data: MarketData) -> MarketData | None:
        """
        Add market data and return aggregated data if conditions are met

        Args:
            data: New market data

        Returns:
            Aggregated data if window/threshold conditions met, None otherwise
        """
        async with self._lock:
            symbol = data.symbol

            # Add to buffer
            self.data_buffer[symbol].append(data)

            # Clean old data from buffer
            cutoff_time = data.timestamp - self.time_window
            self.data_buffer[symbol] = [
                d for d in self.data_buffer[symbol] if d.timestamp >= cutoff_time
            ]

            # Check if we should emit aggregated data
            should_emit = self._should_emit_data(symbol, data)

            if should_emit:
                aggregated = self._aggregate_data(symbol)
                self.last_data[symbol] = aggregated
                return aggregated

            return None

    def _should_emit_data(self, symbol: str, new_data: MarketData) -> bool:
        """Determine if we should emit aggregated data"""
        # Always emit first data point
        if symbol not in self.last_data:
            return True

        last_data = self.last_data[symbol]

        # Time-based condition
        time_elapsed = new_data.timestamp - last_data.timestamp
        if time_elapsed >= self.time_window:
            return True

        # Price change condition
        mid_price_old = (last_data.bid_price + last_data.ask_price) / 2
        mid_price_new = (new_data.bid_price + new_data.ask_price) / 2
        price_change = abs(mid_price_new - mid_price_old) / mid_price_old

        if price_change >= self.price_threshold:
            return True

        return False

    def _aggregate_data(self, symbol: str) -> MarketData:
        """Aggregate buffered data for symbol"""
        buffer_data = self.data_buffer[symbol]

        if not buffer_data:
            return self.last_data.get(symbol)

        # Use latest data point as base (most recent is most relevant)
        latest = buffer_data[-1]

        # Could implement VWAP or other aggregation methods here
        # For now, just return the latest with some smoothing

        return MarketData(
            symbol=symbol,
            bid_price=latest.bid_price,
            ask_price=latest.ask_price,
            bid_qty=latest.bid_qty,
            ask_qty=latest.ask_qty,
            timestamp=latest.timestamp,
        )


class OrderManager:
    """
    Manages order submission with rate limiting and intelligent batching
    """

    def __init__(
        self,
        rate_limiter: TokenBucketRateLimiter | None = None,
        data_aggregator: DataAggregator | None = None,
        order_callback: Callable | None = None,
    ):
        """
        Initialize order manager

        Args:
            rate_limiter: Rate limiter instance (defaults to 5/sec DeltaDeFi limit)
            data_aggregator: Data aggregator instance
            order_callback: Callback function for actual order submission
        """
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.data_aggregator = data_aggregator or DataAggregator()
        self.order_callback = order_callback

        # Order queue (priority queue)
        self.pending_orders: list[PendingOrder] = []
        self.active_orders: dict[str, PendingOrder] = {}

        # Processing control
        self.running = False
        self.processor_task: asyncio.Task | None = None

        self._order_lock = asyncio.Lock()

    async def start(self):
        """Start the order processing loop"""
        self.running = True
        self.processor_task = asyncio.create_task(self._process_orders())
        logger.info("🎯 Order manager started")

    async def stop(self):
        """Stop the order processing loop"""
        self.running = False
        if self.processor_task:
            self.processor_task.cancel()
            try:
                await self.processor_task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Order manager stopped")

    async def handle_market_data(self, raw_data: dict[str, Any]) -> None:
        """
        Process incoming market data and potentially trigger orders

        Args:
            raw_data: Raw market data from WebSocket
        """
        try:
            # Convert to MarketData
            market_data = MarketData(
                symbol=raw_data.get("s", "").upper(),
                bid_price=float(raw_data.get("b", 0)),
                ask_price=float(raw_data.get("a", 0)),
                bid_qty=float(raw_data.get("B", 0)),
                ask_qty=float(raw_data.get("A", 0)),
                timestamp=time.time(),
            )

            # Aggregate data to reduce noise
            aggregated_data = await self.data_aggregator.add_data(market_data)

            if aggregated_data:
                await self._evaluate_trading_opportunity(aggregated_data)

        except (KeyError, ValueError, TypeError) as e:
            logger.error("Error processing market data", error=str(e), data=raw_data)

    async def _evaluate_trading_opportunity(self, data: MarketData) -> None:
        """
        Evaluate if market data presents a trading opportunity

        This is where your trading strategy logic would go
        """
        logger.info(
            "📊 Evaluating trading opportunity",
            symbol=data.symbol,
            bid=data.bid_price,
            ask=data.ask_price,
            spread=data.spread,
        )

        # Example: Add a buy order if spread is reasonable
        # Replace with your actual trading logic
        if data.spread / data.bid_price < 0.01:  # Less than 1% spread
            await self.add_order(
                OrderType.BUY,
                data.symbol,
                data.bid_price * 0.999,  # Slightly below bid
                100.0,  # Example quantity
                OrderPriority.LIMIT,
            )

    async def add_order(
        self,
        order_type: OrderType,
        symbol: str,
        price: float,
        quantity: float,
        priority: OrderPriority,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add an order to the processing queue

        Returns:
            Order ID for tracking
        """
        order_id = f"{symbol}_{order_type.value}_{int(time.time() * 1000)}"

        order = PendingOrder(
            order_type=order_type,
            symbol=symbol,
            price=price,
            quantity=quantity,
            priority=priority,
            order_id=order_id,
            metadata=metadata or {},
        )

        async with self._order_lock:
            self.pending_orders.append(order)
            # Sort by priority
            self.pending_orders.sort(key=lambda x: x.priority.value)

        logger.info(
            "📝 Order queued",
            order_id=order_id,
            type=order_type.value,
            symbol=symbol,
            price=price,
            quantity=quantity,
            priority=priority.name,
            queue_size=len(self.pending_orders),
        )

        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order"""
        async with self._order_lock:
            # Remove from pending orders
            self.pending_orders = [
                order for order in self.pending_orders if order.order_id != order_id
            ]

            # Remove from active orders
            if order_id in self.active_orders:
                del self.active_orders[order_id]
                logger.info("🚫 Order cancelled", order_id=order_id)
                return True

        return False

    async def _process_orders(self):
        """Main order processing loop"""
        logger.info("🔄 Starting order processing loop")

        while self.running:
            try:
                await self._process_next_order()
                await asyncio.sleep(0.05)  # Small delay to prevent busy waiting

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in order processing loop", error=str(e))
                await asyncio.sleep(1)  # Longer delay on error

    async def _process_next_order(self):
        """Process the next order in queue if rate limit allows"""
        async with self._order_lock:
            if not self.pending_orders:
                return

            # Get highest priority order
            order = self.pending_orders[0]

        # Check rate limit
        if await self.rate_limiter.acquire():
            async with self._order_lock:
                if (
                    self.pending_orders
                    and self.pending_orders[0].order_id == order.order_id
                ):
                    self.pending_orders.pop(0)
                    self.active_orders[order.order_id] = order

            # Submit order
            await self._submit_order(order)
        else:
            # Rate limited, log and continue
            logger.debug(
                "Order submission rate limited",
                order_id=order.order_id,
                rate_limit_status=self.rate_limiter.get_status(),
            )

    async def _submit_order(self, order: PendingOrder):
        """Submit order to DeltaDeFi (or mock submission)"""
        logger.info(
            "🚀 Submitting order to DeltaDeFi",
            order_id=order.order_id,
            type=order.order_type.value,
            symbol=order.symbol,
            price=order.price,
            quantity=order.quantity,
            priority=order.priority.name,
        )

        # Mock order submission - replace with actual DeltaDeFi API call
        if self.order_callback:
            try:
                await self.order_callback(order)
            except Exception as e:
                logger.error(
                    "Order submission failed", order_id=order.order_id, error=str(e)
                )
        else:
            # Simulate processing time
            await asyncio.sleep(0.1)
            logger.info("✅ Order submitted successfully", order_id=order.order_id)

        # Remove from active orders
        async with self._order_lock:
            if order.order_id in self.active_orders:
                del self.active_orders[order.order_id]

    def get_status(self) -> dict[str, Any]:
        """Get current order manager status"""
        return {
            "running": self.running,
            "pending_orders": len(self.pending_orders),
            "active_orders": len(self.active_orders),
            "rate_limiter": self.rate_limiter.get_status(),
            "next_order": self.pending_orders[0].order_id
            if self.pending_orders
            else None,
        }
