"""
Order Management System (OMS) with state machine and risk management

This module provides:
- Order state machine (idle -> working -> filled/cancelled)
- Position tracking and management
- Risk management integration
- Order lifecycle management
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import time

import structlog

from bot.config import settings

logger = structlog.get_logger()


class OrderState(str, Enum):
    """Order states in the OMS state machine"""

    IDLE = "idle"
    PENDING = "pending"
    WORKING = "working"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


class OrderSide(str, Enum):
    """Order side enumeration"""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type enumeration"""

    LIMIT = "limit"
    MARKET = "market"


class RiskCheckType(str, Enum):
    """Risk check types"""

    POSITION_SIZE = "position_size"
    DAILY_LOSS = "daily_loss"
    MAX_SKEW = "max_skew"
    MIN_QUANTITY = "min_quantity"
    MAX_OPEN_ORDERS = "max_open_orders"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class Position:
    """Position tracking data structure"""

    symbol: str
    quantity: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    last_update: float = field(default_factory=time.time)

    @property
    def notional_value(self) -> Decimal:
        """Calculate notional value of position"""
        return abs(self.quantity) * self.avg_price

    @property
    def is_long(self) -> bool:
        """Check if position is long"""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if position is short"""
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        """Check if position is flat (no position)"""
        return self.quantity == 0


@dataclass
class OMSOrder:
    """OMS Order with state tracking"""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    state: OrderState = OrderState.IDLE
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")
    created_time: float = field(default_factory=time.time)
    updated_time: float = field(default_factory=time.time)
    external_order_id: str | None = None
    error_message: str | None = None
    fills: list[dict] = field(default_factory=list)

    @property
    def remaining_quantity(self) -> Decimal:
        """Get remaining quantity to be filled"""
        return self.quantity - self.filled_quantity

    @property
    def is_complete(self) -> bool:
        """Check if order is in a terminal state"""
        return self.state in (
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.FAILED,
        )

    @property
    def fill_ratio(self) -> float:
        """Get fill ratio (0.0 to 1.0)"""
        if self.quantity == 0:
            return 0.0
        return float(self.filled_quantity / self.quantity)


class RiskManager:
    """Risk management component for OMS"""

    def __init__(self):
        self.daily_pnl = Decimal("0")
        self.daily_pnl_reset_time = time.time()
        self.open_order_count = 0

    def check_risk(self, order: OMSOrder, position: Position) -> tuple[bool, list[str]]:
        """
        Perform comprehensive risk checks

        Returns:
            tuple: (is_valid, list_of_violations)
        """
        violations = []

        # Emergency stop check
        if settings.risk.emergency_stop:
            violations.append("Emergency stop is active")

        # Position size check
        if position:
            new_position_size = abs(position.quantity)
            if order.side == OrderSide.BUY:
                new_position_size += order.quantity
            else:
                new_position_size = abs(position.quantity - order.quantity)

            if new_position_size > Decimal(str(settings.risk.max_position_size)):
                violations.append(
                    f"Position size would exceed limit: {new_position_size} > {settings.risk.max_position_size}"
                )

        # Daily loss check
        self._update_daily_pnl()
        if self.daily_pnl <= -Decimal(str(settings.risk.max_daily_loss)):
            violations.append(f"Daily loss limit exceeded: {self.daily_pnl}")

        # Max skew check (for market making)
        if (
            position
            and hasattr(settings.trading, "max_skew")
            and abs(position.quantity) > Decimal(str(settings.trading.max_skew))
        ):
            violations.append(f"Position skew too large: {position.quantity}")

        # Minimum quantity check
        if hasattr(settings.trading, "min_quote_size") and order.quantity < Decimal(
            str(settings.trading.min_quote_size)
        ):
            violations.append(f"Order quantity below minimum: {order.quantity}")

        # Max open orders check (configurable limit)
        max_orders = settings.risk.max_open_orders
        if self.open_order_count >= max_orders:
            violations.append(
                f"Too many open orders: {self.open_order_count}/{max_orders}"
            )

        return len(violations) == 0, violations

    def _update_daily_pnl(self):
        """Update daily PnL tracking with reset at midnight"""
        current_time = time.time()
        # Reset daily PnL at midnight (simplified)
        if current_time - self.daily_pnl_reset_time > 86400:
            self.daily_pnl = Decimal("0")
            self.daily_pnl_reset_time = current_time

    def update_pnl(self, pnl_change: Decimal):
        """Update daily PnL tracking"""
        self.daily_pnl += pnl_change


class OrderManagementSystem:
    """
    Main OMS class implementing state machine and position tracking
    """

    def __init__(self):
        self.orders: dict[str, OMSOrder] = {}
        self.positions: dict[str, Position] = {}
        self.risk_manager = RiskManager()

        # Event callbacks
        self.order_callbacks: list[Callable] = []
        self.position_callbacks: list[Callable] = []

        # State machine transitions
        self.valid_transitions = {
            OrderState.IDLE: [OrderState.PENDING, OrderState.REJECTED],
            OrderState.PENDING: [
                OrderState.WORKING,
                OrderState.REJECTED,
                OrderState.FAILED,
            ],
            OrderState.WORKING: [
                OrderState.FILLED,
                OrderState.CANCELLED,
                OrderState.REJECTED,
            ],
            # Terminal states can't transition
            OrderState.FILLED: [],
            OrderState.CANCELLED: [],
            OrderState.REJECTED: [],
            OrderState.FAILED: [],
        }

        logger.info("OMS initialized")

    def add_order_callback(self, callback: Callable):
        """Add callback for order events"""
        self.order_callbacks.append(callback)

    def add_position_callback(self, callback: Callable):
        """Add callback for position events"""
        self.position_callbacks.append(callback)

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        order_id: str | None = None,
    ) -> OMSOrder:
        """
        Submit a new order through OMS with risk checks

        Returns:
            OMSOrder: The created order

        Raises:
            ValueError: If risk checks fail
        """
        if order_id is None:
            order_id = f"oms_{int(time.time() * 1000000)}"

        # Create order
        order = OMSOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )

        # Get current position
        position = self.positions.get(symbol)

        # Risk checks
        is_valid, violations = self.risk_manager.check_risk(order, position)
        if not is_valid:
            order.state = OrderState.REJECTED
            order.error_message = "; ".join(violations)
            self.orders[order_id] = order

            logger.warning(
                "Order rejected by risk management",
                order_id=order_id,
                violations=violations,
            )

            await self._notify_order_callbacks(order)
            raise ValueError(f"Order rejected: {'; '.join(violations)}")

        # Transition to pending state
        await self._transition_order_state(order, OrderState.PENDING)
        self.orders[order_id] = order
        self.risk_manager.open_order_count += 1

        logger.info(
            "Order submitted through OMS",
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
        )

        return order

    async def update_order_state(self, order_id: str, new_state: OrderState, **kwargs):
        """
        Update order state with validation

        Args:
            order_id: Order ID to update
            new_state: New state to transition to
            **kwargs: Additional update data (external_order_id, error_message, etc.)
        """
        if order_id not in self.orders:
            logger.warning("Attempted to update unknown order", order_id=order_id)
            return

        order = self.orders[order_id]

        # Validate state transition
        if new_state not in self.valid_transitions.get(order.state, []):
            logger.error(
                "Invalid state transition",
                order_id=order_id,
                current_state=order.state,
                new_state=new_state,
            )
            return

        await self._transition_order_state(order, new_state, **kwargs)

    async def add_fill(
        self,
        order_id: str,
        fill_quantity: Decimal,
        fill_price: Decimal,
        trade_id: str | None = None,
        fee: Decimal = Decimal("0"),
        symbol: str | None = None,
        side: OrderSide | None = None,
    ):
        """
        Add a fill to an order and update position

        Args:
            order_id: Order ID that was filled
            fill_quantity: Quantity filled
            fill_price: Price of the fill
            trade_id: External trade ID
            fee: Trading fee
            symbol: Symbol for the fill (required if order not found)
            side: Side for the fill (required if order not found)
        """
        if order_id not in self.orders:
            # Order not tracked in OMS (may have been from previous run or external)
            # Still update position if we have symbol and side
            if symbol and side:
                logger.info(
                    "Fill for untracked order - updating position anyway",
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    trade_id=trade_id,
                    fill_quantity=fill_quantity,
                    fill_price=fill_price,
                )

                # Update position directly
                await self._update_position(
                    symbol, side, fill_quantity, fill_price, fee
                )

                return
            else:
                logger.warning(
                    "Fill for unknown order and no symbol/side provided",
                    order_id=order_id,
                    trade_id=trade_id,
                )
                return

        order = self.orders[order_id]

        # Validate fill
        if order.filled_quantity + fill_quantity > order.quantity:
            logger.error(
                "Fill quantity exceeds order quantity",
                order_id=order_id,
                fill_quantity=fill_quantity,
                already_filled=order.filled_quantity,
                order_quantity=order.quantity,
            )
            return

        # Add fill to order
        fill_data = {
            "quantity": fill_quantity,
            "price": fill_price,
            "timestamp": time.time(),
            "trade_id": trade_id,
            "fee": fee,
        }
        order.fills.append(fill_data)

        # Update order fill data
        old_notional = order.filled_quantity * order.avg_fill_price
        new_notional = old_notional + (fill_quantity * fill_price)
        order.filled_quantity += fill_quantity

        if order.filled_quantity > 0:
            order.avg_fill_price = new_notional / order.filled_quantity

        order.updated_time = time.time()

        # Update position
        await self._update_position(
            order.symbol, order.side, fill_quantity, fill_price, fee
        )

        # Check if order is fully filled
        if order.filled_quantity >= order.quantity:
            await self._transition_order_state(order, OrderState.FILLED)
            self.risk_manager.open_order_count -= 1

        logger.info(
            "Fill added to order",
            order_id=order_id,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            total_filled=order.filled_quantity,
            trade_id=trade_id,
        )

        await self._notify_order_callbacks(order)

    async def cancel_order(self, order_id: str, reason: str = "User requested"):
        """Cancel an order"""
        if order_id not in self.orders:
            logger.warning("Attempted to cancel unknown order", order_id=order_id)
            return

        order = self.orders[order_id]

        if order.is_complete:
            logger.warning(
                "Attempted to cancel completed order",
                order_id=order_id,
                state=order.state,
            )
            return

        await self._transition_order_state(
            order, OrderState.CANCELLED, error_message=reason
        )
        self.risk_manager.open_order_count -= 1

        logger.info("Order cancelled", order_id=order_id, reason=reason)

    async def _transition_order_state(
        self, order: OMSOrder, new_state: OrderState, **kwargs
    ):
        """Internal method to transition order state"""
        old_state = order.state
        order.state = new_state
        order.updated_time = time.time()

        # Update additional fields from kwargs
        if "external_order_id" in kwargs:
            order.external_order_id = kwargs["external_order_id"]
        if "error_message" in kwargs:
            order.error_message = kwargs["error_message"]

        # Decrement open order count for failed/rejected orders
        # (FILLED and CANCELLED are handled elsewhere)
        if new_state in [OrderState.FAILED, OrderState.REJECTED]:
            if self.risk_manager.open_order_count > 0:
                self.risk_manager.open_order_count -= 1
                logger.debug(
                    "Decremented open order count",
                    reason=f"Order {new_state.value}",
                    new_count=self.risk_manager.open_order_count,
                )

        logger.debug(
            "Order state transition",
            order_id=order.order_id,
            old_state=old_state,
            new_state=new_state,
        )

        await self._notify_order_callbacks(order)

    async def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
    ):
        """Update position based on fill"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)

        position = self.positions[symbol]

        # Calculate position change
        if side == OrderSide.BUY:
            quantity_delta = quantity
        else:
            quantity_delta = -quantity

        # Update position
        old_quantity = position.quantity

        # Calculate new average price
        if position.quantity == 0:
            # Opening position
            position.avg_price = price
        elif (position.quantity > 0 and side == OrderSide.BUY) or (
            position.quantity < 0 and side == OrderSide.SELL
        ):
            # Adding to position
            old_notional = position.quantity * position.avg_price
            new_notional = old_notional + (quantity_delta * price)
            position.avg_price = abs(
                new_notional / (position.quantity + quantity_delta)
            )
        else:
            # Reducing position - realize PnL
            fill_pnl = (
                quantity
                * (price - position.avg_price)
                * (-1 if side == OrderSide.SELL else 1)
            )
            position.realized_pnl += fill_pnl
            self.risk_manager.update_pnl(fill_pnl - fee)

        position.quantity += quantity_delta
        position.last_update = time.time()

        logger.info(
            "Position updated",
            symbol=symbol,
            old_quantity=old_quantity,
            new_quantity=position.quantity,
            avg_price=position.avg_price,
            side=side,
            fill_price=price,
        )

        await self._notify_position_callbacks(position)

    async def _notify_order_callbacks(self, order: OMSOrder):
        """Notify all order callbacks"""
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

    async def _notify_position_callbacks(self, position: Position):
        """Notify all position callbacks"""
        for callback in self.position_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(position)
                else:
                    callback(position)
            except Exception as e:
                logger.error(
                    "Error in position callback",
                    callback=callback.__name__,
                    error=str(e),
                )

    def get_order(self, order_id: str) -> OMSOrder | None:
        """Get order by ID"""
        return self.orders.get(order_id)

    def get_position(self, symbol: str) -> Position | None:
        """Get position for symbol"""
        return self.positions.get(symbol)

    def get_all_orders(
        self, symbol: str | None = None, state: OrderState | None = None
    ) -> list[OMSOrder]:
        """Get orders filtered by symbol and/or state"""
        orders = list(self.orders.values())

        if symbol:
            orders = [o for o in orders if o.symbol == symbol]

        if state:
            orders = [o for o in orders if o.state == state]

        return orders

    def get_open_orders(self, symbol: str | None = None) -> list[OMSOrder]:
        """Get open (working) orders"""
        return self.get_all_orders(symbol=symbol, state=OrderState.WORKING)

    def get_all_positions(self) -> list[Position]:
        """Get all positions"""
        return list(self.positions.values())

    def get_actual_open_order_count(self) -> int:
        """Get the actual count of open orders by checking order states"""
        open_count = 0
        for order in self.orders.values():
            if order.state == OrderState.WORKING:
                open_count += 1
        return open_count

    def sync_open_order_count(self) -> int:
        """Synchronize the risk manager's open order count with actual order states"""
        actual_count = self.get_actual_open_order_count()
        old_count = self.risk_manager.open_order_count
        self.risk_manager.open_order_count = actual_count

        if old_count != actual_count:
            logger.info(
                "Synchronized open order count",
                old_count=old_count,
                actual_count=actual_count,
                difference=actual_count - old_count,
            )

        return actual_count

    def get_portfolio_summary(self) -> dict:
        """Get portfolio summary"""
        total_notional = sum(pos.notional_value for pos in self.positions.values())
        total_realized_pnl = sum(pos.realized_pnl for pos in self.positions.values())

        return {
            "total_positions": len(self.positions),
            "open_orders": len(self.get_open_orders()),
            "total_notional": total_notional,
            "total_realized_pnl": total_realized_pnl,
            "daily_pnl": self.risk_manager.daily_pnl,
            "positions": {
                symbol: {
                    "quantity": pos.quantity,
                    "avg_price": pos.avg_price,
                    "notional": pos.notional_value,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "realized_pnl": pos.realized_pnl,
                }
                for symbol, pos in self.positions.items()
            },
        }
