"""
Outbox worker for processing events

Implements the transactional outbox pattern for reliable event processing.
Processes events created by repository operations and handles retries.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
import json
import time
from typing import Any

import structlog

from .repo import outbox_repo
from .sqlite import db_manager

logger = structlog.get_logger()


class EventStatus(str, Enum):
    """Event processing status"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class CircuitBreakerState(str, Enum):
    """Circuit breaker states"""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""

    max_retries: int = 5
    base_delay: int = 60  # seconds
    max_delay: int = 3600  # seconds (1 hour)
    backoff_multiplier: float = 2.0
    jitter: bool = True


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""

    failure_threshold: int = 5  # failures to open circuit
    recovery_timeout: int = 300  # seconds to try recovery
    success_threshold: int = 2  # successes to close circuit


class CircuitBreaker:
    """Circuit breaker for event handlers"""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.next_attempt_time = 0

    async def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker"""
        if self.state == CircuitBreakerState.OPEN:
            if time.time() < self.next_attempt_time:
                raise Exception("Circuit breaker is OPEN")
            else:
                # Try to recover
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise

    async def _on_success(self):
        """Handle successful execution"""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
        elif self.state == CircuitBreakerState.CLOSED:
            self.failure_count = 0

    async def _on_failure(self):
        """Handle failed execution"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.next_attempt_time = time.time() + self.config.recovery_timeout
            logger.warning(
                "Circuit breaker opened",
                failure_count=self.failure_count,
                recovery_timeout=self.config.recovery_timeout,
            )
        elif self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
            self.next_attempt_time = time.time() + self.config.recovery_timeout


