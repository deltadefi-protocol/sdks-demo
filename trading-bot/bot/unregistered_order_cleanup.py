"""
Unregistered Order Cleanup Service

Periodically checks for orders that exist on the DeltaDeFi exchange
but are not tracked in our OMS database, and cancels them to maintain
a clean order book state.

This service addresses scenarios where:
- Bot restart leaves orphaned orders on the exchange
- Network failures cause order state mismatch
- Manual orders placed outside the bot system
"""

import asyncio
import time

import structlog

from .config import settings
from .db.repo import order_repo
from .deltadefi import DeltaDeFiClient
from .oms import OrderManagementSystem

logger = structlog.get_logger()


class UnregisteredOrderCleanupService:
    """Service to cleanup unregistered orders on the exchange"""

    def __init__(self, deltadefi_client: DeltaDeFiClient, oms: OrderManagementSystem):
        self.deltadefi_client = deltadefi_client
        self.oms = oms
        self.running = False
        self.cleanup_task = None

        # Metrics
        self.cleanup_runs = 0
        self.orders_found = 0
        self.orders_cancelled = 0
        self.cleanup_errors = 0
        self.last_cleanup_time = 0.0

    async def run_initial_cleanup(self):
        """Run initial cleanup synchronously before starting trading"""
        if not settings.system.cleanup_unregistered_orders:
            logger.info("Initial cleanup disabled in settings, skipping")
            return

        logger.info("🧹 Running initial cleanup of unregistered orders...")

        try:
            await self._perform_cleanup()
            logger.info("✅ Initial cleanup completed successfully")
        except Exception as e:
            logger.error("❌ Initial cleanup failed", error=str(e))
            raise

    async def start(self):
        """Start the cleanup service"""
        if self.running:
            logger.warning("Unregistered order cleanup service is already running")
            return

        self.running = True
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(
            "Unregistered order cleanup service started",
            enabled=settings.system.cleanup_unregistered_orders,
            interval_ms=settings.system.cleanup_check_interval_ms,
        )

    async def stop(self):
        """Stop the cleanup service"""
        self.running = False

        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Unregistered order cleanup service stopped")

    async def _cleanup_loop(self):
        """Main cleanup loop"""
        try:
            while self.running:
                if settings.system.cleanup_unregistered_orders:
                    try:
                        await self._perform_cleanup()
                        self.last_cleanup_time = time.time()
                        self.cleanup_runs += 1
                    except Exception as e:
                        self.cleanup_errors += 1
                        logger.error(
                            "Error during unregistered order cleanup",
                            error=str(e),
                            exc_info=True,
                        )

                # Wait for next cleanup interval
                await asyncio.sleep(settings.system.cleanup_check_interval_ms / 1000.0)

        except asyncio.CancelledError:
            logger.debug("Cleanup loop cancelled")
            raise

    async def _perform_cleanup(self):
        """Perform a single cleanup cycle"""
        logger.debug("Starting unregistered order cleanup cycle")

        try:
            # Get all open orders from the exchange
            exchange_orders = await self._get_exchange_orders()

            if not exchange_orders:
                logger.debug("No open orders found on exchange")
                return

            # Get all registered orders from database
            oms_orders = await self._get_registered_orders()

            # Find unregistered orders
            unregistered_orders = self._find_unregistered_orders(
                exchange_orders, oms_orders
            )

            if not unregistered_orders:
                logger.debug(
                    "All exchange orders are registered",
                    exchange_orders_count=len(exchange_orders),
                    oms_orders_count=len(oms_orders),
                )
                return

            logger.info(
                "Found unregistered orders on exchange",
                unregistered_count=len(unregistered_orders),
                exchange_total=len(exchange_orders),
                oms_total=len(oms_orders),
            )

            # Cancel unregistered orders
            await self._cancel_unregistered_orders(unregistered_orders)

        except Exception as e:
            logger.error("Failed to perform cleanup cycle", error=str(e), exc_info=True)
            raise

    async def _get_exchange_orders(self) -> list[dict]:
        """Get all open orders from DeltaDeFi exchange"""
        try:
            # Get open orders for our trading symbol
            response = await self.deltadefi_client.get_open_orders(
                symbol=settings.trading.symbol_dst
            )

            orders = response if isinstance(response, list) else []
            self.orders_found += len(orders)

            logger.debug(
                "Retrieved open orders from exchange",
                symbol=settings.trading.symbol_dst,
                count=len(orders),
            )

            return orders

        except Exception as e:
            logger.error(
                "Failed to retrieve open orders from exchange",
                symbol=settings.trading.symbol_dst,
                error=str(e),
            )
            raise

    async def _get_registered_orders(self) -> set[str]:
        """Get all registered order IDs from database"""
        # Get all active orders from database (not just in-memory OMS)
        active_orders = await order_repo.get_active_orders(symbol=settings.trading.symbol_dst)

        # Extract DeltaDeFi order IDs (external_order_id field)
        registered_external_ids = set()

        for order in active_orders:
            deltadefi_order_id = order.get("deltadefi_order_id")
            if deltadefi_order_id:
                registered_external_ids.add(deltadefi_order_id)

        logger.debug(
            "Retrieved registered orders from database",
            count=len(registered_external_ids),
            orders=list(registered_external_ids)[:10],  # Log first 10 for debugging
        )

        return registered_external_ids

    def _find_unregistered_orders(
        self, exchange_orders: list[dict], registered_ids: set[str]
    ) -> list[dict]:
        """Find orders that exist on exchange but not in OMS"""
        unregistered = []

        for exchange_order in exchange_orders:
            # Extract order ID from exchange order (format may vary)
            exchange_order_id = str(
                exchange_order.get("order_id") or exchange_order.get("id", "")
            )

            if exchange_order_id and exchange_order_id not in registered_ids:
                # Additional safety check: ignore very recent orders that might not be registered yet
                order_time = exchange_order.get(
                    "created_at", exchange_order.get("timestamp", 0)
                )

                # If order is newer than registration timeout, skip it (might be in progress)
                current_time = time.time() * 1000  # Convert to milliseconds
                timeout_ms = settings.system.order_registration_timeout_ms

                if isinstance(order_time, (int, float)):
                    order_age_ms = current_time - order_time

                    if order_age_ms < timeout_ms:
                        logger.debug(
                            "Skipping recent order that may still be registering",
                            order_id=exchange_order_id,
                            age_ms=order_age_ms,
                            timeout_ms=timeout_ms,
                        )
                        continue

                unregistered.append(exchange_order)
                logger.debug(
                    "Found unregistered order",
                    exchange_order_id=exchange_order_id,
                    symbol=exchange_order.get("symbol"),
                    side=exchange_order.get("side"),
                    quantity=exchange_order.get("quantity"),
                    price=exchange_order.get("price"),
                )

        return unregistered

    async def _cancel_unregistered_orders(self, unregistered_orders: list[dict]):
        """Cancel unregistered orders on the exchange with rate limiting"""
        cancelled_count = 0
        rate_limited_count = 0

        # Process orders in batches to handle rate limits better
        # Each cancel = 2 API calls, rate limit = 50 calls/minute = 25 cancels/minute
        batch_size = 5  # Process 5 orders (10 API calls), then pause

        for i, order in enumerate(unregistered_orders):
            try:
                order_id = str(order.get("order_id") or order.get("id", ""))

                if not order_id:
                    logger.warning("Skipping order with missing ID", order=order)
                    continue

                # Cancel order on exchange
                await self.deltadefi_client.cancel_order(
                    order_id=order_id,
                    symbol=order.get("symbol", settings.trading.symbol_dst),
                )

                cancelled_count += 1
                self.orders_cancelled += 1

                logger.info(
                    "Cancelled unregistered order",
                    order_id=order_id,
                    symbol=order.get("symbol"),
                    side=order.get("side"),
                    quantity=order.get("quantity"),
                    price=order.get("price"),
                )

                # Add delay between orders: 60s / 25 orders = 2.4s per order to stay under rate limit
                await asyncio.sleep(0.5)

            except Exception as e:
                error_str = str(e)

                # Check if this is a rate limit error (429)
                if "429" in error_str or "rate" in error_str.lower():
                    rate_limited_count += 1
                    logger.warning(
                        "Rate limited while cancelling order, will retry later",
                        order_id=order.get("order_id"),
                        rate_limited_count=rate_limited_count,
                        remaining_orders=len(unregistered_orders) - i,
                    )

                    # If we hit rate limits, pause longer before continuing
                    if rate_limited_count > 5:
                        logger.info(
                            "Multiple rate limits hit, pausing cleanup for 30 seconds",
                            cancelled_so_far=cancelled_count,
                            remaining=len(unregistered_orders) - i,
                        )
                        await asyncio.sleep(30)
                        rate_limited_count = 0  # Reset counter after pause
                    else:
                        await asyncio.sleep(2)  # Short pause for occasional rate limits

                else:
                    logger.error(
                        "Failed to cancel unregistered order",
                        order_id=order.get("order_id"),
                        error=error_str,
                    )

            # Batch processing: pause every batch_size orders
            if (i + 1) % batch_size == 0:
                logger.info(
                    "Processed batch of orders, pausing to respect rate limits",
                    batch_num=(i + 1) // batch_size,
                    cancelled_in_batch=min(batch_size, cancelled_count),
                    total_cancelled=cancelled_count,
                    remaining_orders=len(unregistered_orders) - i - 1,
                    estimated_time_remaining_minutes=(
                        (len(unregistered_orders) - i - 1) * 2.5
                    )
                    / 60,
                )
                await asyncio.sleep(3)  # Extra pause between batches

        if cancelled_count > 0:
            logger.info(
                "Cleanup cycle completed",
                cancelled_orders=cancelled_count,
                total_unregistered=len(unregistered_orders),
            )

    def get_stats(self) -> dict:
        """Get cleanup service statistics"""
        return {
            "running": self.running,
            "enabled": settings.system.cleanup_unregistered_orders,
            "cleanup_runs": self.cleanup_runs,
            "orders_found": self.orders_found,
            "orders_cancelled": self.orders_cancelled,
            "cleanup_errors": self.cleanup_errors,
            "last_cleanup_time": self.last_cleanup_time,
            "last_cleanup_age_seconds": int(time.time() - self.last_cleanup_time)
            if self.last_cleanup_time > 0
            else None,
            "interval_ms": settings.system.cleanup_check_interval_ms,
            "registration_timeout_ms": settings.system.order_registration_timeout_ms,
        }
