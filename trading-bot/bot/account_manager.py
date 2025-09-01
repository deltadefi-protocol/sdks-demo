"""
Account State Management

This module implements comprehensive account state management including:
- WebSocket feed processing for real-time account updates
- Balance tracking with historical snapshots
- Fill reconciliation and position management
- Account health monitoring and alerting
"""

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

import structlog

from .config import settings
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
    trade_id: Optional[str] = None
    commission: Decimal = Decimal("0")
    commission_asset: str = ""
    is_maker: bool = True
    status: FillStatus = FillStatus.RECEIVED
    received_at: float = field(default_factory=time.time)
    processed_at: Optional[float] = None
    
    @classmethod
    def from_websocket_data(cls, data: Dict[str, Any]) -> 'AccountFill':
        """Create AccountFill from DeltaDeFi WebSocket message"""
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
            is_maker=bool(data.get("isMaker", True))
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
    def from_websocket_data(cls, asset: str, data: Dict[str, Any]) -> 'AccountBalance':
        """Create AccountBalance from DeltaDeFi WebSocket message"""
        available = Decimal(str(data.get("available", 0)))
        locked = Decimal(str(data.get("locked", 0)))
        
        return cls(
            asset=asset,
            available=available,
            locked=locked,
            total=available + locked
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
        self.current_balances: Dict[str, AccountBalance] = {}
        self.balance_callbacks: List[Callable] = []
        self._balance_lock = asyncio.Lock()
    
    def add_balance_callback(self, callback: Callable):
        """Add callback for balance updates"""
        self.balance_callbacks.append(callback)
    
    async def update_balance(
        self, 
        asset: str, 
        available: Decimal, 
        locked: Decimal,
        reason: BalanceUpdateReason = BalanceUpdateReason.ADJUSTMENT
    ):
        """Update account balance"""
        async with self._balance_lock:
            old_balance = self.current_balances.get(asset)
            
            new_balance = AccountBalance(
                asset=asset,
                available=available,
                locked=locked,
                total=available + locked
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
                        reason=reason
                    )
            else:
                logger.info(
                    "Initial balance set",
                    asset=asset,
                    total=float(new_balance.total),
                    reason=reason
                )
            
            # Notify callbacks
            await self._notify_balance_callbacks(new_balance, reason)
    
    async def update_from_websocket_data(self, balances: Dict[str, Dict[str, Any]]):
        """Update balances from WebSocket account update"""
        for asset, balance_data in balances.items():
            balance = AccountBalance.from_websocket_data(asset, balance_data)
            await self.update_balance(
                asset,
                balance.available,
                balance.locked,
                BalanceUpdateReason.ADJUSTMENT
            )
    
    def get_balance(self, asset: str) -> Optional[AccountBalance]:
        """Get current balance for asset"""
        return self.current_balances.get(asset)
    
    def get_all_balances(self) -> Dict[str, AccountBalance]:
        """Get all current balances"""
        return self.current_balances.copy()
    
    def get_total_value_usd(self) -> Decimal:
        """Get total portfolio value in USD (requires price feeds)"""
        # TODO: Implement with price conversion
        usd_balance = self.current_balances.get("USD", AccountBalance("USD", Decimal("0"), Decimal("0"), Decimal("0")))
        return usd_balance.total
    
    async def _persist_balance(self, balance: AccountBalance):
        """Persist balance to database"""
        try:
            query = """
            INSERT OR REPLACE INTO account_balances (asset, available, locked, total, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """
            
            async with db_manager.get_connection() as conn:
                await conn.execute(query, (
                    balance.asset,
                    float(balance.available),
                    float(balance.locked),
                    float(balance.total),
                    balance.updated_at
                ))
                await conn.commit()
                
        except Exception as e:
            logger.error("Failed to persist balance", asset=balance.asset, error=str(e))
    
    async def _notify_balance_callbacks(self, balance: AccountBalance, reason: BalanceUpdateReason):
        """Notify balance update callbacks"""
        for callback in self.balance_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(balance, reason)
                else:
                    callback(balance, reason)
            except Exception as e:
                logger.error("Error in balance callback", callback=callback.__name__, error=str(e))


class FillReconciler:
    """Reconciles fills with orders and updates positions"""
    
    def __init__(self, balance_tracker: BalanceTracker):
        self.balance_tracker = balance_tracker
        self.processed_fills: Set[str] = set()
        self.fill_callbacks: List[Callable] = []
        self.position_callbacks: List[Callable] = []
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
                    price=float(fill.price)
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
                logger.error("Fill processing failed", fill_id=fill.fill_id, error=str(e), exc_info=True)
                return False
    
    async def _persist_fill(self, fill: AccountFill):
        """Persist fill to database"""
        query = """
        INSERT OR REPLACE INTO fills (
            fill_id, order_id, symbol, side, price, quantity,
            executed_at, trade_id, commission, commission_asset,
            is_maker, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        async with db_manager.get_connection() as conn:
            await conn.execute(query, (
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
                fill.received_at
            ))
            await conn.commit()
    
    async def _update_position(self, fill: AccountFill) -> Optional[PositionUpdate]:
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
            elif (current_qty > 0 and quantity_delta > 0) or (current_qty < 0 and quantity_delta < 0):
                # Adding to position
                total_cost = (current_qty * current_avg_price) + (quantity_delta * fill.price)
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
                    "SELECT realized_pnl FROM positions WHERE symbol = ?", (fill.symbol,)
                )
                if current_realized_result:
                    current_realized = Decimal(str(current_realized_result["realized_pnl"]))
            
            async with db_manager.get_connection() as conn:
                await conn.execute(upsert_query, (
                    fill.symbol,
                    float(new_qty),
                    float(new_avg_price),
                    float(current_realized + realized_pnl),
                    time.time()
                ))
                await conn.commit()
            
            return PositionUpdate(
                symbol=fill.symbol,
                quantity_delta=quantity_delta,
                avg_price_update=new_avg_price,
                realized_pnl=realized_pnl,
                fill_id=fill.fill_id
            )
            
        except Exception as e:
            logger.error("Position update failed", fill_id=fill.fill_id, symbol=fill.symbol, error=str(e))
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
                    has_quote=quote_balance is not None
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
                BalanceUpdateReason.TRADE_FILL
            )
            
            await self.balance_tracker.update_balance(
                quote_asset,
                quote_balance.available + quote_change,
                quote_balance.locked,
                BalanceUpdateReason.TRADE_FILL
            )
            
        except Exception as e:
            logger.error("Balance update from fill failed", fill_id=fill.fill_id, error=str(e))
    
    async def _update_fill_status(self, fill: AccountFill):
        """Update fill status in database"""
        query = "UPDATE fills SET status = ?, processed_at = ? WHERE fill_id = ?"
        
        async with db_manager.get_connection() as conn:
            await conn.execute(query, (fill.status, fill.processed_at, fill.fill_id))
            await conn.commit()
    
    async def _publish_fill_event(self, fill: AccountFill, position_update: Optional[PositionUpdate]):
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
                    "avg_price": float(position_update.avg_price_update)
                } if position_update else None
            }
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
                logger.error("Error in fill callback", callback=callback.__name__, error=str(e))
    
    async def _notify_position_callbacks(self, position_update: PositionUpdate):
        """Notify position callbacks"""
        for callback in self.position_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(position_update)
                else:
                    callback(position_update)
            except Exception as e:
                logger.error("Error in position callback", callback=callback.__name__, error=str(e))


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
        self.account_ws: Optional[AccountWebSocket] = None
        
        # State
        self.running = False
        self.connection_retry_count = 0
        self.max_retries = 5
        
        # Callbacks
        self.account_callbacks: List[Callable] = []
        
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
                    total=Decimal(str(row["total"]))
                )
                self.balance_tracker.current_balances[balance.asset] = balance
            
            logger.info(
                "Initial balances loaded",
                balance_count=len(self.balance_tracker.current_balances)
            )
            
        except Exception as e:
            logger.error("Failed to load initial balances", error=str(e))
    
    async def _start_websocket(self):
        """Start DeltaDeFi account WebSocket connection"""
        try:
            self.account_ws = AccountWebSocket(self.deltadefi_client._client)
            
            # Register message handlers
            self.account_ws.add_message_handler(self._handle_account_update)
            self.account_ws.add_fill_handler(self._handle_fill_update)
            self.account_ws.add_balance_handler(self._handle_balance_update)
            
            await self.account_ws.start()
            
            logger.info("Account WebSocket connection established")
            self.connection_retry_count = 0
            
        except Exception as e:
            logger.error("WebSocket connection failed", error=str(e))
            await self._handle_websocket_error()
    
    async def _handle_websocket_error(self):
        """Handle WebSocket connection errors with exponential backoff"""
        if not self.running:
            return
        
        self.connection_retry_count += 1
        
        if self.connection_retry_count > self.max_retries:
            logger.error("Max WebSocket retry attempts reached, stopping Account Manager")
            await self.stop()
            return
        
        # Exponential backoff
        retry_delay = min(2 ** self.connection_retry_count, 60)
        logger.warning(
            "WebSocket reconnection attempt",
            retry_count=self.connection_retry_count,
            delay_seconds=retry_delay
        )
        
        await asyncio.sleep(retry_delay)
        
        if self.running:
            await self._start_websocket()
    
    async def _handle_account_update(self, message: Dict[str, Any]):
        """Handle general account update messages"""
        try:
            logger.debug("Account update received", message=message)
            
            # Process different types of account updates
            update_type = message.get("type", "")
            
            if update_type == "balance_update":
                await self._process_balance_message(message)
            elif update_type == "order_update":
                await self._process_order_message(message)
            else:
                logger.debug("Unknown account update type", type=update_type, message=message)
            
            # Notify callbacks
            await self._notify_account_callbacks(message)
            
        except Exception as e:
            logger.error("Error handling account update", error=str(e), message=message)
    
    async def _handle_fill_update(self, message: Dict[str, Any]):
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
                price=float(fill.price)
            )
            
            # Process fill through reconciler
            success = await self.fill_reconciler.process_fill(fill)
            
            if not success:
                logger.warning("Fill processing failed", fill_id=fill.fill_id)
            
        except Exception as e:
            logger.error("Error handling fill update", error=str(e), message=message)
    
    async def _handle_balance_update(self, message: Dict[str, Any]):
        """Handle balance update messages"""
        try:
            balances = message.get("balances", {})
            
            if balances:
                await self.balance_tracker.update_from_websocket_data(balances)
                
                logger.debug(
                    "Balance update processed",
                    updated_assets=list(balances.keys())
                )
        
        except Exception as e:
            logger.error("Error handling balance update", error=str(e), message=message)
    
    async def _process_balance_message(self, message: Dict[str, Any]):
        """Process balance-specific messages"""
        # Implementation for specific balance message formats
        pass
    
    async def _process_order_message(self, message: Dict[str, Any]):
        """Process order-specific messages"""
        # Implementation for order update messages
        pass
    
    async def _notify_account_callbacks(self, message: Dict[str, Any]):
        """Notify account update callbacks"""
        for callback in self.account_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error("Error in account callback", callback=callback.__name__, error=str(e))
    
    async def refresh_balances(self):
        """Manually refresh balances from DeltaDeFi API"""
        try:
            # Get balances from REST API
            balance_data = await self.deltadefi_client.get_account_info()
            
            if "balances" in balance_data:
                await self.balance_tracker.update_from_websocket_data(balance_data["balances"])
                logger.info("Balances refreshed from API")
            
        except Exception as e:
            logger.error("Failed to refresh balances", error=str(e))
    
    def get_account_summary(self) -> Dict[str, Any]:
        """Get comprehensive account summary"""
        balances = self.balance_tracker.get_all_balances()
        
        return {
            "running": self.running,
            "websocket_connected": self.account_ws and self.account_ws.connected if self.account_ws else False,
            "connection_retry_count": self.connection_retry_count,
            "balance_count": len(balances),
            "balances": {
                asset: {
                    "available": float(balance.available),
                    "locked": float(balance.locked),
                    "total": float(balance.total)
                }
                for asset, balance in balances.items()
            },
            "total_value_usd": float(self.balance_tracker.get_total_value_usd()),
            "fills_processed": len(self.fill_reconciler.processed_fills)
        }