class DeadLetterQueue:
    """Handles permanently failed events"""

    def __init__(self):
        self.dlq_handlers: dict[str, Any] = {}

    async def send_to_dlq(self, event: dict[str, Any], final_error: str):
        """Send event to dead letter queue"""
        event_id = event["event_id"]
        event_type = event["event_type"]

        # Mark as dead letter in database
        await outbox_repo.mark_event_dead_letter(event_id, final_error)

        # Log critical error
        logger.critical(
            "Event sent to dead letter queue",
            event_id=event_id,
            event_type=event_type,
            aggregate_id=event.get("aggregate_id"),
            retry_count=event.get("retry_count", 0),
            final_error=final_error,
        )

        # Trigger alert/notification if configured
        await self._trigger_dlq_alert(event, final_error)

    async def _trigger_dlq_alert(self, event: dict[str, Any], error: str):
        """Trigger alert for DLQ events (implement based on alerting system)"""
        # This could integrate with:
        # - Slack/Discord webhooks
        # - Email notifications
        # - PagerDuty/monitoring systems
        # - Metrics systems

    async def reprocess_dlq_event(self, event_id: str) -> bool:
        """Attempt to reprocess a dead letter event"""
        try:
            # Reset event status to pending
            await outbox_repo.reset_event_for_reprocessing(event_id)

            logger.info("Event reset for reprocessing", event_id=event_id)
            return True
        except Exception as e:
            logger.error("Failed to reset DLQ event", event_id=event_id, error=str(e))
            return False


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
    Enhanced background worker that processes events from the outbox table

    Implements reliable event processing with:
    - Exponential backoff with jitter for failed events
    - Dead letter queue for permanently failed events
    - Circuit breaker for failing handlers
    - Concurrent processing with rate limiting
    - Transactional processing guarantees
    """

    def __init__(
        self,
        batch_size: int = 10,
        max_concurrent: int = 5,
        poll_interval: float = 1.0,
        retry_config: RetryConfig | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
    ):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        self.running = False
        self.semaphore = asyncio.Semaphore(max_concurrent)

        # Configuration
        self.retry_config = retry_config or RetryConfig()
        self.circuit_breaker_config = circuit_breaker_config or CircuitBreakerConfig()

        # Components
        self.dead_letter_queue = DeadLetterQueue()
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

        # Metrics
        self.processed_count = 0
        self.failed_count = 0
        self.dlq_count = 0
        self.start_time = time.time()

        # Event handlers by event type prefix
        self.handlers = {
            "order_": OrderEventHandler(),
            "fill_": FillEventHandler(),
        }

        # Initialize circuit breakers for each handler
        for handler_key in self.handlers:
            self.circuit_breakers[handler_key] = CircuitBreaker(
                self.circuit_breaker_config
            )

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
        """Handle a single event with enhanced error handling"""
        event_id = event["event_id"]
        event_type = event["event_type"]
        retry_count = event.get("retry_count", 0)

        try:
            # Mark as processing
            await outbox_repo.mark_event_processing(event_id)

            # Find appropriate handler and circuit breaker
            handler = self._get_handler(event_type)
            if not handler:
                raise ValueError(f"No handler found for event type: {event_type}")

            circuit_breaker = self._get_circuit_breaker(event_type)

            # Process the event through circuit breaker
            await circuit_breaker.call(handler.handle, event)

            # Mark as completed
            await outbox_repo.mark_event_completed(event_id)
            self.processed_count += 1

            logger.debug(
                "Event processed successfully",
                event_id=event_id,
                event_type=event_type,
                retry_count=retry_count,
            )

        except Exception as e:
            error_msg = str(e)
            self.failed_count += 1

            # Check if we should send to DLQ
            if retry_count >= self.retry_config.max_retries:
                # Send to dead letter queue
                await self.dead_letter_queue.send_to_dlq(event, error_msg)
                self.dlq_count += 1

                logger.error(
                    "Event sent to dead letter queue after max retries",
                    event_id=event_id,
                    event_type=event_type,
                    error=error_msg,
                    retry_count=retry_count,
                    max_retries=self.retry_config.max_retries,
                )
            else:
                # Schedule for retry with exponential backoff
                retry_delay = self._calculate_retry_delay(retry_count)
                await outbox_repo.mark_event_failed(event_id, error_msg, retry_delay)

                logger.warning(
                    "Event processing failed, will retry",
                    event_id=event_id,
                    event_type=event_type,
                    error=error_msg,
                    retry_count=retry_count,
                    retry_delay=retry_delay,
                    next_retry_at=time.time() + retry_delay,
                )

    def _get_handler(self, event_type: str) -> OutboxEventHandler | None:
        """Get the appropriate handler for an event type"""
        for prefix, handler in self.handlers.items():
            if event_type.startswith(prefix):
                return handler
        return None

    def _get_circuit_breaker(self, event_type: str) -> CircuitBreaker:
        """Get the appropriate circuit breaker for an event type"""
        for prefix, circuit_breaker in self.circuit_breakers.items():
            if event_type.startswith(prefix):
                return circuit_breaker
        # Fallback to a default circuit breaker
        return CircuitBreaker(self.circuit_breaker_config)

    def _calculate_retry_delay(self, retry_count: int) -> int:
        """Calculate exponential backoff delay with optional jitter"""
        import random

        # Exponential backoff: base_delay * (multiplier ^ retry_count)
        delay = min(
            self.retry_config.base_delay
            * (self.retry_config.backoff_multiplier**retry_count),
            self.retry_config.max_delay,
        )

        # Add jitter to prevent thundering herd
        if self.retry_config.jitter:
            jitter = random.uniform(0.8, 1.2)  # ±20% jitter
            delay = int(delay * jitter)

        return int(delay)

    def get_metrics(self) -> dict[str, Any]:
        """Get worker performance metrics"""
        uptime = time.time() - self.start_time

        return {
            "uptime_seconds": uptime,
            "processed_count": self.processed_count,
            "failed_count": self.failed_count,
            "dlq_count": self.dlq_count,
            "success_rate": self.processed_count
            / max(self.processed_count + self.failed_count, 1),
            "events_per_second": self.processed_count / max(uptime, 1),
            "circuit_breakers": {
                prefix: {
                    "state": cb.state,
                    "failure_count": cb.failure_count,
                    "success_count": cb.success_count,
                    "last_failure_time": cb.last_failure_time,
                }
                for prefix, cb in self.circuit_breakers.items()
            },
            "configuration": {
                "batch_size": self.batch_size,
                "max_concurrent": self.max_concurrent,
                "poll_interval": self.poll_interval,
                "max_retries": self.retry_config.max_retries,
                "base_delay": self.retry_config.base_delay,
                "max_delay": self.retry_config.max_delay,
            },
        }

    async def reset_circuit_breaker(self, handler_prefix: str) -> bool:
        """Manually reset a circuit breaker"""
        if handler_prefix in self.circuit_breakers:
            cb = self.circuit_breakers[handler_prefix]
            cb.state = CircuitBreakerState.CLOSED
            cb.failure_count = 0
            cb.success_count = 0
            cb.next_attempt_time = 0

            logger.info("Circuit breaker reset", handler_prefix=handler_prefix)
            return True
        return False

    async def reprocess_dlq_events(
        self, event_types: list[str] | None = None, limit: int = 100
    ) -> int:
        """Reprocess events from dead letter queue"""
        try:
            # Get DLQ events to reprocess
            dlq_events = await outbox_repo.get_dlq_events(event_types, limit)

            reprocessed = 0
            for event in dlq_events:
                success = await self.dead_letter_queue.reprocess_dlq_event(
                    event["event_id"]
                )
                if success:
                    reprocessed += 1

            logger.info(
                "DLQ reprocessing completed",
                total_events=len(dlq_events),
                reprocessed=reprocessed,
            )

            return reprocessed
        except Exception as e:
            logger.error("Error reprocessing DLQ events", error=str(e))
            return 0


class OutboxMonitor:
    """Enhanced outbox health monitoring and alerting"""

    def __init__(self):
        self.alert_thresholds = {
            "max_pending_events": 1000,
            "max_failed_events": 100,
            "max_dlq_events": 10,
            "max_processing_time_minutes": 30,
            "min_success_rate": 0.95,
        }

    async def get_stats(self) -> dict[str, Any]:
        """Get comprehensive outbox processing statistics"""
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

            # Get oldest pending event age
            oldest_pending = await db_manager.fetch_one(
                "SELECT MIN(created_at) as oldest FROM outbox WHERE status = 'pending'"
            )

            oldest_pending_age = None
            if oldest_pending and oldest_pending["oldest"]:
                oldest_pending_age = time.time() - oldest_pending["oldest"]

            # Get failed events count by retry count
            retry_counts = {}
            for i in range(7):  # 0-6 retries
                query = "SELECT COUNT(*) as count FROM outbox WHERE retry_count = ? AND status IN ('failed', 'dead_letter')"
                result = await db_manager.fetch_one(query, (i,))
                retry_counts[f"retry_{i}"] = result["count"] if result else 0

            # Get events by type
            event_type_stats = await db_manager.fetch_all(
                """
                SELECT
                    event_type,
                    status,
                    COUNT(*) as count
                FROM outbox
                GROUP BY event_type, status
            """
            )

            # Get processing rate (events per hour in last 24 hours)
            processing_rate = await db_manager.fetch_one(
                """
                SELECT COUNT(*) as hourly_processed
                FROM outbox
                WHERE status = 'completed'
                AND processed_at > ?
            """,
                (time.time() - 86400,),
            )  # Last 24 hours

            # Calculate health score
            health_score = await self._calculate_health_score(
                status_counts, oldest_pending_age
            )

            # Get stuck events (processing for too long)
            stuck_events = await db_manager.fetch_all(
                """
                SELECT event_id, event_type, created_at, updated_at
                FROM outbox
                WHERE status = 'processing'
                AND updated_at < ?
                ORDER BY updated_at ASC
                LIMIT 10
            """,
                (time.time() - 1800,),
            )  # Stuck for 30+ minutes

            return {
                "status_counts": status_counts,
                "oldest_pending_age_seconds": oldest_pending_age,
                "retry_counts": retry_counts,
                "total_events": sum(status_counts.values()),
                "event_type_stats": event_type_stats,
                "processing_rate_24h": processing_rate["hourly_processed"]
                if processing_rate
                else 0,
                "health_score": health_score,
                "stuck_events": stuck_events,
                "alerts": await self._check_alerts(status_counts, oldest_pending_age),
                "thresholds": self.alert_thresholds,
                "timestamp": time.time(),
            }

        except Exception as e:
            logger.error("Error getting outbox stats", error=str(e), exc_info=True)
            return {"error": str(e), "timestamp": time.time()}

    async def _calculate_health_score(
        self, status_counts: dict[str, int], oldest_pending_age: float | None
    ) -> float:
        """Calculate outbox health score (0-100)"""
        score = 100.0
        total_events = sum(status_counts.values())

        if total_events == 0:
            return score

        # Penalize high failure rate
        failed_ratio = status_counts.get("failed", 0) / total_events
        score -= failed_ratio * 30

        # Penalize DLQ events
        dlq_ratio = status_counts.get("dead_letter", 0) / total_events
        score -= dlq_ratio * 50

        # Penalize old pending events
        if oldest_pending_age and oldest_pending_age > 3600:  # 1 hour
            score -= min(30, oldest_pending_age / 3600 * 10)

        # Penalize too many pending events
        pending_ratio = status_counts.get("pending", 0) / total_events
        if pending_ratio > 0.1:  # More than 10% pending
            score -= (pending_ratio - 0.1) * 100

        return max(0.0, min(100.0, score))

    async def _check_alerts(
        self, status_counts: dict[str, int], oldest_pending_age: float | None
    ) -> list[dict[str, Any]]:
        """Check for alert conditions"""
        alerts = []

        # Too many pending events
        if (
            status_counts.get("pending", 0)
            > self.alert_thresholds["max_pending_events"]
        ):
            alerts.append(
                {
                    "type": "high_pending_events",
                    "severity": "warning",
                    "message": f"High number of pending events: {status_counts['pending']}",
                    "value": status_counts["pending"],
                    "threshold": self.alert_thresholds["max_pending_events"],
                }
            )

        # Too many failed events
        if status_counts.get("failed", 0) > self.alert_thresholds["max_failed_events"]:
            alerts.append(
                {
                    "type": "high_failed_events",
                    "severity": "error",
                    "message": f"High number of failed events: {status_counts['failed']}",
                    "value": status_counts["failed"],
                    "threshold": self.alert_thresholds["max_failed_events"],
                }
            )

        # DLQ events present
        if (
            status_counts.get("dead_letter", 0)
            > self.alert_thresholds["max_dlq_events"]
        ):
            alerts.append(
                {
                    "type": "dead_letter_events",
                    "severity": "critical",
                    "message": f"Events in dead letter queue: {status_counts['dead_letter']}",
                    "value": status_counts["dead_letter"],
                    "threshold": self.alert_thresholds["max_dlq_events"],
                }
            )

        # Old pending events
        if oldest_pending_age and oldest_pending_age > (
            self.alert_thresholds["max_processing_time_minutes"] * 60
        ):
            alerts.append(
                {
                    "type": "stale_pending_events",
                    "severity": "warning",
                    "message": f"Oldest pending event is {oldest_pending_age / 60:.1f} minutes old",
                    "value": oldest_pending_age,
                    "threshold": self.alert_thresholds["max_processing_time_minutes"]
                    * 60,
                }
            )

        return alerts

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


async def get_worker_metrics() -> dict[str, Any]:
    """Get worker performance metrics"""
    return outbox_worker.get_metrics()


async def reset_circuit_breaker(handler_prefix: str) -> bool:
    """Reset a circuit breaker manually"""
    return await outbox_worker.reset_circuit_breaker(handler_prefix)


async def reprocess_dead_letter_events(
    event_types: list[str] | None = None, limit: int = 100
) -> int:
    """Reprocess events from the dead letter queue"""
    return await outbox_worker.reprocess_dlq_events(event_types, limit)


async def get_health_check() -> dict[str, Any]:
    """Get a comprehensive health check of the outbox system"""
    try:
        stats = await get_outbox_stats()
        worker_metrics = await get_worker_metrics()

        health_score = stats.get("health_score", 0)
        alerts = stats.get("alerts", [])

        # Determine overall health status
        if health_score >= 90 and len(alerts) == 0:
            status = "healthy"
        elif health_score >= 70 and not any(
            alert["severity"] == "critical" for alert in alerts
        ):
            status = "degraded"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "health_score": health_score,
            "alerts": alerts,
            "worker_running": outbox_worker.running,
            "worker_metrics": worker_metrics,
            "outbox_stats": stats,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error("Error getting health check", error=str(e))
        return {"status": "error", "error": str(e), "timestamp": time.time()}
