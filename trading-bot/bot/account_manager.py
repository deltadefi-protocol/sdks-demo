"""
Account State Management

This module implements comprehensive account state management including:
- WebSocket feed processing for real-time account updates
- Balance tracking with historical snapshots
- Fill reconciliation and position management
- Account health monitoring and alerting
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import time
from typing import Any

import structlog

from .db.repo import outbox_repo
from .db.sqlite import db_manager
from .deltadefi import AccountWebSocket, DeltaDeFiClient

logger = structlog.get_logger()


class FillStatus(str, Enum):
    """Fill processing status"""

    RECEIVED = "received"
    RECONCILED = "reconciled"
    PROCESSED = "processed"
    ERROR = "error"


class BalanceUpdateReason(str, Enum):
    """Reasons for balance updates"""

    TRADE_FILL = "trade_fill"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    FEE = "fee"
    ADJUSTMENT = "adjustment"
    INITIAL = "initial"


@dataclass
class AccountFill:
    """Represents a trade fill from DeltaDeFi"""

    fill_id: str
    order_id: str
    symbol: str
    side: str  # buy/sell
    price: Decimal
    quantity: Decimal
    executed_at: float
    trade_id: str | None = None
    commission: Decimal = Decimal("0")
    commission_asset: str = ""
    is_maker: bool = True
    status: FillStatus = FillStatus.RECEIVED
    received_at: float = field(default_factory=time.time)
    processed_at: float | None = None

    @classmethod
    def from_websocket_data(cls, data: dict[str, Any]) -> "AccountFill":
        """Create AccountFill from DeltaDeFi WebSocket message

        Supports two formats:
        1. Direct fill message: {"fillId": "...", "orderId": "...", ...}
        2. Trading history record: {"execution_id": "...", "order_id": "...", "executed_qty": "...", ...}
        """
        # Check if this is a trading_history format (from SDK's OrderFillingRecordJSON)
        if "execution_id" in data:
            # Trading history format
            return cls(
                fill_id=str(data.get("execution_id", "")),
                order_id=str(data.get("order_id", "")),
                symbol=data.get("symbol", "").upper(),
                side=data.get("side", "").lower(),
                price=Decimal(str(data.get("executed_price", 0))),
                quantity=Decimal(str(data.get("executed_qty", 0))),
                executed_at=float(data.get("created_time", time.time())),
                trade_id=str(data.get("execution_id", "")),
                commission=Decimal(str(data.get("fee_charged", 0))),
                commission_asset=data.get("fee_unit", ""),
                is_maker=True,  # Default to maker, actual value not in response
            )
        else:
            # Original direct fill format
            return cls(
                fill_id=str(data.get("fillId", data.get("id", ""))),
                order_id=str(data.get("orderId", "")),
                symbol=data.get("symbol", "").upper(),
                side=data.get("side", "").lower(),
                price=Decimal(str(data.get("price", 0))),
                quantity=Decimal(str(data.get("quantity", 0))),
                executed_at=float(data.get("timestamp", time.time())),
                trade_id=str(data.get("tradeId")) if data.get("tradeId") else None,
                commission=Decimal(str(data.get("commission", 0))),
                commission_asset=data.get("commissionAsset", ""),
                is_maker=bool(data.get("isMaker", True)),
            )


@dataclass
class AccountBalance:
    """Represents account balance for an asset"""

    asset: str
    available: Decimal
    locked: Decimal
    total: Decimal
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def from_websocket_data(cls, asset: str, data: dict[str, Any]) -> "AccountBalance":
        """Create AccountBalance from DeltaDeFi WebSocket message"""
        available = Decimal(str(data.get("available", 0)))
        locked = Decimal(str(data.get("locked", 0)))

        return cls(
            asset=asset, available=available, locked=locked, total=available + locked
        )


@dataclass
class PositionUpdate:
    """Position update from fill reconciliation"""

    symbol: str
    quantity_delta: Decimal  # Change in position
    avg_price_update: Decimal  # New average price
    realized_pnl: Decimal  # Realized P&L from this update
    fill_id: str
    timestamp: float = field(default_factory=time.time)


class BalanceTracker:
    """Tracks account balances with historical snapshots"""

    def __init__(self):
        self.current_balances: dict[str, AccountBalance] = {}
        self.balance_callbacks: list[Callable] = []
        self._balance_lock = asyncio.Lock()

    def add_balance_callback(self, callback: Callable):
        """Add callback for balance updates"""
        self.balance_callbacks.append(callback)

    async def update_balance(
        self,
        asset: str,
        available: Decimal,
        locked: Decimal,
        reason: BalanceUpdateReason = BalanceUpdateReason.ADJUSTMENT,
    ):
        """Update account balance"""
        async with self._balance_lock:
            old_balance = self.current_balances.get(asset)

            new_balance = AccountBalance(
                asset=asset,
                available=available,
                locked=locked,
                total=available + locked,
            )

            self.current_balances[asset] = new_balance

            # Persist to database
            await self._persist_balance(new_balance)

            # Log significant changes
            if old_balance:
                total_change = new_balance.total - old_balance.total
                if abs(total_change) > Decimal("0.001"):  # Significant change threshold
                    logger.info(
                        "Balance updated",
                        asset=asset,
                        old_total=float(old_balance.total),
                        new_total=float(new_balance.total),
                        change=float(total_change),
                        reason=reason,
                    )
            else:
                logger.info(
                    "Initial balance set",
                    asset=asset,
                    total=float(new_balance.total),
                    reason=reason,
                )

            # Notify callbacks
            await self._notify_balance_callbacks(new_balance, reason)

    async def update_from_websocket_data(self, balances: dict[str, dict[str, Any]]):
        """Update balances from WebSocket account update"""
        for asset, balance_data in balances.items():
            balance = AccountBalance.from_websocket_data(asset, balance_data)
            await self.update_balance(
                asset, balance.available, balance.locked, BalanceUpdateReason.ADJUSTMENT
            )

    def get_balance(self, asset: str) -> AccountBalance | None:
        """Get current balance for asset"""
        return self.current_balances.get(asset)

    def get_all_balances(self) -> dict[str, AccountBalance]:
        """Get all current balances"""
        return self.current_balances.copy()

    def get_total_value_usd(self) -> Decimal:
        """Get total portfolio value in USD (requires price feeds)"""
        # TODO: Implement with price conversion
        usd_balance = self.current_balances.get(
            "USD", AccountBalance("USD", Decimal("0"), Decimal("0"), Decimal("0"))
        )
        return usd_balance.total

    async def _persist_balance(self, balance: AccountBalance):
        """Persist balance to database"""
        try:
            query = """
            INSERT OR REPLACE INTO account_balances (asset, available, locked, total, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """

            async with db_manager.get_connection() as conn:
                await conn.execute(
                    query,
                    (
                        balance.asset,
                        float(balance.available),
                        float(balance.locked),
                        float(balance.total),
                        balance.updated_at,
                    ),
                )
                await conn.commit()

        except Exception as e:
            logger.error("Failed to persist balance", asset=balance.asset, error=str(e))

    async def _notify_balance_callbacks(
        self, balance: AccountBalance, reason: BalanceUpdateReason
    ):
        """Notify balance update callbacks"""
        for callback in self.balance_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(balance, reason)
                else:
                    callback(balance, reason)
            except Exception as e:
                logger.error(
                    "Error in balance callback",
                    callback=callback.__name__,
                    error=str(e),
                )


class FillReconciler:
    """Reconciles fills with orders and updates positions"""

    def __init__(self, balance_tracker: BalanceTracker):
        self.balance_tracker = balance_tracker
        self.processed_fills: set[str] = set()
        self.fill_callbacks: list[Callable] = []
        self.position_callbacks: list[Callable] = []
        self._reconciliation_lock = asyncio.Lock()

    def add_fill_callback(self, callback: Callable):
        """Add callback for fill events"""
        self.fill_callbacks.append(callback)

    def add_position_callback(self, callback: Callable):
        """Add callback for position updates"""
        self.position_callbacks.append(callback)

    async def process_fill(self, fill: AccountFill) -> bool:
        """Process and reconcile a fill"""
        if fill.fill_id in self.processed_fills:
            logger.debug("Fill already processed", fill_id=fill.fill_id)
            return False

        async with self._reconciliation_lock:
            try:
                # Persist fill to database
                await self._persist_fill(fill)

                # Update position
                position_update = await self._update_position(fill)

                # Update balances based on fill
                await self._update_balances_from_fill(fill)

                # Mark as processed
                fill.status = FillStatus.PROCESSED
                fill.processed_at = time.time()
                self.processed_fills.add(fill.fill_id)

                # Update fill status in database
                await self._update_fill_status(fill)

                logger.info(
                    "Fill processed and reconciled",
                    fill_id=fill.fill_id,
                    order_id=fill.order_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    quantity=float(fill.quantity),
                    price=float(fill.price),
                )

                # Notify callbacks
                await self._notify_fill_callbacks(fill)
                if position_update:
                    await self._notify_position_callbacks(position_update)

                # Publish outbox event
                await self._publish_fill_event(fill, position_update)

                return True

            except Exception as e:
                fill.status = FillStatus.ERROR
                await self._update_fill_status(fill)
                logger.error(
                    "Fill processing failed",
                    fill_id=fill.fill_id,
                    error=str(e),
                    exc_info=True,
                )
                return False

    async def _persist_fill(self, fill: AccountFill):
        """Persist fill to database"""
        query = """
        INSERT OR REPLACE INTO fills (
            fill_id, order_id, symbol, side, price, quantity,
            executed_at, trade_id, commission, commission_asset,
            is_maker, created_at, status, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        async with db_manager.get_connection() as conn:
            await conn.execute(
                query,
                (
                    fill.fill_id,
                    fill.order_id,
                    fill.symbol,
                    fill.side,
                    float(fill.price),
                    float(fill.quantity),
                    fill.executed_at,
                    fill.trade_id,
                    float(fill.commission),
                    fill.commission_asset,
                    fill.is_maker,
                    fill.received_at,
                    fill.status,
                    fill.processed_at,
                ),
            )
            await conn.commit()

    async def _update_position(self, fill: AccountFill) -> PositionUpdate | None:
        """Update position based on fill"""
        try:
            # Calculate quantity delta (positive for buy, negative for sell)
            quantity_delta = fill.quantity if fill.side == "buy" else -fill.quantity

            # Get current position
            query = "SELECT quantity, avg_entry_price FROM positions WHERE symbol = ?"
            result = await db_manager.fetch_one(query, (fill.symbol,))

            if result:
                current_qty = Decimal(str(result["quantity"]))
                current_avg_price = Decimal(str(result["avg_entry_price"]))
            else:
                current_qty = Decimal("0")
                current_avg_price = Decimal("0")

            # Calculate new position
            new_qty = current_qty + quantity_delta

            # Calculate realized P&L and new average price
            realized_pnl = Decimal("0")
            if current_qty != 0 and (current_qty > 0) != (quantity_delta > 0):
                # Reducing position - calculate realized P&L
                close_qty = min(abs(quantity_delta), abs(current_qty))
                realized_pnl = close_qty * (fill.price - current_avg_price)
                if current_qty < 0:  # Short position
                    realized_pnl = -realized_pnl

            # Calculate new average price
            if new_qty == 0:
                new_avg_price = Decimal("0")
            elif (current_qty > 0 and quantity_delta > 0) or (
                current_qty < 0 and quantity_delta < 0
            ):
                # Adding to position
                total_cost = (current_qty * current_avg_price) + (
                    quantity_delta * fill.price
                )
                new_avg_price = total_cost / new_qty
            elif abs(new_qty) < abs(current_qty):
                # Reducing position - keep current average price
                new_avg_price = current_avg_price
            else:
                # Flipping position
                new_avg_price = fill.price

            # Update position in database
            upsert_query = """
            INSERT OR REPLACE INTO positions (
                symbol, quantity, avg_entry_price, realized_pnl, last_updated
            ) VALUES (?, ?, ?, ?, ?)
            """

            current_realized = Decimal("0")
            if result:
                current_realized_result = await db_manager.fetch_one(
                    "SELECT realized_pnl FROM positions WHERE symbol = ?",
                    (fill.symbol,),
                )
                if current_realized_result:
                    current_realized = Decimal(
                        str(current_realized_result["realized_pnl"])
                    )

            async with db_manager.get_connection() as conn:
                await conn.execute(
                    upsert_query,
                    (
                        fill.symbol,
                        float(new_qty),
                        float(new_avg_price),
                        float(current_realized + realized_pnl),
                        time.time(),
                    ),
                )
                await conn.commit()

            return PositionUpdate(
                symbol=fill.symbol,
                quantity_delta=quantity_delta,
                avg_price_update=new_avg_price,
                realized_pnl=realized_pnl,
                fill_id=fill.fill_id,
            )

        except Exception as e:
            logger.error(
                "Position update failed",
                fill_id=fill.fill_id,
                symbol=fill.symbol,
                error=str(e),
            )
            return None

    async def _update_balances_from_fill(self, fill: AccountFill):
        """Update account balances based on fill"""
        try:
            # Parse symbol to get base and quote assets
            # Assuming format like "ADAUSDM" -> base="ADA", quote="USDM"
            if fill.symbol.endswith("USDM"):
                base_asset = fill.symbol[:-4]
                quote_asset = "USDM"
            elif fill.symbol.endswith("USDT"):
                base_asset = fill.symbol[:-4]
                quote_asset = "USDT"
            else:
                # Default parsing - might need adjustment
                base_asset = fill.symbol[:3]
                quote_asset = fill.symbol[3:]

            # Get current balances
            base_balance = self.balance_tracker.get_balance(base_asset)
            quote_balance = self.balance_tracker.get_balance(quote_asset)

            if not base_balance or not quote_balance:
                logger.warning(
                    "Missing balance data for fill processing",
                    fill_id=fill.fill_id,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    has_base=base_balance is not None,
                    has_quote=quote_balance is not None,
                )
                return

            # Calculate balance changes
            if fill.side == "buy":
                # Buying base asset with quote asset
                base_change = fill.quantity
                quote_change = -(fill.quantity * fill.price)
            else:
                # Selling base asset for quote asset
                base_change = -fill.quantity
                quote_change = fill.quantity * fill.price

            # Apply commission
            if fill.commission > 0:
                if fill.commission_asset == base_asset:
                    base_change -= fill.commission
                elif fill.commission_asset == quote_asset:
                    quote_change -= fill.commission

            # Update balances
            await self.balance_tracker.update_balance(
                base_asset,
                base_balance.available + base_change,
                base_balance.locked,
                BalanceUpdateReason.TRADE_FILL,
            )

            await self.balance_tracker.update_balance(
                quote_asset,
                quote_balance.available + quote_change,
                quote_balance.locked,
                BalanceUpdateReason.TRADE_FILL,
            )

        except Exception as e:
            logger.error(
                "Balance update from fill failed", fill_id=fill.fill_id, error=str(e)
            )

    async def _update_fill_status(self, fill: AccountFill):
        """Update fill status in database"""
        query = "UPDATE fills SET status = ?, processed_at = ? WHERE fill_id = ?"

        async with db_manager.get_connection() as conn:
            await conn.execute(query, (fill.status, fill.processed_at, fill.fill_id))
            await conn.commit()

    async def _publish_fill_event(
        self, fill: AccountFill, position_update: PositionUpdate | None
    ):
        """Publish fill event to outbox"""
        await outbox_repo.add_event(
            event_type="fill_processed",
            aggregate_id=fill.fill_id,
            payload={
                "fill_id": fill.fill_id,
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "price": float(fill.price),
                "quantity": float(fill.quantity),
                "executed_at": fill.executed_at,
                "commission": float(fill.commission),
                "position_update": {
                    "quantity_delta": float(position_update.quantity_delta),
                    "realized_pnl": float(position_update.realized_pnl),
                    "avg_price": float(position_update.avg_price_update),
                }
                if position_update
                else None,
            },
        )

    async def _notify_fill_callbacks(self, fill: AccountFill):
        """Notify fill callbacks"""
        for callback in self.fill_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(fill)
                else:
                    callback(fill)
            except Exception as e:
                logger.error(
                    "Error in fill callback", callback=callback.__name__, error=str(e)
                )

    async def _notify_position_callbacks(self, position_update: PositionUpdate):
        """Notify position callbacks"""
        for callback in self.position_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(position_update)
                else:
                    callback(position_update)
            except Exception as e:
                logger.error(
                    "Error in position callback",
                    callback=callback.__name__,
                    error=str(e),
                )


class AccountManager:
    """
    Main account state management coordinator

    Orchestrates WebSocket feed processing, balance tracking, and fill reconciliation
    """

    def __init__(self, deltadefi_client: DeltaDeFiClient):
        self.deltadefi_client = deltadefi_client
        self.balance_tracker = BalanceTracker()
        self.fill_reconciler = FillReconciler(self.balance_tracker)

        # WebSocket connections
        self.account_ws: AccountWebSocket | None = None

        # State
        self.running = False
        self.connection_retry_count = 0
        self.max_retries = 5

        # Callbacks
        self.account_callbacks: list[Callable] = []

        logger.info("Account Manager initialized")

    def add_account_callback(self, callback: Callable):
        """Add callback for account events"""
        self.account_callbacks.append(callback)

    async def start(self):
        """Start account state management"""
        if self.running:
            return

        self.running = True

        try:
            # Load initial balances from database
            await self._load_initial_balances()

            # Fetch current balances from DeltaDeFi API
            await self._fetch_current_balances()

            # Start WebSocket connection
            await self._start_websocket()

            logger.info("Account Manager started successfully")

        except Exception as e:
            logger.error("Failed to start Account Manager", error=str(e))
            self.running = False
            raise

    async def stop(self):
        """Stop account state management"""
        self.running = False

        if self.account_ws:
            await self.account_ws.stop()
            self.account_ws = None

        logger.info("Account Manager stopped")

    async def _load_initial_balances(self):
        """Load balances from database on startup"""
        try:
            query = "SELECT asset, available, locked, total FROM account_balances"
            results = await db_manager.fetch_all(query)

            for row in results:
                balance = AccountBalance(
                    asset=row["asset"],
                    available=Decimal(str(row["available"])),
                    locked=Decimal(str(row["locked"])),
                    total=Decimal(str(row["total"])),
                )
                self.balance_tracker.current_balances[balance.asset] = balance

            logger.info(
                "Initial balances loaded",
                balance_count=len(self.balance_tracker.current_balances),
            )

        except Exception as e:
            logger.error("Failed to load initial balances", error=str(e))

    async def _fetch_current_balances(self):
        """Fetch current balances from DeltaDeFi API"""
        try:
            # Fetch account balance from DeltaDeFi REST API
            balance_response = await self.deltadefi_client.get_account_balance()

            logger.info("Account balance fetched from API", response=balance_response)

            # Parse and update balances
            # The response format may vary - handle different formats
            if isinstance(balance_response, list):
                # Direct list format: [{"asset": "USDM", "free": "...", ...}, ...]
                balances_data = balance_response
            elif isinstance(balance_response, dict):
                # Check for nested data structure
                balances_data = balance_response.get("data", balance_response)
            else:
                logger.warning("Unexpected balance response format", response_type=type(balance_response))
                return

            # Handle different response formats
            if isinstance(balances_data, dict) and "balances" in balances_data:
                # Format: {"balances": {"USDM": {"available": "...", "locked": "..."}, ...}}
                for asset, balance_info in balances_data["balances"].items():
                    await self.balance_tracker.update_balance(
                        asset=asset.upper(),
                        available=Decimal(str(balance_info.get("available", 0))),
                        locked=Decimal(str(balance_info.get("locked", 0))),
                        reason=BalanceUpdateReason.INITIAL,
                    )
            elif isinstance(balances_data, list):
                # Format: [{"asset": "USDM", "free": "...", "locked": "..."}, ...]
                # Note: DeltaDeFi API uses "free" instead of "available"
                for balance_item in balances_data:
                    available = balance_item.get("free", balance_item.get("available", 0))
                    await self.balance_tracker.update_balance(
                        asset=balance_item.get("asset", "").upper(),
                        available=Decimal(str(available)),
                        locked=Decimal(str(balance_item.get("locked", 0))),
                        reason=BalanceUpdateReason.INITIAL,
                    )
            else:
                # Format: {"USDM": {"available": "...", "locked": "..."}, ...}
                for asset, balance_info in balances_data.items():
                    if isinstance(balance_info, dict):
                        await self.balance_tracker.update_balance(
                            asset=asset.upper(),
                            available=Decimal(str(balance_info.get("available", 0))),
                            locked=Decimal(str(balance_info.get("locked", 0))),
                            reason=BalanceUpdateReason.INITIAL,
                        )

            logger.info(
                "Current balances fetched and updated",
                balance_count=len(self.balance_tracker.current_balances),
            )

        except Exception as e:
            logger.warning(
                "Failed to fetch current balances from API - will rely on WebSocket updates",
                error=str(e),
            )

    async def _start_websocket(self):
        """Start DeltaDeFi account WebSocket connection"""
        try:
            self.account_ws = AccountWebSocket(self.deltadefi_client._client)

            # Register message handlers
            self.account_ws.add_account_callback(self._handle_account_update)

            await self.account_ws.start()

            logger.info("Account WebSocket connection established")
            self.connection_retry_count = 0

        except Exception as e:
            logger.warning(
                "WebSocket connection failed, continuing without real-time account updates",
                error=str(e),
            )
            # Don't call _handle_websocket_error immediately - let the bot continue
            # We can still do market making without real-time account updates
            # The REST API can be used for balance checks if needed

    async def _handle_websocket_error(self):
        """Handle WebSocket connection errors with exponential backoff"""
        if not self.running:
            return

        self.connection_retry_count += 1

        if self.connection_retry_count > self.max_retries:
            logger.error(
                "Max WebSocket retry attempts reached, stopping Account Manager"
            )
            await self.stop()
            return

        # Exponential backoff
        retry_delay = min(2**self.connection_retry_count, 60)
        logger.warning(
            "WebSocket reconnection attempt",
            retry_count=self.connection_retry_count,
            delay_seconds=retry_delay,
        )

        await asyncio.sleep(retry_delay)

        if self.running:
            await self._start_websocket()

    async def _handle_account_update(self, message: dict[str, Any]):
        """Handle general account update messages"""
        try:
            logger.debug("Account update received", message=message)

            # Process different types of account updates
            # Note: DeltaDeFi SDK uses 'sub_type' field for message type
            update_type = message.get("sub_type", message.get("type", ""))

            if update_type == "balance_update" or update_type == "balanceUpdate":
                await self._process_balance_message(message)
            elif update_type == "order_update" or update_type == "orderUpdate":
                await self._process_order_message(message)
            elif update_type == "fill" or update_type == "trade":
                await self._handle_fill_update(message)
            elif update_type == "trading_history":
                # Trading history contains fill/execution records
                await self._handle_trading_history_update(message)
            elif update_type in ["orders_history", "positions"]:
                # Historical data messages on initial connection - can be ignored or logged at debug level
                logger.debug(
                    "Received historical data message",
                    sub_type=update_type,
                    data_count=message.get("total_count", 0),
                )
            else:
                logger.info(
                    "Unknown account update type - logging for debugging",
                    sub_type=message.get("sub_type"),
                    type=message.get("type"),
                    message_keys=list(message.keys()),
                )

            # Notify callbacks
            await self._notify_account_callbacks(message)

        except Exception as e:
            logger.error("Error handling account update", error=str(e), message=message)

    async def _handle_fill_update(self, message: dict[str, Any]):
        """Handle fill/execution messages"""
        try:
            fill = AccountFill.from_websocket_data(message)

            logger.info(
                "Fill received from WebSocket",
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=float(fill.quantity),
                price=float(fill.price),
            )

            # Process fill through reconciler
            success = await self.fill_reconciler.process_fill(fill)

            if not success:
                logger.warning("Fill processing failed", fill_id=fill.fill_id)

        except Exception as e:
            logger.error("Error handling fill update", error=str(e), message=message)

    async def _handle_trading_history_update(self, message: dict[str, Any]):
        """Handle trading history messages containing fill records

        Trading history messages contain execution/fill records in this format:
        {
            "type": "Account",
            "sub_type": "trading_history",
            "data": [{
                "execution_id": "...",
                "order_id": "...",
                "symbol": "ADAUSDM",
                "executed_qty": "10",
                "executed_price": 0.75,
                "side": "buy",
                "fee_charged": "0.01",
                "fee_unit": "USDM",
                "created_time": 1234567890
            }, ...]
        }
        """
        try:
            # Extract fill records from data array
            data = message.get("data", [])

            if not data:
                logger.debug("Trading history message with no data", message=message)
                return

            # Process each page of data
            # Structure: data is an array where each element has:
            # - "orders": array of orders with nested "fills"
            # - "order_filling_records": array of execution records
            fills_processed = 0
            for page_data in data:
                try:
                    # Extract fill records from order_filling_records array
                    order_filling_records = page_data.get("order_filling_records", [])

                    for fill_record in order_filling_records:
                        try:
                            # Create AccountFill from the execution record
                            fill = AccountFill.from_websocket_data(fill_record)

                            logger.info(
                                "Fill received from order_filling_records",
                                fill_id=fill.fill_id,
                                order_id=fill.order_id,
                                symbol=fill.symbol,
                                side=fill.side,
                                quantity=float(fill.quantity),
                                price=float(fill.price),
                            )

                            # Process fill through reconciler
                            success = await self.fill_reconciler.process_fill(fill)

                            if success:
                                fills_processed += 1
                            else:
                                logger.warning(
                                    "Fill processing failed", fill_id=fill.fill_id
                                )

                        except Exception as e:
                            logger.error(
                                "Error processing order_filling_record",
                                error=str(e),
                                record=fill_record,
                            )

                    # Also extract fills from nested orders array
                    orders = page_data.get("orders", [])
                    for order in orders:
                        fills = order.get("fills", [])
                        for fill_data in fills:
                            try:
                                # Augment fill_data with order-level information
                                fill_data_with_order_info = {
                                    "id": fill_data.get("id"),
                                    "order_id": fill_data.get("order_id"),
                                    "execution_price": fill_data.get("execution_price"),
                                    "filled_amount": fill_data.get("filled_amount"),
                                    "fee_unit": fill_data.get("fee_unit"),
                                    "fee_amount": fill_data.get("fee_amount"),
                                    "role": fill_data.get("role"),
                                    "create_time": fill_data.get("create_time"),
                                    # Add from parent order
                                    "symbol": order.get("symbol"),
                                    "side": order.get("side"),
                                }

                                # Create AccountFill (needs special handling for nested fills format)
                                fill = AccountFill(
                                    fill_id=str(fill_data.get("id", "")),
                                    order_id=str(fill_data.get("order_id", "")),
                                    symbol=order.get("symbol", "").upper(),
                                    side=order.get("side", "").lower(),
                                    price=Decimal(str(fill_data.get("execution_price", 0))),
                                    quantity=Decimal(str(fill_data.get("filled_amount", 0))),
                                    executed_at=float(fill_data.get("create_time", time.time())),
                                    trade_id=str(fill_data.get("id", "")),
                                    commission=Decimal(str(fill_data.get("fee_amount", 0))),
                                    commission_asset=fill_data.get("fee_unit", ""),
                                    is_maker=fill_data.get("role", "maker") == "maker",
                                )

                                logger.info(
                                    "Fill received from order fills array",
                                    fill_id=fill.fill_id,
                                    order_id=fill.order_id,
                                    symbol=fill.symbol,
                                    side=fill.side,
                                    quantity=float(fill.quantity),
                                    price=float(fill.price),
                                )

                                # Process fill through reconciler
                                success = await self.fill_reconciler.process_fill(fill)

                                if success:
                                    fills_processed += 1
                                else:
                                    logger.warning(
                                        "Fill processing failed", fill_id=fill.fill_id
                                    )

                            except Exception as e:
                                logger.error(
                                    "Error processing nested fill from order",
                                    error=str(e),
                                    fill_data=fill_data,
                                )

                except Exception as e:
                    logger.error(
                        "Error processing page data",
                        error=str(e),
                        page_data=page_data,
                    )

            logger.info(
                "Trading history processed",
                total_records=len(data),
                fills_processed=fills_processed,
            )

        except Exception as e:
            logger.error(
                "Error handling trading history update", error=str(e), message=message
            )

    async def _handle_balance_update(self, message: dict[str, Any]):
        """Handle balance update messages"""
        try:
            balances = message.get("balances", {})

            if balances:
                await self.balance_tracker.update_from_websocket_data(balances)

                logger.debug(
                    "Balance update processed", updated_assets=list(balances.keys())
                )

        except Exception as e:
            logger.error("Error handling balance update", error=str(e), message=message)

    async def _process_balance_message(self, message: dict[str, Any]):
        """Process balance-specific messages"""
        # Implementation for specific balance message formats

    async def _process_order_message(self, message: dict[str, Any]):
        """Process order-specific messages"""
        # Implementation for order update messages

    async def _notify_account_callbacks(self, message: dict[str, Any]):
        """Notify account update callbacks"""
        for callback in self.account_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error(
                    "Error in account callback",
                    callback=callback.__name__,
                    error=str(e),
                )

    async def refresh_balances(self):
        """Manually refresh balances from DeltaDeFi API"""
        try:
            # Get balances from REST API
            balance_data = await self.deltadefi_client.get_account_info()

            if "balances" in balance_data:
                await self.balance_tracker.update_from_websocket_data(
                    balance_data["balances"]
                )
                logger.info("Balances refreshed from API")

        except Exception as e:
            logger.error("Failed to refresh balances", error=str(e))

    def get_account_summary(self) -> dict[str, Any]:
        """Get comprehensive account summary"""
        balances = self.balance_tracker.get_all_balances()

        return {
            "running": self.running,
            "websocket_connected": self.account_ws.is_connected
            if self.account_ws
            else False,
            "connection_retry_count": self.connection_retry_count,
            "balance_count": len(balances),
            "balances": {
                asset: {
                    "available": float(balance.available),
                    "locked": float(balance.locked),
                    "total": float(balance.total),
                }
                for asset, balance in balances.items()
            },
            "total_value_usd": float(self.balance_tracker.get_total_value_usd()),
            "fills_processed": len(self.fill_reconciler.processed_fills),
        }
