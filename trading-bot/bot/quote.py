"""
Quote engine for calculating bid/ask prices with spread adjustments
Handles BPS calculations, price clamping, and don't-cross protection
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
import time
from typing import Any

import structlog

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
class Quote:
    """Generated quote for DeltaDeFi"""

    symbol: str
    bid_price: float | None
    bid_qty: float | None
    ask_price: float | None
    ask_qty: float | None
    timestamp: float
    source_data: BookTicker

    @property
    def spread_bps(self) -> float | None:
        """Calculate spread in basis points"""
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

    def __init__(self):
        self.last_quote_time = 0.0
        self.last_source_prices: BookTicker | None = None
        self._precision = 6  # Price precision for rounding

    def generate_quote(self, book_ticker: BookTicker) -> Quote | None:
        """
        Generate a DeltaDeFi quote from Binance book ticker data

        Args:
            book_ticker: Binance market data

        Returns:
            Quote object or None if generation should be skipped
        """
        current_time = time.time()

        # Check if we should skip requoting based on time threshold
        if self._should_skip_requote(book_ticker, current_time):
            return None

        # Check if data is stale
        if self._is_data_stale(book_ticker, current_time):
            logger.warning(
                "Market data is stale, skipping quote generation",
                age_ms=(current_time - book_ticker.timestamp) * 1000,
            )
            return None

        # Generate quotes for enabled sides
        bid_price, bid_qty = self._calculate_bid(book_ticker)
        ask_price, ask_qty = self._calculate_ask(book_ticker)

        # Apply don't-cross protection (optional future enhancement)
        bid_price, ask_price = self._apply_dont_cross_protection(bid_price, ask_price)

        # Update state
        self.last_quote_time = current_time
        self.last_source_prices = book_ticker

        quote = Quote(
            symbol=settings.trading.symbol_dst,
            bid_price=bid_price,
            bid_qty=bid_qty,
            ask_price=ask_price,
            ask_qty=ask_qty,
            timestamp=current_time,
            source_data=book_ticker,
        )

        logger.debug(
            "Generated quote",
            symbol=quote.symbol,
            bid=f"{bid_price:.{self._precision}f}" if bid_price else None,
            ask=f"{ask_price:.{self._precision}f}" if ask_price else None,
            spread_bps=f"{quote.spread_bps:.2f}" if quote.spread_bps else None,
            source_bid=book_ticker.bid_price,
            source_ask=book_ticker.ask_price,
        )

        return quote

    def _calculate_bid(
        self, book_ticker: BookTicker
    ) -> tuple[float | None, float | None]:
        """Calculate bid price and quantity"""
        if not settings.is_side_enabled("bid"):
            return None, None

        # Calculate bid price with spread adjustment
        total_bps = settings.total_spread_bps
        bid_price = book_ticker.bid_price * (1 - total_bps / 10000)

        # Round to appropriate precision
        bid_price = self._round_price(bid_price)

        # Apply size limits
        bid_qty = min(settings.trading.qty, settings.trading.min_quote_size)

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

        # Apply size limits
        ask_qty = min(settings.trading.qty, settings.trading.min_quote_size)

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
            return True

        # Check price movement threshold
        if self.last_source_prices:
            bid_change = abs(book_ticker.bid_price - self.last_source_prices.bid_price)
            ask_change = abs(book_ticker.ask_price - self.last_source_prices.ask_price)
            max_change = max(bid_change, ask_change)

            if max_change < settings.trading.requote_tick_threshold:
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
