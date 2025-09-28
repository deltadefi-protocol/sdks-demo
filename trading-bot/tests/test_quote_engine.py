"""
Tests for quote engine functionality
"""

import time
from unittest.mock import patch

import pytest

from bot.config import Settings
from bot.quote import (
    BookTicker,
    LayeredQuote,
    Quote,
    QuoteEngine,
    create_book_ticker_from_binance,
)


@pytest.fixture
def mock_settings():
    """Create mock settings for testing"""
    return Settings(
        exchange__deltadefi_api_key="test_key",
        trading__anchor_bps=5,
        trading__venue_spread_bps=3,
        trading__qty=100.0,
        trading__side_enable=["bid", "ask"],
    )


@pytest.fixture
def sample_book_ticker():
    """Create sample book ticker data"""
    return BookTicker(
        symbol="ADAUSDT",
        bid_price=1.0000,
        bid_qty=1000.0,
        ask_price=1.0010,
        ask_qty=1000.0,
        timestamp=time.time(),
    )


@pytest.fixture
def quote_engine():
    """Create quote engine instance"""
    return QuoteEngine()


class TestBookTicker:
    def test_book_ticker_creation(self):
        """Test BookTicker dataclass creation"""
        ticker = BookTicker(
            symbol="ADAUSDT",
            bid_price=1.0,
            bid_qty=100.0,
            ask_price=1.001,
            ask_qty=200.0,
            timestamp=1234567890.0,
        )

        assert ticker.symbol == "ADAUSDT"
        assert ticker.bid_price == 1.0
        assert ticker.ask_price == 1.001


class TestQuote:
    def test_quote_creation(self, sample_book_ticker):
        """Test Quote dataclass creation"""
        bid_layers = [
            LayeredQuote(layer=1, price=0.999, quantity=100.0, spread_bps=10.0)
        ]
        ask_layers = [
            LayeredQuote(layer=1, price=1.002, quantity=100.0, spread_bps=10.0)
        ]

        quote = Quote(
            symbol="ADAUSDM",
            bid_layers=bid_layers,
            ask_layers=ask_layers,
            timestamp=time.time(),
            source_data=sample_book_ticker,
        )

        assert quote.symbol == "ADAUSDM"
        assert quote.bid_price == 0.999
        assert quote.ask_price == 1.002

    def test_spread_calculation(self, sample_book_ticker):
        """Test spread calculation in basis points"""
        bid_layers = [
            LayeredQuote(layer=1, price=0.999, quantity=100.0, spread_bps=10.0)
        ]
        ask_layers = [
            LayeredQuote(layer=1, price=1.001, quantity=100.0, spread_bps=10.0)
        ]

        quote = Quote(
            symbol="ADAUSDM",
            bid_layers=bid_layers,
            ask_layers=ask_layers,
            timestamp=time.time(),
            source_data=sample_book_ticker,
        )

        # Spread should be (1.001 - 0.999) / ((1.001 + 0.999) / 2) * 10000
        expected_spread = (0.002 / 1.0) * 10000
        assert abs(quote.spread_bps - expected_spread) < 0.01

    def test_mid_price_calculation(self, sample_book_ticker):
        """Test mid price calculation"""
        bid_layers = [
            LayeredQuote(layer=1, price=0.999, quantity=100.0, spread_bps=10.0)
        ]
        ask_layers = [
            LayeredQuote(layer=1, price=1.001, quantity=100.0, spread_bps=10.0)
        ]

        quote = Quote(
            symbol="ADAUSDM",
            bid_layers=bid_layers,
            ask_layers=ask_layers,
            timestamp=time.time(),
            source_data=sample_book_ticker,
        )

        assert quote.mid_price == 1.0


