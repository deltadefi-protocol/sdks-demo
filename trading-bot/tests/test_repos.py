"""
Comprehensive tests for database repositories and SQLite manager

Tests the complete database layer including:
- SQLite connection management and pooling
- Repository CRUD operations
- Outbox pattern implementation
- Database transactions and error handling
"""

import asyncio
import json
import time
import uuid

import pytest

from bot.db import (
    balance_repo,
    db_manager,
    fill_repo,
    order_repo,
    outbox_repo,
    position_repo,
    quote_repo,
    session_repo,
)
from bot.db.outbox_worker import OutboxWorker
from bot.db.sqlite import SQLiteManager


# Test fixtures
@pytest.fixture
async def test_db():
    """Create a test database in memory"""
    test_manager = SQLiteManager(":memory:")
    await test_manager.initialize()
    yield test_manager
    await test_manager.close()


@pytest.fixture
def sample_quote_data():
    """Sample quote data for testing"""
    return {
        "timestamp": time.time(),
        "symbol_src": "ADAUSDT",
        "symbol_dst": "ADAUSDM",
        "source_bid_price": 0.4500,
        "source_bid_qty": 1000.0,
        "source_ask_price": 0.4505,
        "source_ask_qty": 1500.0,
        "bid_price": 0.4495,
        "bid_qty": 100.0,
        "ask_price": 0.4510,
        "ask_qty": 150.0,
        "spread_bps": 33.3,
        "mid_price": 0.45025,
        "total_spread_bps": 8,
        "sides_enabled": ["bid", "ask"],
    }


@pytest.fixture
def sample_order_data():
    """Sample order data for testing"""
    return {
        "order_id": str(uuid.uuid4()),
        "symbol": "ADAUSDM",
        "side": "bid",
        "order_type": "limit",
        "price": 0.4495,
        "quantity": 100.0,
        "status": "pending",
    }


@pytest.fixture
def sample_fill_data():
    """Sample fill data for testing"""
    return {
        "fill_id": str(uuid.uuid4()),
        "order_id": str(uuid.uuid4()),
        "symbol": "ADAUSDM",
        "side": "bid",
        "price": 0.4495,
        "quantity": 50.0,
        "executed_at": time.time(),
        "trade_id": "test_trade_123",
        "commission": 0.1,
        "commission_asset": "ADA",
        "is_maker": True,
    }


class TestSQLiteManager:
    """Test SQLite connection manager"""

    @pytest.mark.asyncio
    async def test_initialization(self, test_db):
        """Test database initialization"""
        # Test that tables were created
        tables = await test_db.get_tables()
        expected_tables = [
            "quotes",
            "orders",
            "fills",
            "outbox",
            "positions",
            "account_balances",
            "trading_sessions",
        ]

        for table in expected_tables:
            assert table in tables

    @pytest.mark.asyncio
    async def test_connection_pooling(self, test_db):
        """Test connection pooling behavior"""
        # Test that we can get multiple connections
        async with test_db.get_connection() as conn1, test_db.get_connection() as conn2:
                # Both connections should be usable
                result1 = await conn1.execute("SELECT 1 as test")
                result2 = await conn2.execute("SELECT 1 as test")

                row1 = await result1.fetchone()
                row2 = await result2.fetchone()

                assert row1["test"] == 1
                assert row2["test"] == 1

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, test_db):
        """Test transaction rollback on error"""
        try:
            async with test_db.transaction() as conn:
                await conn.execute(
                    "INSERT INTO quotes (timestamp, symbol_src, symbol_dst, total_spread_bps, sides_enabled) VALUES (?, ?, ?, ?, ?)",
                    (time.time(), "TEST", "TEST", 10, "[]"),
                )
                # Force an error
                await conn.execute("INVALID SQL")
        except Exception:
            pass  # Expected

        # Verify rollback - no quotes should exist
        rows = await test_db.fetch_all("SELECT * FROM quotes WHERE symbol_src = 'TEST'")
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_database_size_tracking(self, test_db):
        """Test database size statistics"""
        stats = await test_db.get_database_size()

        assert "total_size_mb" in stats
        assert "total_pages" in stats
        assert "page_size_bytes" in stats
        assert stats["total_pages"] >= 0
        assert stats["page_size_bytes"] > 0


