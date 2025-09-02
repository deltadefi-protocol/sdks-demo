"""
Quote-to-Order Pipeline

This module implements the complete pipeline from quote generation to order submission:
- Connects quote engine to OMS
- Persists quotes to database
- Generates orders from quotes
- Manages quote lifecycle
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import json
import time
from typing import Any
import uuid

import structlog

from bot.config import settings
from bot.db.repo import outbox_repo
from bot.db.sqlite import db_manager
from bot.deltadefi import DeltaDeFiClient
from bot.oms import OMSOrder, OrderManagementSystem, OrderSide, OrderState
from bot.oms import OrderType as OMSOrderType
from bot.quote import Quote
from bot.rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger()


class QuoteStatus(str, Enum):
    """Quote lifecycle status"""

    GENERATED = "generated"
    PERSISTED = "persisted"
    ORDERS_CREATED = "orders_created"
    ORDERS_SUBMITTED = "orders_submitted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class QuoteStrategy(str, Enum):
    """Quote generation strategies"""

    MARKET_MAKING = "market_making"
    ARBITRAGE = "arbitrage"
    MOMENTUM = "momentum"


@dataclass
class PersistentQuote:
    """Enhanced quote with persistence and lifecycle tracking"""

    id: int | None = None
    quote_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    symbol_src: str = ""  # Source symbol (e.g., ADAUSDT)
    symbol_dst: str = ""  # Destination symbol (e.g., ADAUSDM)

    # Source market data
    source_bid_price: Decimal = Decimal("0")
    source_bid_qty: Decimal = Decimal("0")
    source_ask_price: Decimal = Decimal("0")
    source_ask_qty: Decimal = Decimal("0")

    # Generated quote
    bid_price: Decimal | None = None
    bid_qty: Decimal | None = None
    ask_price: Decimal | None = None
    ask_qty: Decimal | None = None

    # Metadata
    spread_bps: Decimal | None = None
    mid_price: Decimal | None = None
    total_spread_bps: int = 0
    sides_enabled: list[str] = field(default_factory=list)
    strategy: QuoteStrategy = QuoteStrategy.MARKET_MAKING
    status: QuoteStatus = QuoteStatus.GENERATED

    # Lifecycle tracking
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    # Order references
    bid_order_id: str | None = None
    ask_order_id: str | None = None

    @classmethod
    def from_quote(
        cls, quote: Quote, strategy: QuoteStrategy = QuoteStrategy.MARKET_MAKING
    ) -> "PersistentQuote":
        """Create PersistentQuote from Quote engine output"""
        # Set expiry based on settings
        expires_at = time.time() + (settings.trading.stale_ms / 1000.0)

        return cls(
            symbol_src=quote.source_data.symbol,
            symbol_dst=quote.symbol,
            source_bid_price=Decimal(str(quote.source_data.bid_price)),
            source_bid_qty=Decimal(str(quote.source_data.bid_qty)),
            source_ask_price=Decimal(str(quote.source_data.ask_price)),
            source_ask_qty=Decimal(str(quote.source_data.ask_qty)),
            bid_price=Decimal(str(quote.bid_price)) if quote.bid_price else None,
            bid_qty=Decimal(str(quote.bid_qty)) if quote.bid_qty else None,
            ask_price=Decimal(str(quote.ask_price)) if quote.ask_price else None,
            ask_qty=Decimal(str(quote.ask_qty)) if quote.ask_qty else None,
            spread_bps=Decimal(str(quote.spread_bps)) if quote.spread_bps else None,
            mid_price=Decimal(str((quote.bid_price + quote.ask_price) / 2))
            if quote.bid_price and quote.ask_price
            else None,
            total_spread_bps=settings.total_spread_bps,
            sides_enabled=settings.trading.side_enable.copy(),
            strategy=strategy,
            expires_at=expires_at,
            timestamp=quote.timestamp,
        )

    @property
    def is_expired(self) -> bool:
        """Check if quote has expired"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def has_bid(self) -> bool:
        """Check if quote has valid bid"""
        return (
            self.bid_price is not None and self.bid_qty is not None and self.bid_qty > 0
        )

    @property
    def has_ask(self) -> bool:
        """Check if quote has valid ask"""
        return (
            self.ask_price is not None and self.ask_qty is not None and self.ask_qty > 0
        )


