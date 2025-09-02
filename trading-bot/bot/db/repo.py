"""
Repository layer for database operations

Provides high-level data access methods for the trading bot's core entities.
Uses the outbox pattern for reliable event publishing.
"""

import json
from typing import Any
import uuid

import structlog

from .sqlite import db_manager

logger = structlog.get_logger()


class QuoteRepository:
    """Repository for quote-related database operations"""

    async def create_quote(self, quote_data: dict[str, Any]) -> int:
        """Create a new quote record"""
        query = """
        INSERT INTO quotes (
            timestamp, symbol_src, symbol_dst,
            source_bid_price, source_bid_qty, source_ask_price, source_ask_qty,
            bid_price, bid_qty, ask_price, ask_qty,
            spread_bps, mid_price, total_spread_bps, sides_enabled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            quote_data["timestamp"],
            quote_data["symbol_src"],
            quote_data["symbol_dst"],
            quote_data["source_bid_price"],
            quote_data["source_bid_qty"],
            quote_data["source_ask_price"],
            quote_data["source_ask_qty"],
            quote_data.get("bid_price"),
            quote_data.get("bid_qty"),
            quote_data.get("ask_price"),
            quote_data.get("ask_qty"),
            quote_data.get("spread_bps"),
            quote_data.get("mid_price"),
            quote_data["total_spread_bps"],
            json.dumps(quote_data["sides_enabled"]),
        )

        quote_id = await db_manager.execute(query, params)
        logger.info(
            "Created quote record", quote_id=quote_id, symbol=quote_data["symbol_dst"]
        )
        return quote_id

    async def get_recent_quotes(
        self, symbol_dst: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get recent quotes for a symbol"""
        query = """
        SELECT * FROM quotes
        WHERE symbol_dst = ?
        ORDER BY created_at DESC
        LIMIT ?
        """

        rows = await db_manager.fetch_all(query, (symbol_dst, limit))
        return [dict(row) for row in rows]


class OrderRepository:
    """Repository for order-related database operations"""

    async def create_order(self, order_data: dict[str, Any]) -> int:
        """Create a new order record"""
        query = """
        INSERT INTO orders (
            order_id, quote_id, symbol, side, order_type, price, quantity, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            order_data["order_id"],
            order_data.get("quote_id"),
            order_data["symbol"],
            order_data["side"],
            order_data["order_type"],
            order_data.get("price"),
            order_data["quantity"],
            order_data.get("status", "pending"),
        )

        order_id = await db_manager.execute(query, params)

        # Publish order created event to outbox
        await self._publish_order_event(
            "order_created", order_data["order_id"], order_data
        )

        logger.info(
            "Created order record",
            order_id=order_id,
            client_order_id=order_data["order_id"],
        )
        return order_id

    async def update_order_status(
        self,
        order_id: str,
        status: str,
        deltadefi_order_id: str | None = None,
        tx_hex: str | None = None,
        signed_tx: str | None = None,
        tx_hash: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update order status and related fields"""

        # Build dynamic update query
        updates = ["status = ?", "last_updated = unixepoch()"]
        params = [status]

        if deltadefi_order_id:
            updates.append("deltadefi_order_id = ?")
            params.append(deltadefi_order_id)

        if tx_hex:
            updates.append("tx_hex = ?")
            params.append(tx_hex)

        if signed_tx:
            updates.append("signed_tx = ?")
            params.append(signed_tx)

        if tx_hash:
            updates.append("tx_hash = ?")
            params.append(tx_hash)

        if error_message:
            updates.append("error_message = ?")
            params.append(error_message)

        if status == "submitted":
            updates.append("submitted_at = unixepoch()")

        params.append(order_id)  # WHERE clause

        query = f"UPDATE orders SET {', '.join(updates)} WHERE order_id = ?"
        await db_manager.execute(query, tuple(params))

        # Publish order status event
        await self._publish_order_event(
            "order_status_updated",
            order_id,
            {
                "status": status,
                "deltadefi_order_id": deltadefi_order_id,
                "tx_hash": tx_hash,
                "error_message": error_message,
            },
        )

        logger.info(
            "Updated order status",
            order_id=order_id,
            status=status,
            deltadefi_order_id=deltadefi_order_id,
        )

    async def update_order_fill(
        self, order_id: str, filled_quantity: float, avg_fill_price: float | None = None
    ) -> None:
        """Update order fill information"""
        query = """
        UPDATE orders
        SET filled_quantity = ?, avg_fill_price = ?, last_updated = unixepoch()
        WHERE order_id = ?
        """

        await db_manager.execute(query, (filled_quantity, avg_fill_price, order_id))

        # Publish fill event
        await self._publish_order_event(
            "order_filled",
            order_id,
            {"filled_quantity": filled_quantity, "avg_fill_price": avg_fill_price},
        )

        logger.info(
            "Updated order fill",
            order_id=order_id,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
        )

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Get order by client order ID"""
        query = "SELECT * FROM orders WHERE order_id = ?"
        row = await db_manager.fetch_one(query, (order_id,))
        return dict(row) if row else None

    async def get_active_orders(
        self, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all active orders"""
        query = "SELECT * FROM v_active_orders"
        params = ()

        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)

        rows = await db_manager.fetch_all(query, params)
        return [dict(row) for row in rows]

    async def _publish_order_event(
        self, event_type: str, order_id: str, payload: dict[str, Any]
    ) -> None:
        """Publish order event to outbox"""
        event_id = str(uuid.uuid4())

        query = """
        INSERT INTO outbox (event_id, event_type, aggregate_id, payload)
        VALUES (?, ?, ?, ?)
        """

        await db_manager.execute(
            query, (event_id, event_type, order_id, json.dumps(payload))
        )


