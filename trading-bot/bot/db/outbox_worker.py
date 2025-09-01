"""
Outbox worker for processing events

Implements the transactional outbox pattern for reliable event processing.
Processes events created by repository operations and handles retries.
"""

import asyncio
import json
from typing import Any

import structlog

from .repo import outbox_repo
from .sqlite import db_manager

logger = structlog.get_logger()


class OutboxEventHandler:
    """Base class for handling specific event types"""

    async def handle(self, event: dict[str, Any]) -> None:
        """Handle a specific event type"""
        raise NotImplementedError


class OrderEventHandler(OutboxEventHandler):
    """Handles order-related events"""

    async def handle(self, event: dict[str, Any]) -> None:
        """Process order events"""
        event_type = event["event_type"]
        payload = json.loads(event["payload"])
        order_id = event["aggregate_id"]

        logger.info(
            "Processing order event",
            event_type=event_type,
            order_id=order_id,
            event_id=event["event_id"],
        )

        if event_type == "order_created":
            await self._handle_order_created(order_id, payload)
        elif event_type == "order_status_updated":
            await self._handle_order_status_updated(order_id, payload)
        elif event_type == "order_filled":
            await self._handle_order_filled(order_id, payload)
        else:
            logger.warning("Unknown order event type", event_type=event_type)

    async def _handle_order_created(
        self, order_id: str, payload: dict[str, Any]
    ) -> None:
        """Handle order created events"""
        logger.info(
            "Order created",
            order_id=order_id,
            symbol=payload.get("symbol"),
            side=payload.get("side"),
            quantity=payload.get("quantity"),
        )

    async def _handle_order_status_updated(
        self, order_id: str, payload: dict[str, Any]
    ) -> None:
        """Handle order status update events"""
        status = payload.get("status")

        logger.info(
            "Order status updated",
            order_id=order_id,
            status=status,
            deltadefi_order_id=payload.get("deltadefi_order_id"),
        )

        # Handle specific status transitions
        if status == "submitted":
            # Order successfully submitted to DeltaDeFi
            await self._on_order_submitted(order_id, payload)
        elif status == "filled":
            # Order fully filled
            await self._on_order_filled(order_id, payload)
        elif status == "rejected":
            # Order rejected
            await self._on_order_rejected(order_id, payload)
        elif status == "failed":
            # Order failed to submit
            await self._on_order_failed(order_id, payload)

    async def _handle_order_filled(
        self, order_id: str, payload: dict[str, Any]
    ) -> None:
        """Handle order fill events"""
        filled_quantity = payload.get("filled_quantity")
        avg_fill_price = payload.get("avg_fill_price")

        logger.info(
            "Order filled",
            order_id=order_id,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
        )

    async def _on_order_submitted(self, order_id: str, payload: dict[str, Any]) -> None:
        """Handle order submission"""

    async def _on_order_filled(self, order_id: str, payload: dict[str, Any]) -> None:
        """Handle order fill"""

    async def _on_order_rejected(self, order_id: str, payload: dict[str, Any]) -> None:
        """Handle order rejection"""
        error_message = payload.get("error_message")
        logger.warning("Order rejected", order_id=order_id, error=error_message)

    async def _on_order_failed(self, order_id: str, payload: dict[str, Any]) -> None:
        """Handle order failure"""
        error_message = payload.get("error_message")
        logger.error("Order failed", order_id=order_id, error=error_message)


class FillEventHandler(OutboxEventHandler):
    """Handles fill-related events"""

    async def handle(self, event: dict[str, Any]) -> None:
        """Process fill events"""
        event_type = event["event_type"]
        payload = json.loads(event["payload"])
        order_id = event["aggregate_id"]

        logger.info(
            "Processing fill event",
            event_type=event_type,
            order_id=order_id,
            event_id=event["event_id"],
        )

        if event_type == "fill_created":
            await self._handle_fill_created(order_id, payload)
        else:
            logger.warning("Unknown fill event type", event_type=event_type)

    async def _handle_fill_created(
        self, order_id: str, payload: dict[str, Any]
    ) -> None:
        """Handle fill creation"""
        logger.info(
            "Fill created",
            order_id=order_id,
            fill_id=payload.get("fill_id"),
            price=payload.get("price"),
            quantity=payload.get("quantity"),
        )