class TestQuoteEngine:
    @patch("bot.quote.settings")
    def test_generate_quote_both_sides(
        self, mock_settings_patch, sample_book_ticker, mock_settings
    ):
        """Test quote generation for both bid and ask sides"""
        mock_settings_patch.trading.symbol_dst = "ADAUSDM"
        mock_settings_patch.total_spread_bps = 8  # 5 + 3
        mock_settings_patch.trading.qty = 100.0
        mock_settings_patch.trading.min_quote_size = 10.0
        mock_settings_patch.trading.min_requote_ms = 0
        mock_settings_patch.trading.requote_tick_threshold = 0.0
        mock_settings_patch.trading.stale_ms = 60000
        mock_settings_patch.is_side_enabled.side_effect = lambda side: side in [
            "bid",
            "ask",
        ]

        engine = QuoteEngine()
        quote = engine.generate_quote(sample_book_ticker)

        assert quote is not None
        assert quote.symbol == "ADAUSDM"

        # Check bid calculation: 1.0000 * (1 - 8/10000) = 0.9992
        assert abs(quote.bid_price - 0.9992) < 0.0001

        # Check ask calculation: 1.0010 * (1 + 8/10000) = 1.001801
        assert abs(quote.ask_price - 1.001801) < 0.0001

    @patch("bot.quote.settings")
    def test_generate_quote_bid_only(self, mock_settings_patch, sample_book_ticker):
        """Test quote generation for bid side only"""
        mock_settings_patch.trading.symbol_dst = "ADAUSDM"
        mock_settings_patch.total_spread_bps = 8
        mock_settings_patch.trading.qty = 100.0
        mock_settings_patch.trading.min_quote_size = 10.0
        mock_settings_patch.trading.min_requote_ms = 0
        mock_settings_patch.trading.requote_tick_threshold = 0.0
        mock_settings_patch.trading.stale_ms = 60000
        mock_settings_patch.is_side_enabled.side_effect = lambda side: side == "bid"

        engine = QuoteEngine()
        quote = engine.generate_quote(sample_book_ticker)

        assert quote is not None
        assert quote.bid_price is not None
        assert quote.ask_price is None

    @patch("bot.quote.settings")
    def test_stale_data_rejection(self, mock_settings_patch, sample_book_ticker):
        """Test rejection of stale market data"""
        mock_settings_patch.trading.stale_ms = 1000  # 1 second
        mock_settings_patch.trading.min_requote_ms = 0
        mock_settings_patch.trading.requote_tick_threshold = 0.0

        # Create stale data (2 seconds old)
        stale_ticker = BookTicker(
            symbol="ADAUSDT",
            bid_price=1.0,
            bid_qty=100.0,
            ask_price=1.001,
            ask_qty=100.0,
            timestamp=time.time() - 2.0,
        )

        engine = QuoteEngine()
        quote = engine.generate_quote(stale_ticker)

        assert quote is None

    @patch("bot.quote.settings")
    def test_requote_time_threshold(self, mock_settings_patch, sample_book_ticker):
        """Test minimum requote time threshold"""
        mock_settings_patch.trading.min_requote_ms = 1000  # 1 second
        mock_settings_patch.trading.requote_tick_threshold = 0.0
        mock_settings_patch.trading.stale_ms = 60000
        mock_settings_patch.trading.symbol_dst = "ADAUSDM"
        mock_settings_patch.total_spread_bps = 8
        mock_settings_patch.trading.qty = 100.0
        mock_settings_patch.trading.min_quote_size = 10.0
        mock_settings_patch.is_side_enabled.return_value = True

        engine = QuoteEngine()

        # First quote should succeed
        quote1 = engine.generate_quote(sample_book_ticker)
        assert quote1 is not None

        # Second quote immediately after should be rejected
        quote2 = engine.generate_quote(sample_book_ticker)
        assert quote2 is None

    def test_price_rounding(self, quote_engine):
        """Test price rounding to appropriate precision"""
        price = 1.123456789
        rounded = quote_engine._round_price(price)

        assert rounded == 1.123457  # Should round to 6 decimal places

    def test_get_stats(self, quote_engine):
        """Test quote engine statistics"""
        stats = quote_engine.get_stats()

        assert "last_quote_time" in stats
        assert "has_last_source_prices" in stats
        assert "total_spread_bps" in stats
        assert "sides_enabled" in stats


class TestBinanceDataConversion:
    def test_create_book_ticker_from_binance(self):
        """Test conversion from Binance WebSocket format"""
        binance_data = {
            "u": 400900217,
            "s": "ADAUSDT",
            "b": "1.00000000",
            "B": "1000.00000000",
            "a": "1.00100000",
            "A": "2000.00000000",
        }

        ticker = create_book_ticker_from_binance(binance_data)

        assert ticker.symbol == "ADAUSDT"
        assert ticker.bid_price == 1.0
        assert ticker.bid_qty == 1000.0
        assert ticker.ask_price == 1.001
        assert ticker.ask_qty == 2000.0
        assert ticker.timestamp > 0