class FillRepository:
    """Repository for fill/execution related operations"""

    async def create_fill(self, fill_data: dict[str, Any]) -> int:
        """Create a new fill record"""
        query = """
        INSERT INTO fills (
            fill_id, order_id, symbol, side, price, quantity,
            executed_at, trade_id, commission, commission_asset, is_maker
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            fill_data["fill_id"],
            fill_data["order_id"],
            fill_data["symbol"],
            fill_data["side"],
            fill_data["price"],
            fill_data["quantity"],
            fill_data["executed_at"],
            fill_data.get("trade_id"),
            fill_data.get("commission", 0),
            fill_data.get("commission_asset"),
            fill_data.get("is_maker", True),
        )

        fill_id = await db_manager.execute(query, params)

        # Publish fill event
        await self._publish_fill_event("fill_created", fill_data["order_id"], fill_data)

        logger.info(
            "Created fill record",
            fill_id=fill_id,
            order_id=fill_data["order_id"],
            quantity=fill_data["quantity"],
        )
        return fill_id

    async def get_fills_for_order(self, order_id: str) -> list[dict[str, Any]]:
        """Get all fills for an order"""
        query = "SELECT * FROM fills WHERE order_id = ? ORDER BY executed_at"
        rows = await db_manager.fetch_all(query, (order_id,))
        return [dict(row) for row in rows]

    async def get_recent_fills(
        self, symbol: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get recent fills"""
        query = "SELECT * FROM fills"
        params = ()

        if symbol:
            query += " WHERE symbol = ?"
            params = (symbol,)

        query += " ORDER BY executed_at DESC LIMIT ?"
        params = (*params, limit)

        rows = await db_manager.fetch_all(query, params)
        return [dict(row) for row in rows]

    async def _publish_fill_event(
        self, event_type: str, order_id: str, payload: dict[str, Any]
    ) -> None:
        """Publish fill event to outbox"""
        event_id = str(uuid.uuid4())

        query = """
        INSERT INTO outbox (event_id, event_type, aggregate_id, payload)
        VALUES (?, ?, ?, ?)
        """

        await db_manager.execute(
            query, (event_id, event_type, order_id, json.dumps(payload))
        )


class PositionRepository:
    """Repository for position tracking"""

    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        """Get current position for symbol"""
        query = "SELECT * FROM positions WHERE symbol = ?"
        row = await db_manager.fetch_one(query, (symbol,))
        return dict(row) if row else None

    async def get_all_positions(self) -> list[dict[str, Any]]:
        """Get all current positions"""
        query = "SELECT * FROM positions WHERE quantity != 0"
        rows = await db_manager.fetch_all(query)
        return [dict(row) for row in rows]

    async def update_position(
        self,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        realized_pnl: float | None = None,
    ) -> None:
        """Update position information"""
        query = """
        INSERT OR REPLACE INTO positions (
            symbol, quantity, avg_entry_price, realized_pnl, last_updated
        ) VALUES (?, ?, ?, COALESCE(?, (SELECT realized_pnl FROM positions WHERE symbol = ?)), unixepoch())
        """

        await db_manager.execute(
            query, (symbol, quantity, avg_entry_price, realized_pnl, symbol)
        )

        logger.info(
            "Updated position",
            symbol=symbol,
            quantity=quantity,
            avg_entry_price=avg_entry_price,
        )