class OutboxWorker:
    """
    Background worker that processes events from the outbox table

    Implements reliable event processing with:
    - Exponential backoff for failed events
    - Dead letter queue for permanently failed events
    - Concurrent processing with rate limiting
    """

    def __init__(
        self, batch_size: int = 10, max_concurrent: int = 5, poll_interval: float = 1.0
    ):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        self.running = False
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # Event handlers by event type prefix
        self.handlers = {
            "order_": OrderEventHandler(),
            "fill_": FillEventHandler(),
        }

    async def start(self) -> None:
        """Start the outbox worker"""
        if self.running:
            logger.warning("Outbox worker already running")
            return

        self.running = True
        logger.info(
            "Starting outbox worker",
            batch_size=self.batch_size,
            max_concurrent=self.max_concurrent,
            poll_interval=self.poll_interval,
        )

        try:
            while self.running:
                await self._process_batch()
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            logger.info("Outbox worker cancelled")
        except Exception as e:
            logger.error("Outbox worker error", error=str(e), exc_info=True)
        finally:
            self.running = False
            logger.info("Outbox worker stopped")

    async def stop(self) -> None:
        """Stop the outbox worker"""
        logger.info("Stopping outbox worker")
        self.running = False

    async def _process_batch(self) -> None:
        """Process a batch of pending events"""
        try:
            # Get pending events
            events = await outbox_repo.get_pending_events(self.batch_size)

            if not events:
                return

            logger.debug("Processing event batch", count=len(events))

            # Process events concurrently
            tasks = [self._process_event(event) for event in events]

            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error("Error processing event batch", error=str(e), exc_info=True)

    async def _process_event(self, event: dict[str, Any]) -> None:
        """Process a single event with concurrency control"""
        async with self.semaphore:
            await self._handle_event(event)

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle a single event"""
        event_id = event["event_id"]
        event_type = event["event_type"]

        try:
            # Mark as processing
            await outbox_repo.mark_event_processing(event_id)

            # Find appropriate handler
            handler = self._get_handler(event_type)
            if not handler:
                raise ValueError(f"No handler found for event type: {event_type}")

            # Process the event
            await handler.handle(event)

            # Mark as completed
            await outbox_repo.mark_event_completed(event_id)

            logger.debug(
                "Event processed successfully", event_id=event_id, event_type=event_type
            )

        except Exception as e:
            # Mark as failed with retry scheduling
            error_msg = str(e)
            retry_delay = self._calculate_retry_delay(event.get("retry_count", 0))

            await outbox_repo.mark_event_failed(event_id, error_msg, retry_delay)

            logger.error(
                "Event processing failed",
                event_id=event_id,
                event_type=event_type,
                error=error_msg,
                retry_count=event.get("retry_count", 0),
                retry_delay=retry_delay,
            )

    def _get_handler(self, event_type: str) -> OutboxEventHandler | None:
        """Get the appropriate handler for an event type"""
        for prefix, handler in self.handlers.items():
            if event_type.startswith(prefix):
                return handler
        return None

    def _calculate_retry_delay(self, retry_count: int) -> int:
        """Calculate exponential backoff delay"""
        # Exponential backoff: 2^retry_count * 60 seconds, max 1 hour
        delay = min(60 * (2**retry_count), 3600)
        return delay


class OutboxMonitor:
    """Monitors outbox health and provides metrics"""

    def __init__(self):
        pass

    async def get_stats(self) -> dict[str, Any]:
        """Get outbox processing statistics"""
        try:
            # Count events by status
            status_counts = {}
            for status in [
                "pending",
                "processing",
                "completed",
                "failed",
                "dead_letter",
            ]:
                query = "SELECT COUNT(*) as count FROM outbox WHERE status = ?"
                result = await db_manager.fetch_one(query, (status,))
                status_counts[status] = result["count"] if result else 0

            # Get oldest pending event
            oldest_pending = await db_manager.fetch_one(
                "SELECT MIN(created_at) as oldest FROM outbox WHERE status = 'pending'"
            )

            # Get failed events count by retry count
            retry_counts = {}
            for i in range(6):  # 0-5 retries
                query = "SELECT COUNT(*) as count FROM outbox WHERE retry_count = ? AND status = 'failed'"
                result = await db_manager.fetch_one(query, (i,))
                retry_counts[f"retry_{i}"] = result["count"] if result else 0

            return {
                "status_counts": status_counts,
                "oldest_pending_age": oldest_pending["oldest"]
                if oldest_pending["oldest"]
                else None,
                "retry_counts": retry_counts,
                "total_events": sum(status_counts.values()),
            }

        except Exception as e:
            logger.error("Error getting outbox stats", error=str(e), exc_info=True)
            return {"error": str(e)}

    async def cleanup_completed_events(self, older_than_hours: int = 24) -> int:
        """Clean up completed events older than specified hours"""
        try:
            cutoff_time = asyncio.get_event_loop().time() - (older_than_hours * 3600)

            query = """
            DELETE FROM outbox
            WHERE status = 'completed'
            AND processed_at < ?
            """

            async with db_manager.get_connection() as conn:
                cursor = await conn.execute(query, (cutoff_time,))
                deleted_count = cursor.rowcount
                await conn.commit()

            if deleted_count > 0:
                logger.info(
                    "Cleaned up completed events",
                    count=deleted_count,
                    older_than_hours=older_than_hours,
                )

            return deleted_count

        except Exception as e:
            logger.error("Error cleaning up outbox events", error=str(e), exc_info=True)
            return 0


# Global instances
outbox_worker = OutboxWorker()
outbox_monitor = OutboxMonitor()


async def start_outbox_worker() -> None:
    """Start the global outbox worker"""
    await outbox_worker.start()


async def stop_outbox_worker() -> None:
    """Stop the global outbox worker"""
    await outbox_worker.stop()


async def get_outbox_stats() -> dict[str, Any]:
    """Get outbox processing statistics"""
    return await outbox_monitor.get_stats()


async def cleanup_outbox_events(older_than_hours: int = 24) -> int:
    """Clean up old completed events"""
    return await outbox_monitor.cleanup_completed_events(older_than_hours)