class QuoteRepository:
    """Repository for quote persistence"""

    async def save_quote(self, quote: PersistentQuote) -> int:
        """Save quote to database and return ID"""
        query = """
        INSERT INTO quotes (
            quote_id, timestamp, symbol_src, symbol_dst,
            source_bid_price, source_bid_qty, source_ask_price, source_ask_qty,
            bid_price, bid_qty, ask_price, ask_qty,
            spread_bps, mid_price, total_spread_bps, sides_enabled,
            strategy, status, created_at, updated_at, expires_at,
            bid_order_id, ask_order_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        async with db_manager.get_connection() as conn:
            cursor = await conn.execute(
                query,
                (
                    quote.quote_id,
                    quote.timestamp,
                    quote.symbol_src,
                    quote.symbol_dst,
                    float(quote.source_bid_price),
                    float(quote.source_bid_qty),
                    float(quote.source_ask_price),
                    float(quote.source_ask_qty),
                    float(quote.bid_price) if quote.bid_price else None,
                    float(quote.bid_qty) if quote.bid_qty else None,
                    float(quote.ask_price) if quote.ask_price else None,
                    float(quote.ask_qty) if quote.ask_qty else None,
                    float(quote.spread_bps) if quote.spread_bps else None,
                    float(quote.mid_price) if quote.mid_price else None,
                    quote.total_spread_bps,
                    json.dumps(quote.sides_enabled),
                    quote.strategy,
                    quote.status,
                    quote.created_at,
                    quote.updated_at,
                    quote.expires_at,
                    quote.bid_order_id,
                    quote.ask_order_id,
                ),
            )

            quote_id = cursor.lastrowid
            await conn.commit()

            quote.id = quote_id
            return quote_id

    async def update_quote_status(
        self, quote_id: str, status: QuoteStatus, **kwargs
    ) -> None:
        """Update quote status and optional fields"""
        set_clause = "status = ?, updated_at = ?"
        params = [status, time.time()]

        for field_name, value in kwargs.items():
            if field_name in ["bid_order_id", "ask_order_id", "expires_at"]:
                set_clause += f", {field_name} = ?"
                params.append(value)

        query = f"UPDATE quotes SET {set_clause} WHERE quote_id = ?"
        params.append(quote_id)

        async with db_manager.get_connection() as conn:
            await conn.execute(query, params)
            await conn.commit()

    async def get_quote(self, quote_id: str) -> PersistentQuote | None:
        """Get quote by ID"""
        query = "SELECT * FROM quotes WHERE quote_id = ?"
        result = await db_manager.fetch_one(query, (quote_id,))

        if not result:
            return None

        return self._row_to_quote(result)

    async def get_active_quotes(self, symbol_dst: str) -> list[PersistentQuote]:
        """Get active quotes for a symbol"""
        query = """
        SELECT * FROM quotes
        WHERE symbol_dst = ?
        AND status IN ('persisted', 'orders_created', 'orders_submitted')
        AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY created_at DESC
        """

        results = await db_manager.fetch_all(query, (symbol_dst, time.time()))
        return [self._row_to_quote(row) for row in results]

    async def expire_old_quotes(self, symbol_dst: str | None = None) -> int:
        """Mark expired quotes as expired"""
        where_clause = "WHERE expires_at IS NOT NULL AND expires_at <= ?"
        params = [time.time()]

        if symbol_dst:
            where_clause += " AND symbol_dst = ?"
            params.append(symbol_dst)

        query = f"""
        UPDATE quotes
        SET status = 'expired', updated_at = ?
        {where_clause}
        AND status NOT IN ('expired', 'cancelled')
        """

        params.insert(0, time.time())  # updated_at

        async with db_manager.get_connection() as conn:
            cursor = await conn.execute(query, params)
            count = cursor.rowcount
            await conn.commit()
            return count

    def _row_to_quote(self, row: dict) -> PersistentQuote:
        """Convert database row to PersistentQuote"""
        return PersistentQuote(
            id=row["id"],
            quote_id=row["quote_id"],
            timestamp=row["timestamp"],
            symbol_src=row["symbol_src"],
            symbol_dst=row["symbol_dst"],
            source_bid_price=Decimal(str(row["source_bid_price"])),
            source_bid_qty=Decimal(str(row["source_bid_qty"])),
            source_ask_price=Decimal(str(row["source_ask_price"])),
            source_ask_qty=Decimal(str(row["source_ask_qty"])),
            bid_price=Decimal(str(row["bid_price"])) if row["bid_price"] else None,
            bid_qty=Decimal(str(row["bid_qty"])) if row["bid_qty"] else None,
            ask_price=Decimal(str(row["ask_price"])) if row["ask_price"] else None,
            ask_qty=Decimal(str(row["ask_qty"])) if row["ask_qty"] else None,
            spread_bps=Decimal(str(row["spread_bps"])) if row["spread_bps"] else None,
            mid_price=Decimal(str(row["mid_price"])) if row["mid_price"] else None,
            total_spread_bps=row["total_spread_bps"],
            sides_enabled=json.loads(row["sides_enabled"]),
            strategy=QuoteStrategy(row["strategy"]),
            status=QuoteStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            bid_order_id=row["bid_order_id"],
            ask_order_id=row["ask_order_id"],
        )


class QuoteToOrderPipeline:
    """
    Main pipeline that orchestrates quote generation, persistence, and order creation
    """

    def __init__(
        self,
        oms: OrderManagementSystem,
        deltadefi_client: DeltaDeFiClient,
        rate_limiter: TokenBucketRateLimiter | None = None,
    ):
        self.oms = oms
        self.deltadefi_client = deltadefi_client
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()

        self.quote_repo = QuoteRepository()

        # Callbacks for pipeline events
        self.quote_callbacks: list[Callable] = []
        self.order_callbacks: list[Callable] = []

        # Metrics
        self.quotes_processed = 0
        self.quotes_expired = 0
        self.orders_generated = 0
        self.orders_submitted = 0
        self.orders_failed = 0

        # Pipeline state
        self.active_quotes: dict[str, PersistentQuote] = {}
        self.running = False

        logger.info("Quote-to-Order pipeline initialized")

    def add_quote_callback(self, callback: Callable):
        """Add callback for quote events"""
        self.quote_callbacks.append(callback)

    def add_order_callback(self, callback: Callable):
        """Add callback for order events"""
        self.order_callbacks.append(callback)

    async def start(self):
        """Start the pipeline"""
        self.running = True

        # Register OMS callbacks
        self.oms.add_order_callback(self._on_order_update)

        logger.info("Quote-to-Order pipeline started")

    async def stop(self):
        """Stop the pipeline"""
        self.running = False

        # Cancel active quotes (create a copy to avoid dictionary size change during iteration)
        active_quotes_copy = list(self.active_quotes.values())
        for quote in active_quotes_copy:
            await self._cancel_quote(quote)

        self.active_quotes.clear()

        logger.info("Quote-to-Order pipeline stopped")

    async def process_quote(
        self, quote: Quote, strategy: QuoteStrategy = QuoteStrategy.MARKET_MAKING
    ) -> PersistentQuote:
        """
        Main entry point: process a quote through the complete pipeline
        
        Implements active order replacement - cancels existing orders before submitting new ones

        Args:
            quote: Quote from the quote engine
            strategy: Trading strategy for this quote

        Returns:
            PersistentQuote: The processed quote
        """
        if not self.running:
            raise RuntimeError("Pipeline is not running")

        # Convert to persistent quote
        persistent_quote = PersistentQuote.from_quote(quote, strategy)

        try:
            # Step 0: Cancel existing active quotes/orders for this symbol (ORDER REPLACEMENT)
            cancelled_count = await self.cancel_active_quotes_for_symbol(persistent_quote.symbol_dst)
            
            # Verify OMS order count after cancellation
            current_order_count = self.oms.risk_manager.open_order_count if self.oms else 0
            max_orders = settings.risk.max_open_orders
            
            if cancelled_count > 0:
                logger.info(
                    "Order replacement: cancelled existing quotes",
                    symbol=persistent_quote.symbol_dst,
                    cancelled_quotes=cancelled_count,
                    new_quote_id=persistent_quote.quote_id,
                    order_count_after_cancel=current_order_count,
                    max_orders=max_orders
                )
            
            # Safety check: ensure we have room for new orders
            orders_to_create = len([s for s in settings.trading.side_enable if s in ["bid", "ask"]])
            if current_order_count + orders_to_create > max_orders:
                raise ValueError(
                    f"Cannot create {orders_to_create} new orders: would exceed limit "
                    f"({current_order_count} + {orders_to_create} > {max_orders}). "
                    f"Order replacement may have failed."
                )

            # Step 1: Persist quote to database
            await self._persist_quote(persistent_quote)

            # Step 2: Generate and submit orders
            await self._generate_orders(persistent_quote)

            # Step 3: Track active quote
            self.active_quotes[persistent_quote.quote_id] = persistent_quote
            
            # Step 4: Validate we only have one active quote per symbol (safety check)
            active_for_symbol = [q for q in self.active_quotes.values() if q.symbol_dst == persistent_quote.symbol_dst]
            if len(active_for_symbol) > 1:
                logger.warning(
                    "Multiple active quotes detected for symbol - this should not happen with order replacement",
                    symbol=persistent_quote.symbol_dst,
                    active_count=len(active_for_symbol),
                    quote_ids=[q.quote_id for q in active_for_symbol]
                )

            self.quotes_processed += 1

            logger.info(
                "Quote processed successfully with order replacement",
                quote_id=persistent_quote.quote_id,
                symbol=persistent_quote.symbol_dst,
                strategy=strategy,
                has_bid=persistent_quote.has_bid,
                has_ask=persistent_quote.has_ask,
                replaced_quotes=cancelled_count,
            )

            # Notify callbacks
            await self._notify_quote_callbacks(persistent_quote)

            return persistent_quote

        except Exception as e:
            logger.error(
                "Quote processing failed",
                quote_id=persistent_quote.quote_id,
                error=str(e),
                exc_info=True,
            )

            # Mark as failed
            persistent_quote.status = QuoteStatus.CANCELLED
            if persistent_quote.id:
                await self.quote_repo.update_quote_status(
                    persistent_quote.quote_id, QuoteStatus.CANCELLED
                )

            raise

    async def _persist_quote(self, quote: PersistentQuote):
        """Persist quote to database"""
        try:
            quote_id = await self.quote_repo.save_quote(quote)
            quote.status = QuoteStatus.PERSISTED

            logger.debug("Quote persisted", quote_id=quote.quote_id, db_id=quote_id)

            # Publish outbox event
            await outbox_repo.add_event(
                event_type="quote_persisted",
                aggregate_id=quote.quote_id,
                payload={
                    "quote_id": quote.quote_id,
                    "symbol_dst": quote.symbol_dst,
                    "strategy": quote.strategy,
                    "bid_price": float(quote.bid_price) if quote.bid_price else None,
                    "ask_price": float(quote.ask_price) if quote.ask_price else None,
                    "timestamp": quote.timestamp,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to persist quote", quote_id=quote.quote_id, error=str(e)
            )
            raise

    async def _generate_orders(self, quote: PersistentQuote):
        """Generate and submit orders from quote"""
        orders_created = []

        try:
            # Generate bid order if enabled and valid
            if quote.has_bid and "bid" in quote.sides_enabled:
                bid_order = await self._create_order(
                    quote, OrderSide.BUY, quote.bid_price, quote.bid_qty
                )
                orders_created.append(bid_order)
                quote.bid_order_id = bid_order.order_id

            # Generate ask order if enabled and valid
            if quote.has_ask and "ask" in quote.sides_enabled:
                ask_order = await self._create_order(
                    quote, OrderSide.SELL, quote.ask_price, quote.ask_qty
                )
                orders_created.append(ask_order)
                quote.ask_order_id = ask_order.order_id

            if orders_created:
                quote.status = QuoteStatus.ORDERS_CREATED
                await self.quote_repo.update_quote_status(
                    quote.quote_id,
                    QuoteStatus.ORDERS_CREATED,
                    bid_order_id=quote.bid_order_id,
                    ask_order_id=quote.ask_order_id,
                )

                self.orders_generated += len(orders_created)

                logger.info(
                    "Orders generated from quote",
                    quote_id=quote.quote_id,
                    orders_count=len(orders_created),
                    bid_order=quote.bid_order_id,
                    ask_order=quote.ask_order_id,
                )

                # Submit orders to exchange
                await self._submit_orders(quote, orders_created)
            else:
                logger.warning(
                    "No orders generated from quote",
                    quote_id=quote.quote_id,
                    has_bid=quote.has_bid,
                    has_ask=quote.has_ask,
                    sides_enabled=quote.sides_enabled,
                )

        except Exception:
            # Cancel any orders that were created
            for order in orders_created:
                try:
                    await self.oms.cancel_order(
                        order.order_id, "Quote processing failed"
                    )
                except Exception:
                    pass  # Best effort cleanup

            raise

    async def _create_order(
        self, quote: PersistentQuote, side: OrderSide, price: Decimal, quantity: Decimal
    ) -> OMSOrder:
        """Create order through OMS"""
        try:
            order = await self.oms.submit_order(
                symbol=quote.symbol_dst,
                side=side,
                order_type=OMSOrderType.LIMIT,
                quantity=quantity,
                price=price,
            )

            logger.debug(
                "Order created in OMS",
                order_id=order.order_id,
                quote_id=quote.quote_id,
                side=side,
                price=price,
                quantity=quantity,
            )

            return order

        except Exception as e:
            logger.error(
                "Failed to create order in OMS",
                quote_id=quote.quote_id,
                side=side,
                price=price,
                quantity=quantity,
                error=str(e),
            )
            raise

    async def _submit_orders(self, quote: PersistentQuote, orders: list[OMSOrder]):
        """Submit orders to DeltaDeFi exchange"""
        submitted_count = 0

        for order in orders:
            try:
                await self.rate_limiter.wait_for_token()

                # Convert OMS order to DeltaDeFi format
                # Round quantity to integer for DeltaDeFi (should be close to integer for our sizing)
                quantity_int = round(float(order.quantity))
                
                logger.debug(
                    "Submitting order to DeltaDeFi",
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity_original=float(order.quantity),
                    quantity_rounded=quantity_int,
                    price=float(order.price) if order.price else None,
                )
                
                result = await self.deltadefi_client.submit_order(
                    symbol=order.symbol,
                    side=order.side.value,
                    order_type=order.order_type.value,
                    quantity=quantity_int,
                    price=float(order.price) if order.price else None,
                )

                # Update order state

                await self.oms.update_order_state(
                    order.order_id,
                    OrderState.WORKING,
                    external_order_id=str(result.get("order_id")),
                )

                submitted_count += 1
                self.orders_submitted += 1

                logger.info(
                    "Order submitted to DeltaDeFi",
                    order_id=order.order_id,
                    quote_id=quote.quote_id,
                    external_order_id=result.get("order_id"),
                    symbol=order.symbol,
                    side=order.side,
                )

            except Exception as e:
                self.orders_failed += 1

                # Update order state to failed
                await self.oms.update_order_state(
                    order.order_id, OrderState.FAILED, error_message=str(e)
                )

                logger.error(
                    "Failed to submit order",
                    order_id=order.order_id,
                    quote_id=quote.quote_id,
                    error=str(e),
                )

        if submitted_count > 0:
            quote.status = QuoteStatus.ORDERS_SUBMITTED
            await self.quote_repo.update_quote_status(
                quote.quote_id, QuoteStatus.ORDERS_SUBMITTED
            )

            logger.info(
                "Orders submitted for quote",
                quote_id=quote.quote_id,
                submitted=submitted_count,
                total=len(orders),
            )

    async def _cancel_quote(self, quote: PersistentQuote):
        """Cancel a quote and its associated orders"""
        cancelled_orders = []
        
        try:
            # Get OMS order count before cancellation for verification
            initial_order_count = self.oms.risk_manager.open_order_count if self.oms else 0
            
            # Cancel orders in OMS
            if quote.bid_order_id:
                await self.oms.cancel_order(quote.bid_order_id, "Quote cancelled")
                cancelled_orders.append(quote.bid_order_id)
            if quote.ask_order_id:
                await self.oms.cancel_order(quote.ask_order_id, "Quote cancelled")  
                cancelled_orders.append(quote.ask_order_id)

            # Verify order count decreased properly
            final_order_count = self.oms.risk_manager.open_order_count if self.oms else 0
            expected_decrease = len(cancelled_orders)
            actual_decrease = initial_order_count - final_order_count
            
            if actual_decrease != expected_decrease:
                logger.warning(
                    "Order count mismatch after cancellation",
                    quote_id=quote.quote_id,
                    expected_decrease=expected_decrease,
                    actual_decrease=actual_decrease,
                    initial_count=initial_order_count,
                    final_count=final_order_count,
                    cancelled_orders=cancelled_orders
                )

            # Update quote status
            quote.status = QuoteStatus.CANCELLED
            await self.quote_repo.update_quote_status(
                quote.quote_id, QuoteStatus.CANCELLED
            )

            logger.info(
                "Quote cancelled successfully", 
                quote_id=quote.quote_id,
                cancelled_orders=cancelled_orders,
                order_count_before=initial_order_count,
                order_count_after=final_order_count
            )

        except Exception as e:
            logger.error(
                "Error cancelling quote", 
                quote_id=quote.quote_id, 
                error=str(e),
                cancelled_orders=cancelled_orders
            )

    async def _on_order_update(self, order: OMSOrder):
        """Handle order updates from OMS"""
        # Find the quote associated with this order
        quote = None
        for q in self.active_quotes.values():
            if q.bid_order_id == order.order_id or q.ask_order_id == order.order_id:
                quote = q
                break

        if not quote:
            return  # Order not from this pipeline

        # Handle order completion
        if order.is_complete:
            # Check if all orders for this quote are complete
            all_complete = True
            if quote.bid_order_id:
                bid_order = self.oms.get_order(quote.bid_order_id)
                all_complete = all_complete and (
                    bid_order is None or bid_order.is_complete
                )
            if quote.ask_order_id:
                ask_order = self.oms.get_order(quote.ask_order_id)
                all_complete = all_complete and (
                    ask_order is None or ask_order.is_complete
                )

            # If all orders complete, remove from active quotes
            if all_complete:
                self.active_quotes.pop(quote.quote_id, None)

                logger.debug(
                    "Quote completed, removed from active tracking",
                    quote_id=quote.quote_id,
                    order_id=order.order_id,
                    order_status=order.state,
                )

        # Notify callbacks
        await self._notify_order_callbacks(order)

    async def cancel_active_quotes_for_symbol(self, symbol_dst: str) -> int:
        """Cancel all active quotes and their orders for a specific symbol
        
        This is used for order replacement - cancel existing orders before submitting new ones
        """
        cancelled_count = 0
        
        try:
            # Get initial state for verification
            initial_active_count = len(self.active_quotes)
            initial_order_count = self.oms.risk_manager.open_order_count if self.oms else 0
            
            # Find all active quotes for this symbol
            quotes_to_cancel = []
            for quote_id, quote in list(self.active_quotes.items()):
                if quote.symbol_dst == symbol_dst and quote.status in [
                    QuoteStatus.PERSISTED, QuoteStatus.ORDERS_CREATED, QuoteStatus.ORDERS_SUBMITTED
                ]:
                    quotes_to_cancel.append(quote)
            
            if quotes_to_cancel:
                logger.info(
                    "Starting order replacement cancellation",
                    symbol=symbol_dst,
                    quotes_to_cancel=len(quotes_to_cancel),
                    quote_ids=[q.quote_id for q in quotes_to_cancel],
                    initial_active_quotes=initial_active_count,
                    initial_order_count=initial_order_count
                )
            
            # Cancel each quote and its orders
            for quote in quotes_to_cancel:
                await self._cancel_quote(quote)
                self.active_quotes.pop(quote.quote_id, None)
                cancelled_count += 1
            
            # Verify final state
            final_active_count = len(self.active_quotes)
            final_order_count = self.oms.risk_manager.open_order_count if self.oms else 0
            
            if cancelled_count > 0:
                logger.info(
                    "Order replacement cancellation completed",
                    symbol=symbol_dst,
                    cancelled_count=cancelled_count,
                    active_quotes_before=initial_active_count,
                    active_quotes_after=final_active_count,
                    order_count_before=initial_order_count,
                    order_count_after=final_order_count,
                    orders_freed=initial_order_count - final_order_count
                )
            else:
                logger.debug(
                    "No active quotes found to cancel for symbol",
                    symbol=symbol_dst,
                    current_active_quotes=final_active_count
                )
            
            return cancelled_count
            
        except Exception as e:
            logger.error("Error cancelling active quotes", symbol=symbol_dst, error=str(e))
            return cancelled_count

    async def cleanup_expired_quotes(self) -> int:
        """Clean up expired quotes"""
        expired_count = 0

        try:
            # Mark expired quotes in database
            db_expired = await self.quote_repo.expire_old_quotes()

            # Cancel active expired quotes
            expired_quote_ids = []
            for quote_id, quote in list(self.active_quotes.items()):
                if quote.is_expired:
                    await self._cancel_quote(quote)
                    expired_quote_ids.append(quote_id)
                    expired_count += 1

            # Remove from active tracking
            for quote_id in expired_quote_ids:
                self.active_quotes.pop(quote_id, None)

            self.quotes_expired += expired_count

            if expired_count > 0:
                logger.info(
                    "Cleaned up expired quotes",
                    active_expired=expired_count,
                    db_expired=db_expired,
                    total_active=len(self.active_quotes),
                )

            return expired_count + db_expired

        except Exception as e:
            logger.error("Error cleaning up expired quotes", error=str(e))
            return expired_count

    async def get_pipeline_stats(self) -> dict[str, Any]:
        """Get pipeline performance statistics"""
        # Count active quotes per symbol
        quotes_by_symbol = {}
        for quote in self.active_quotes.values():
            symbol = quote.symbol_dst
            quotes_by_symbol[symbol] = quotes_by_symbol.get(symbol, 0) + 1
        
        return {
            "running": self.running,
            "quotes_processed": self.quotes_processed,
            "quotes_expired": self.quotes_expired,
            "orders_generated": self.orders_generated,
            "orders_submitted": self.orders_submitted,
            "orders_failed": self.orders_failed,
            "active_quotes_count": len(self.active_quotes),
            "active_quotes_by_symbol": quotes_by_symbol,  # New field for monitoring
            "active_quotes": [
                {
                    "quote_id": q.quote_id,
                    "symbol": q.symbol_dst,
                    "status": q.status,
                    "created_at": q.created_at,
                    "expires_at": q.expires_at,
                    "bid_order_id": q.bid_order_id,
                    "ask_order_id": q.ask_order_id,
                }
                for q in self.active_quotes.values()
            ],
            "success_rate": self.orders_submitted / max(self.orders_generated, 1),
            "failure_rate": self.orders_failed / max(self.orders_generated, 1),
        }

    async def _notify_quote_callbacks(self, quote: PersistentQuote):
        """Notify quote callbacks"""
        for callback in self.quote_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(quote)
                else:
                    callback(quote)
            except Exception as e:
                logger.error(
                    "Error in quote callback", callback=callback.__name__, error=str(e)
                )

    async def _notify_order_callbacks(self, order: OMSOrder):
        """Notify order callbacks"""
        for callback in self.order_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(order)
                else:
                    callback(order)
            except Exception as e:
                logger.error(
                    "Error in order callback", callback=callback.__name__, error=str(e)
                )