class BalanceRepository:
    """Repository for account balance tracking"""

    async def update_balance(self, asset: str, available: float, locked: float) -> None:
        """Update account balance"""
        total = available + locked

        query = """
        INSERT OR REPLACE INTO account_balances (
            asset, available, locked, total, updated_at
        ) VALUES (?, ?, ?, ?, unixepoch())
        """

        await db_manager.execute(query, (asset, available, locked, total))

        logger.info(
            "Updated balance",
            asset=asset,
            available=available,
            locked=locked,
            total=total,
        )

    async def get_balance(self, asset: str) -> dict[str, Any] | None:
        """Get balance for specific asset"""
        query = "SELECT * FROM account_balances WHERE asset = ?"
        row = await db_manager.fetch_one(query, (asset,))
        return dict(row) if row else None

    async def get_all_balances(self) -> list[dict[str, Any]]:
        """Get all account balances"""
        query = "SELECT * FROM account_balances WHERE total > 0"
        rows = await db_manager.fetch_all(query)
        return [dict(row) for row in rows]


class OutboxRepository:
    """Repository for outbox pattern event management"""

    async def get_pending_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get pending events for processing"""
        query = """
        SELECT * FROM outbox
        WHERE status = 'pending'
           OR (status = 'failed' AND next_retry_at <= unixepoch())
        ORDER BY created_at
        LIMIT ?
        """

        rows = await db_manager.fetch_all(query, (limit,))
        return [dict(row) for row in rows]

    async def mark_event_processing(self, event_id: str) -> None:
        """Mark event as being processed"""
        query = "UPDATE outbox SET status = 'processing' WHERE event_id = ?"
        await db_manager.execute(query, (event_id,))

    async def mark_event_completed(self, event_id: str) -> None:
        """Mark event as completed"""
        query = """
        UPDATE outbox
        SET status = 'completed', processed_at = unixepoch()
        WHERE event_id = ?
        """
        await db_manager.execute(query, (event_id,))

    async def mark_event_failed(
        self, event_id: str, error_message: str, retry_delay_seconds: int = 60
    ) -> None:
        """Mark event as failed and schedule retry"""
        query = """
        UPDATE outbox
        SET status = CASE
                WHEN retry_count >= max_retries THEN 'dead_letter'
                ELSE 'failed'
            END,
            retry_count = retry_count + 1,
            error_message = ?,
            last_error_at = unixepoch(),
            next_retry_at = CASE
                WHEN retry_count >= max_retries THEN NULL
                ELSE unixepoch() + ?
            END
        WHERE event_id = ?
        """

        await db_manager.execute(query, (error_message, retry_delay_seconds, event_id))

    async def add_event(
        self, 
        event_type: str, 
        aggregate_id: str, 
        payload: dict[str, Any],
        max_retries: int = 5
    ) -> str:
        """Add a new event to the outbox"""
        import uuid
        import json
        
        event_id = str(uuid.uuid4())
        
        query = """
        INSERT INTO outbox (
            event_id, event_type, aggregate_id, payload, 
            status, retry_count, max_retries
        ) VALUES (?, ?, ?, ?, 'pending', 0, ?)
        """
        
        await db_manager.execute(query, (
            event_id, event_type, aggregate_id, 
            json.dumps(payload), max_retries
        ))
        
        return event_id


class TradingSessionRepository:
    """Repository for trading session management"""

    async def create_session(self, session_data: dict[str, Any]) -> int:
        """Create a new trading session"""
        query = """
        INSERT INTO trading_sessions (
            session_id, started_at, config_snapshot, status
        ) VALUES (?, ?, ?, ?)
        """

        params = (
            session_data["session_id"],
            session_data["started_at"],
            json.dumps(session_data["config_snapshot"]),
            session_data.get("status", "active"),
        )

        session_id = await db_manager.execute(query, params)

        logger.info(
            "Created trading session",
            session_id=session_id,
            session_uuid=session_data["session_id"],
        )
        return session_id

    async def end_session(
        self, session_id: str, status: str = "stopped", error_message: str | None = None
    ) -> None:
        """End a trading session"""
        query = """
        UPDATE trading_sessions
        SET ended_at = unixepoch(), status = ?, error_message = ?
        WHERE session_id = ?
        """

        await db_manager.execute(query, (status, error_message, session_id))

        logger.info("Ended trading session", session_id=session_id, status=status)

    async def get_active_session(self) -> dict[str, Any] | None:
        """Get current active session"""
        query = "SELECT * FROM trading_sessions WHERE status = 'active' ORDER BY started_at DESC LIMIT 1"
        row = await db_manager.fetch_one(query)
        return dict(row) if row else None


# Repository instances
quote_repo = QuoteRepository()
order_repo = OrderRepository()
fill_repo = FillRepository()
position_repo = PositionRepository()
balance_repo = BalanceRepository()
outbox_repo = OutboxRepository()
session_repo = TradingSessionRepository()
