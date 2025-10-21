"""
Quote engine for calculating bid/ask prices with spread adjustments
Handles BPS calculations, price clamping, and don't-cross protection
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
import time
from typing import Any

import structlog

from .asset_ratio_manager import AssetRatioManager
from .config import settings

logger = structlog.get_logger()


@dataclass
class BookTicker:
    """Binance book ticker data"""

    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    timestamp: float


@dataclass
class LayeredQuote:
    """Single layer quote for DeltaDeFi"""

    layer: int
    price: float
    quantity: float
    spread_bps: float


@dataclass
class Quote:
    """Generated multi-layer quote for DeltaDeFi"""

    symbol: str
    bid_layers: list[LayeredQuote] | None
    ask_layers: list[LayeredQuote] | None
    timestamp: float
    source_data: BookTicker

    # Legacy single-layer support for backwards compatibility
    bid_price: float | None = None
    bid_qty: float | None = None
    ask_price: float | None = None
    ask_qty: float | None = None

    def __post_init__(self):
        """Set legacy fields from first layer for backwards compatibility"""
        if self.bid_layers and len(self.bid_layers) > 0:
            self.bid_price = self.bid_layers[0].price
            self.bid_qty = self.bid_layers[0].quantity

        if self.ask_layers and len(self.ask_layers) > 0:
            self.ask_price = self.ask_layers[0].price
            self.ask_qty = self.ask_layers[0].quantity

    @property
    def spread_bps(self) -> float | None:
        """Calculate spread in basis points (from first layer)"""
        if self.bid_price and self.ask_price:
            mid = (self.bid_price + self.ask_price) / 2
            spread = self.ask_price - self.bid_price
            return (spread / mid) * 10000
        return None

    @property
    def mid_price(self) -> float | None:
        """Calculate mid price"""
        if self.bid_price and self.ask_price:
            return (self.bid_price + self.ask_price) / 2
        return None


class QuoteEngine:
    """
    Core quote generation engine

    Takes Binance book ticker data and generates DeltaDeFi quotes
    with configurable spreads and risk controls
    """

    def __init__(self, asset_ratio_manager: AssetRatioManager | None = None):
        self.last_quote_time = 0.0
        self.last_source_prices: BookTicker | None = None
        self._precision = 6  # Price precision for rounding
        self.asset_ratio_manager = asset_ratio_manager or AssetRatioManager()

    def generate_quote(self, book_ticker: BookTicker) -> Quote | None:
        """
        Generate a DeltaDeFi quote from Binance book ticker data

        Args:
            book_ticker: Binance market data

        Returns:
            Quote object or None if generation should be skipped
        """
        current_time = time.time()

        logger.debug(
            "🔍 Quote generation called",
            symbol=book_ticker.symbol,
            bid=book_ticker.bid_price,
            ask=book_ticker.ask_price,
            time_since_last_quote_ms=(current_time - self.last_quote_time) * 1000
            if self.last_quote_time > 0
            else None,
        )

        # Check if we should skip requoting based on time threshold
        if self._should_skip_requote(book_ticker, current_time):
            logger.debug("⏭️  Quote generation skipped by _should_skip_requote check")
            return None

        # Check if data is stale
        if self._is_data_stale(book_ticker, current_time):
            logger.warning(
                "Market data is stale, skipping quote generation",
                age_ms=(current_time - book_ticker.timestamp) * 1000,
            )
            return None

        # Generate multi-layer quotes
        bid_layers = self._generate_bid_layers(book_ticker)
        ask_layers = self._generate_ask_layers(book_ticker)

        # Calculate time since last quote BEFORE updating timestamp
        time_since_last_quote_ms = (
            round((current_time - self.last_quote_time) * 1000, 2)
            if self.last_quote_time > 0
            else None
        )

        # Update state
        self.last_quote_time = current_time
        self.last_source_prices = book_ticker

        quote = Quote(
            symbol=settings.trading.symbol_dst,
            bid_layers=bid_layers,
            ask_layers=ask_layers,
            timestamp=current_time,
            source_data=book_ticker,
        )

        logger.info(
            "✅ Quote generation SUCCESSFUL",
            symbol=quote.symbol,
            bid_layers_count=len(bid_layers) if bid_layers else 0,
            ask_layers_count=len(ask_layers) if ask_layers else 0,
            first_layer_spread_bps=f"{quote.spread_bps:.2f}"
            if quote.spread_bps
            else None,
            source_bid=book_ticker.bid_price,
            source_ask=book_ticker.ask_price,
            time_since_last_quote_ms=time_since_last_quote_ms,
        )

        return quote

    def _generate_bid_layers(
        self, book_ticker: BookTicker
    ) -> list[LayeredQuote] | None:
        """Generate multi-layer bid quotes with ratio adjustments"""
        if not settings.is_side_enabled("bid"):
            return None

        bid_layers = []
        bid_reference_price = book_ticker.bid_price

        # Get ratio adjustments
        ratio_adjustment = self.asset_ratio_manager.get_ratio_adjustment()
        bid_alloc, ask_alloc = self.asset_ratio_manager.get_capital_allocation()

        # Calculate base layer notional with capital allocation
        total_available_liquidity = settings.trading.total_liquidity * bid_alloc
        base_layer_notional = total_available_liquidity / settings.trading.num_layers

        for layer_i in range(1, settings.trading.num_layers + 1):
            # Calculate base spread for this layer
            base_spread_bps = (
                settings.trading.base_spread_bps
                + (layer_i - 1) * settings.trading.tick_spread_bps
            )

            # Apply ratio-based spread adjustment
            adjusted_spread_bps = (
                base_spread_bps * ratio_adjustment.bid_spread_multiplier
            )

            # Calculate price according to spec: bid_reference_price * (1 - spread_bps/10000)
            layer_price = bid_reference_price * (1 - adjusted_spread_bps / 10000)

            # Calculate quantity with progressive growth and ratio adjustment
            growth_factor = (
                1 + (layer_i - 1) * settings.trading.layer_liquidity_multiplier
            )
            base_quantity = (base_layer_notional * growth_factor) / layer_price
            layer_quantity = base_quantity * ratio_adjustment.bid_liquidity_multiplier

            # Apply minimum size constraint
            if layer_quantity < settings.trading.min_quote_size:
                layer_quantity = settings.trading.min_quote_size

            # Round to appropriate precision
            layer_price = round(layer_price, self._precision)
            layer_quantity = round(layer_quantity, 2)

            bid_layers.append(
                LayeredQuote(
                    layer=layer_i,
                    price=layer_price,
                    quantity=layer_quantity,
                    spread_bps=adjusted_spread_bps,
                )
            )

        return bid_layers

    def _generate_ask_layers(
        self, book_ticker: BookTicker
    ) -> list[LayeredQuote] | None:
        """Generate multi-layer ask quotes with ratio adjustments"""
        if not settings.is_side_enabled("ask"):
            return None

        ask_layers = []
        ask_reference_price = book_ticker.ask_price

        # Get ratio adjustments
        ratio_adjustment = self.asset_ratio_manager.get_ratio_adjustment()
        bid_alloc, ask_alloc = self.asset_ratio_manager.get_capital_allocation()

        # Calculate base layer notional with capital allocation
        total_available_liquidity = settings.trading.total_liquidity * ask_alloc
        base_layer_notional = total_available_liquidity / settings.trading.num_layers

        for layer_i in range(1, settings.trading.num_layers + 1):
            # Calculate base spread for this layer
            base_spread_bps = (
                settings.trading.base_spread_bps
                + (layer_i - 1) * settings.trading.tick_spread_bps
            )

            # Apply ratio-based spread adjustment
            adjusted_spread_bps = (
                base_spread_bps * ratio_adjustment.ask_spread_multiplier
            )

            # Calculate price according to spec: ask_reference_price * (1 + spread_bps/10000)
            layer_price = ask_reference_price * (1 + adjusted_spread_bps / 10000)

            # Calculate quantity with progressive growth and ratio adjustment
            growth_factor = (
                1 + (layer_i - 1) * settings.trading.layer_liquidity_multiplier
            )
            base_quantity = (base_layer_notional * growth_factor) / layer_price
            layer_quantity = base_quantity * ratio_adjustment.ask_liquidity_multiplier

            # Apply minimum size constraint
            if layer_quantity < settings.trading.min_quote_size:
                layer_quantity = settings.trading.min_quote_size

            # Round to appropriate precision
            layer_price = round(layer_price, self._precision)
            layer_quantity = round(layer_quantity, 2)

            ask_layers.append(
                LayeredQuote(
                    layer=layer_i,
                    price=layer_price,
                    quantity=layer_quantity,
                    spread_bps=adjusted_spread_bps,
                )
            )

        return ask_layers

    def _calculate_bid(
        self, book_ticker: BookTicker
    ) -> tuple[float | None, float | None]:
        """Legacy method - Calculate bid price and quantity"""
        if not settings.is_side_enabled("bid"):
            return None, None

        # Calculate bid price with spread adjustment
        total_bps = settings.total_spread_bps
        bid_price = book_ticker.bid_price * (1 - total_bps / 10000)

        # Round to appropriate precision
        bid_price = self._round_price(bid_price)

        # Calculate order size based on max position size and max orders
        # Each order should be roughly max_position_size / max_open_orders
        max_orders = settings.risk.max_open_orders
        target_notional_per_order = settings.risk.max_position_size / max_orders

        # Calculate quantity based on target notional and bid price
        bid_qty = target_notional_per_order / bid_price

        # Apply minimum size constraints
        bid_qty = max(bid_qty, settings.trading.min_quote_size)

        # Apply max order size limit only if configured (qty > 0)
        # If qty is 0, use full calculated size to maximize capital utilization
        if hasattr(settings.trading, "qty") and settings.trading.qty > 0:
            bid_qty = min(bid_qty, settings.trading.qty)

        return bid_price, bid_qty

    def _calculate_ask(
        self, book_ticker: BookTicker
    ) -> tuple[float | None, float | None]:
        """Calculate ask price and quantity"""
        if not settings.is_side_enabled("ask"):
            return None, None

        # Calculate ask price with spread adjustment
        total_bps = settings.total_spread_bps
        ask_price = book_ticker.ask_price * (1 + total_bps / 10000)

        # Round to appropriate precision
        ask_price = self._round_price(ask_price)

        # Calculate order size based on max position size and max orders
        # Each order should be roughly max_position_size / max_open_orders
        max_orders = settings.risk.max_open_orders
        target_notional_per_order = settings.risk.max_position_size / max_orders

        # Calculate quantity based on target notional and ask price
        ask_qty = target_notional_per_order / ask_price

        # Apply minimum size constraints
        ask_qty = max(ask_qty, settings.trading.min_quote_size)

        # Apply max order size limit only if configured (qty > 0)
        # If qty is 0, use full calculated size to maximize capital utilization
        if hasattr(settings.trading, "qty") and settings.trading.qty > 0:
            ask_qty = min(ask_qty, settings.trading.qty)

        return ask_price, ask_qty

    def _round_price(self, price: float) -> float:
        """Round price to appropriate precision"""
        decimal_price = Decimal(str(price))
        rounded = decimal_price.quantize(
            Decimal("0." + "0" * self._precision), rounding=ROUND_HALF_UP
        )
        return float(rounded)

    def _should_skip_requote(
        self, book_ticker: BookTicker, current_time: float
    ) -> bool:
        """Check if we should skip requoting based on thresholds"""
        # Check minimum time threshold
        time_since_last_quote = (current_time - self.last_quote_time) * 1000  # ms
        if time_since_last_quote < settings.trading.min_requote_ms:
            logger.debug(
                "⏱️  Skipping requote: time threshold not met",
                time_since_last_quote_ms=round(time_since_last_quote, 2),
                min_requote_ms=settings.trading.min_requote_ms,
                time_remaining_ms=round(
                    settings.trading.min_requote_ms - time_since_last_quote, 2
                ),
            )
            return True

        # Check price movement threshold
        if self.last_source_prices:
            bid_change = abs(book_ticker.bid_price - self.last_source_prices.bid_price)
            ask_change = abs(book_ticker.ask_price - self.last_source_prices.ask_price)
            max_change = max(bid_change, ask_change)

            # Per spec: trigger when price moves >= tick_spread_bps / 2
            min_price_change = (
                settings.trading.tick_spread_bps / 2
            ) / 10000  # Convert bps to decimal

            if max_change < min_price_change:
                # Calculate the percentage change for logging
                mid_price = (book_ticker.bid_price + book_ticker.ask_price) / 2
                max_change_bps = (max_change / mid_price) * 10000

                logger.debug(
                    "📊 Skipping requote: price movement threshold not met",
                    bid_change=round(bid_change, 6),
                    ask_change=round(ask_change, 6),
                    max_change=round(max_change, 6),
                    max_change_bps=round(max_change_bps, 2),
                    min_price_change=round(min_price_change, 6),
                    min_price_change_bps=settings.trading.tick_spread_bps / 2,
                    current_bid=book_ticker.bid_price,
                    current_ask=book_ticker.ask_price,
                    last_bid=self.last_source_prices.bid_price,
                    last_ask=self.last_source_prices.ask_price,
                )
                return True

        return False

    def _is_data_stale(self, book_ticker: BookTicker, current_time: float) -> bool:
        """Check if market data is too old"""
        age_ms = (current_time - book_ticker.timestamp) * 1000
        return age_ms > settings.trading.stale_ms

    def _apply_dont_cross_protection(
        self, bid_price: float | None, ask_price: float | None
    ) -> tuple[float | None, float | None]:
        """
        Apply don't-cross protection (future enhancement)

        This would check DeltaDeFi order book to ensure we don't cross
        the existing top of book
        """
        # TODO: Implement DeltaDeFi market data integration
        # For now, just ensure our bid < ask
        if bid_price and ask_price and bid_price >= ask_price:
            logger.warning(
                "Generated bid >= ask, adjusting prices", bid=bid_price, ask=ask_price
            )
            # Simple adjustment: widen the spread
            mid = (bid_price + ask_price) / 2
            spread = settings.total_spread_bps / 10000
            bid_price = mid * (1 - spread / 2)
            ask_price = mid * (1 + spread / 2)

        return bid_price, ask_price

    def get_stats(self) -> dict[str, Any]:
        """Get quote engine statistics"""
        return {
            "last_quote_time": self.last_quote_time,
            "has_last_source_prices": self.last_source_prices is not None,
            "total_spread_bps": settings.total_spread_bps,
            "sides_enabled": settings.trading.side_enable,
        }


def create_book_ticker_from_binance(data: dict[str, Any]) -> BookTicker:
    """
    Create BookTicker from Binance WebSocket data

    Expected Binance format:
    {
        "u": 400900217,     # order book updateId
        "s": "BNBUSDT",     # symbol
        "b": "25.35190000", # best bid price
        "B": "31.21000000", # best bid qty
        "a": "25.36520000", # best ask price
        "A": "40.66000000"  # best ask qty
    }
    """
    return BookTicker(
        symbol=data["s"],
        bid_price=float(data["b"]),
        bid_qty=float(data["B"]),
        ask_price=float(data["a"]),
        ask_qty=float(data["A"]),
        timestamp=time.time(),  # Add local timestamp since Binance doesn't provide one
    )