class TestQuoteRepository:
    """Test quote repository operations"""

    @pytest.mark.asyncio
    async def test_create_quote(self, test_db, sample_quote_data):
        """Test quote creation"""
        # Monkey patch for test
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            quote_id = await quote_repo.create_quote(sample_quote_data)
            assert quote_id is not None

            # Verify quote was created
            rows = await test_db.fetch_all(
                "SELECT * FROM quotes WHERE id = ?", (quote_id,)
            )
            assert len(rows) == 1

            quote = dict(rows[0])
            assert quote["symbol_src"] == "ADAUSDT"
            assert quote["symbol_dst"] == "ADAUSDM"
            assert quote["bid_price"] == 0.4495
            assert json.loads(quote["sides_enabled"]) == ["bid", "ask"]

        finally:
            # Restore original db_manager
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_get_recent_quotes(self, test_db, sample_quote_data):
        """Test retrieving recent quotes"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create multiple quotes
            quote_id1 = await quote_repo.create_quote(sample_quote_data)

            # Create second quote with different timestamp
            sample_quote_data["timestamp"] = time.time() + 1
            quote_id2 = await quote_repo.create_quote(sample_quote_data)

            # Get recent quotes
            quotes = await quote_repo.get_recent_quotes("ADAUSDM", limit=10)

            assert len(quotes) == 2
            # Should be in descending order by created_at
            assert quotes[0]["id"] == quote_id2  # More recent
            assert quotes[1]["id"] == quote_id1

        finally:
            bot.db.repo.db_manager = db_manager


class TestOrderRepository:
    """Test order repository operations"""

    @pytest.mark.asyncio
    async def test_create_order(self, test_db, sample_order_data):
        """Test order creation with outbox event"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            order_id = await order_repo.create_order(sample_order_data)
            assert order_id is not None

            # Verify order was created
            order = await order_repo.get_order(sample_order_data["order_id"])
            assert order is not None
            assert order["symbol"] == "ADAUSDM"
            assert order["status"] == "pending"

            # Verify outbox event was created
            events = await outbox_repo.get_pending_events(limit=10)
            assert len(events) == 1
            assert events[0]["event_type"] == "order_created"
            assert events[0]["aggregate_id"] == sample_order_data["order_id"]

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_update_order_status(self, test_db, sample_order_data):
        """Test order status updates"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create order
            await order_repo.create_order(sample_order_data)

            # Update status
            await order_repo.update_order_status(
                sample_order_data["order_id"],
                "submitted",
                deltadefi_order_id="ddefi_123",
                tx_hash="0xabc123",
            )

            # Verify update
            order = await order_repo.get_order(sample_order_data["order_id"])
            assert order["status"] == "submitted"
            assert order["deltadefi_order_id"] == "ddefi_123"
            assert order["tx_hash"] == "0xabc123"
            assert order["submitted_at"] is not None

            # Verify outbox event
            events = await outbox_repo.get_pending_events(limit=10)
            status_events = [
                e for e in events if e["event_type"] == "order_status_updated"
            ]
            assert len(status_events) == 1

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_update_order_fill(self, test_db, sample_order_data):
        """Test order fill updates"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create order
            await order_repo.create_order(sample_order_data)

            # Update fill
            await order_repo.update_order_fill(
                sample_order_data["order_id"], 50.0, 0.4495
            )

            # Verify fill update
            order = await order_repo.get_order(sample_order_data["order_id"])
            assert order["filled_quantity"] == 50.0
            assert order["avg_fill_price"] == 0.4495
            assert order["remaining_quantity"] == 50.0  # Updated by trigger

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_get_active_orders(self, test_db, sample_order_data):
        """Test retrieving active orders"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create active order
            await order_repo.create_order(sample_order_data)

            # Create completed order
            completed_order = sample_order_data.copy()
            completed_order["order_id"] = str(uuid.uuid4())
            completed_order["status"] = "filled"
            await order_repo.create_order(completed_order)

            # Get active orders
            active_orders = await order_repo.get_active_orders()

            # Should only return pending order (active view excludes filled)
            assert len(active_orders) == 1
            assert active_orders[0]["status"] == "pending"

        finally:
            bot.db.repo.db_manager = db_manager


class TestFillRepository:
    """Test fill repository operations"""

    @pytest.mark.asyncio
    async def test_create_fill(self, test_db, sample_fill_data):
        """Test fill creation"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            fill_id = await fill_repo.create_fill(sample_fill_data)
            assert fill_id is not None

            # Verify fill was created
            fills = await fill_repo.get_fills_for_order(sample_fill_data["order_id"])
            assert len(fills) == 1

            fill = fills[0]
            assert fill["fill_id"] == sample_fill_data["fill_id"]
            assert fill["price"] == 0.4495
            assert fill["quantity"] == 50.0

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_get_recent_fills(self, test_db, sample_fill_data):
        """Test retrieving recent fills"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create fill
            await fill_repo.create_fill(sample_fill_data)

            # Get recent fills
            fills = await fill_repo.get_recent_fills(limit=10)
            assert len(fills) == 1
            assert fills[0]["symbol"] == "ADAUSDM"

            # Test symbol filtering
            fills_filtered = await fill_repo.get_recent_fills(
                symbol="ADAUSDM", limit=10
            )
            assert len(fills_filtered) == 1

            fills_other = await fill_repo.get_recent_fills(symbol="OTHER", limit=10)
            assert len(fills_other) == 0

        finally:
            bot.db.repo.db_manager = db_manager


class TestPositionRepository:
    """Test position repository operations"""

    @pytest.mark.asyncio
    async def test_update_position(self, test_db):
        """Test position updates"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Update position
            await position_repo.update_position(
                "ADAUSDM", 100.0, 0.4500, realized_pnl=10.5
            )

            # Verify position
            position = await position_repo.get_position("ADAUSDM")
            assert position is not None
            assert position["quantity"] == 100.0
            assert position["avg_entry_price"] == 0.4500
            assert position["realized_pnl"] == 10.5

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_get_all_positions(self, test_db):
        """Test retrieving all positions"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create multiple positions
            await position_repo.update_position("ADAUSDM", 100.0, 0.4500)
            await position_repo.update_position("ADAUSD", -50.0, 0.4600)
            await position_repo.update_position("ZEROED", 0.0, 0.5000)  # Zero position

            # Get all positions (should exclude zero)
            positions = await position_repo.get_all_positions()
            assert len(positions) == 2

            symbols = [pos["symbol"] for pos in positions]
            assert "ADAUSDM" in symbols
            assert "ADAUSD" in symbols
            assert "ZEROED" not in symbols  # Excluded because quantity = 0

        finally:
            bot.db.repo.db_manager = db_manager


class TestBalanceRepository:
    """Test balance repository operations"""

    @pytest.mark.asyncio
    async def test_update_balance(self, test_db):
        """Test balance updates"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Update balance
            await balance_repo.update_balance("ADA", 1000.0, 200.0)

            # Verify balance
            balance = await balance_repo.get_balance("ADA")
            assert balance is not None
            assert balance["available"] == 1000.0
            assert balance["locked"] == 200.0
            assert balance["total"] == 1200.0

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_get_all_balances(self, test_db):
        """Test retrieving all balances"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create multiple balances
            await balance_repo.update_balance("ADA", 1000.0, 200.0)
            await balance_repo.update_balance("USDM", 5000.0, 0.0)
            await balance_repo.update_balance("ZERO", 0.0, 0.0)  # Zero balance

            # Get all balances (should exclude zero)
            balances = await balance_repo.get_all_balances()
            assert len(balances) == 2

            assets = [bal["asset"] for bal in balances]
            assert "ADA" in assets
            assert "USDM" in assets
            assert "ZERO" not in assets  # Excluded because total = 0

        finally:
            bot.db.repo.db_manager = db_manager


class TestOutboxRepository:
    """Test outbox repository operations"""

    @pytest.mark.asyncio
    async def test_outbox_event_lifecycle(self, test_db):
        """Test complete outbox event lifecycle"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create test event
            event_id = str(uuid.uuid4())
            await test_db.execute(
                "INSERT INTO outbox (event_id, event_type, aggregate_id, payload) VALUES (?, ?, ?, ?)",
                (event_id, "test_event", "test_123", '{"test": "data"}'),
            )

            # Get pending events
            events = await outbox_repo.get_pending_events(limit=10)
            assert len(events) == 1
            assert events[0]["event_id"] == event_id
            assert events[0]["status"] == "pending"

            # Mark as processing
            await outbox_repo.mark_event_processing(event_id)

            # Verify status change
            events = await outbox_repo.get_pending_events(limit=10)
            assert len(events) == 0  # No longer pending

            # Mark as completed
            await outbox_repo.mark_event_completed(event_id)

            # Verify completion
            row = await test_db.fetch_one(
                "SELECT * FROM outbox WHERE event_id = ?", (event_id,)
            )
            assert row["status"] == "completed"
            assert row["processed_at"] is not None

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_outbox_retry_logic(self, test_db):
        """Test outbox retry and failure handling"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create test event
            event_id = str(uuid.uuid4())
            await test_db.execute(
                "INSERT INTO outbox (event_id, event_type, aggregate_id, payload) VALUES (?, ?, ?, ?)",
                (event_id, "test_event", "test_123", '{"test": "data"}'),
            )

            # Mark as failed
            await outbox_repo.mark_event_failed(
                event_id, "Test error", retry_delay_seconds=60
            )

            # Verify retry state
            row = await test_db.fetch_one(
                "SELECT * FROM outbox WHERE event_id = ?", (event_id,)
            )
            assert row["status"] == "failed"
            assert row["retry_count"] == 1
            assert row["error_message"] == "Test error"
            assert row["next_retry_at"] is not None

            # Simulate multiple failures to reach dead letter
            for i in range(5):  # Max retries is 5 by default
                await outbox_repo.mark_event_failed(
                    event_id, f"Error {i + 2}", retry_delay_seconds=60
                )

            # Should be dead letter now
            row = await test_db.fetch_one(
                "SELECT * FROM outbox WHERE event_id = ?", (event_id,)
            )
            assert row["status"] == "dead_letter"
            assert row["retry_count"] == 6

        finally:
            bot.db.repo.db_manager = db_manager


class TestTradingSessionRepository:
    """Test trading session repository operations"""

    @pytest.mark.asyncio
    async def test_create_session(self, test_db):
        """Test session creation"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            session_data = {
                "session_id": str(uuid.uuid4()),
                "started_at": time.time(),
                "config_snapshot": {"symbol": "ADAUSDM", "anchor_bps": 5},
            }

            session_id = await session_repo.create_session(session_data)
            assert session_id is not None

            # Verify session
            session = await session_repo.get_active_session()
            assert session is not None
            assert session["session_id"] == session_data["session_id"]
            assert session["status"] == "active"

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_end_session(self, test_db):
        """Test session termination"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create session
            session_data = {
                "session_id": str(uuid.uuid4()),
                "started_at": time.time(),
                "config_snapshot": {"test": True},
            }
            await session_repo.create_session(session_data)

            # End session
            await session_repo.end_session(session_data["session_id"], "stopped")

            # Verify no active session
            session = await session_repo.get_active_session()
            assert session is None

        finally:
            bot.db.repo.db_manager = db_manager


class TestOutboxWorker:
    """Test outbox worker functionality"""

    @pytest.mark.asyncio
    async def test_worker_processing(self, test_db):
        """Test that worker can process events"""
        # Create test worker with short poll interval
        worker = OutboxWorker(batch_size=1, max_concurrent=1, poll_interval=0.1)

        # Mock the db_manager for worker
        import bot.db.outbox_worker

        original_db = bot.db.outbox_worker.db_manager
        bot.db.outbox_worker.db_manager = test_db

        import bot.db.repo

        original_repo_db = bot.db.repo.db_manager
        bot.db.repo.db_manager = test_db

        try:
            # Create test event
            event_id = str(uuid.uuid4())
            await test_db.execute(
                "INSERT INTO outbox (event_id, event_type, aggregate_id, payload) VALUES (?, ?, ?, ?)",
                (event_id, "order_created", "test_order_123", '{"symbol": "ADAUSDM"}'),
            )

            # Start worker briefly
            worker_task = asyncio.create_task(worker.start())

            # Wait a moment for processing
            await asyncio.sleep(0.3)

            # Stop worker
            await worker.stop()
            worker_task.cancel()

            try:
                await worker_task
            except asyncio.CancelledError:
                pass

            # Verify event was processed
            row = await test_db.fetch_one(
                "SELECT * FROM outbox WHERE event_id = ?", (event_id,)
            )
            assert row["status"] == "completed"

        finally:
            # Restore original db managers
            bot.db.outbox_worker.db_manager = original_db
            bot.db.repo.db_manager = original_repo_db


class TestDatabaseIntegration:
    """Integration tests for database components"""

    @pytest.mark.asyncio
    async def test_order_to_fill_flow(self, test_db):
        """Test complete order-to-fill data flow"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # 1. Create quote
            quote_data = {
                "timestamp": time.time(),
                "symbol_src": "ADAUSDT",
                "symbol_dst": "ADAUSDM",
                "source_bid_price": 0.4500,
                "source_bid_qty": 1000.0,
                "source_ask_price": 0.4505,
                "source_ask_qty": 1500.0,
                "bid_price": 0.4495,
                "bid_qty": 100.0,
                "ask_price": None,  # Ask side disabled
                "ask_qty": None,
                "total_spread_bps": 8,
                "sides_enabled": ["bid"],
            }
            quote_id = await quote_repo.create_quote(quote_data)

            # 2. Create order from quote
            order_data = {
                "order_id": str(uuid.uuid4()),
                "quote_id": quote_id,
                "symbol": "ADAUSDM",
                "side": "bid",
                "order_type": "limit",
                "price": 0.4495,
                "quantity": 100.0,
            }
            await order_repo.create_order(order_data)

            # 3. Update order status to submitted
            await order_repo.update_order_status(
                order_data["order_id"], "submitted", deltadefi_order_id="ddefi_456"
            )

            # 4. Create partial fill
            fill_data = {
                "fill_id": str(uuid.uuid4()),
                "order_id": order_data["order_id"],
                "symbol": "ADAUSDM",
                "side": "bid",
                "price": 0.4495,
                "quantity": 50.0,
                "executed_at": time.time(),
            }
            await fill_repo.create_fill(fill_data)

            # 5. Update order with partial fill
            await order_repo.update_order_fill(
                order_data["order_id"],
                50.0,  # filled_quantity
                0.4495,  # avg_fill_price
            )

            # 6. Verify complete flow
            order = await order_repo.get_order(order_data["order_id"])
            assert order["status"] == "submitted"  # Still not fully filled
            assert order["filled_quantity"] == 50.0
            assert order["remaining_quantity"] == 50.0  # Updated by trigger

            fills = await fill_repo.get_fills_for_order(order_data["order_id"])
            assert len(fills) == 1
            assert fills[0]["quantity"] == 50.0

            # 7. Verify outbox events were created
            events = await outbox_repo.get_pending_events(limit=10)
            event_types = [e["event_type"] for e in events]
            assert "order_created" in event_types
            assert "order_status_updated" in event_types
            assert "order_filled" in event_types
            assert "fill_created" in event_types

        finally:
            bot.db.repo.db_manager = db_manager

    @pytest.mark.asyncio
    async def test_position_trigger_on_fill(self, test_db):
        """Test that position is updated when fill is created (via trigger)"""
        import bot.db.repo

        bot.db.repo.db_manager = test_db

        try:
            # Create fill directly (triggers position update)
            fill_data = {
                "fill_id": str(uuid.uuid4()),
                "order_id": str(uuid.uuid4()),
                "symbol": "ADAUSDM",
                "side": "bid",  # Buy side
                "price": 0.4500,
                "quantity": 100.0,
                "executed_at": time.time(),
            }
            await fill_repo.create_fill(fill_data)

            # Verify position was updated by trigger
            position = await position_repo.get_position("ADAUSDM")
            assert position is not None
            assert position["quantity"] == 100.0  # Positive for buy
            assert position["avg_entry_price"] == 0.4500

            # Create another fill on sell side
            fill_data2 = {
                "fill_id": str(uuid.uuid4()),
                "order_id": str(uuid.uuid4()),
                "symbol": "ADAUSDM",
                "side": "ask",  # Sell side
                "price": 0.4600,
                "quantity": 30.0,
                "executed_at": time.time(),
            }
            await fill_repo.create_fill(fill_data2)

            # Position should be reduced
            position = await position_repo.get_position("ADAUSDM")
            assert position["quantity"] == 70.0  # 100 - 30

        finally:
            bot.db.repo.db_manager = db_manager
