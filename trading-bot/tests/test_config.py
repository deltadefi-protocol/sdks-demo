"""
Tests for configuration management
"""

import os
from unittest.mock import patch

from bot.config import ExchangeConfig, RiskConfig, Settings, SystemConfig, TradingConfig


class TestTradingConfig:
    def test_default_values(self):
        """Test default trading configuration values"""
        config = TradingConfig()

        assert config.symbol_src == "ADAUSDT"
        assert config.symbol_dst == "ADAUSDM"
        assert config.anchor_bps == 5
        assert config.venue_spread_bps == 3
        assert config.side_enable == ["bid", "ask"]
        assert config.qty == 100.0
        assert config.max_skew == 2000.0

    def test_custom_values(self):
        """Test custom trading configuration"""
        config = TradingConfig(
            symbol_src="BTCUSDT", anchor_bps=10, venue_spread_bps=5, qty=50.0
        )

        assert config.symbol_src == "BTCUSDT"
        assert config.anchor_bps == 10
        assert config.venue_spread_bps == 5
        assert config.qty == 50.0


class TestExchangeConfig:
    def test_default_values(self):
        """Test default exchange configuration"""
        config = ExchangeConfig()

        assert config.deltadefi_api_key == ""  # Default empty string
        assert config.trading_password == ""  # Default empty string

    def test_with_api_key(self):
        """Test exchange config with API key"""
        config = ExchangeConfig(deltadefi_api_key="test_key", trading_password="pass123")

        assert config.deltadefi_api_key == "test_key"
        assert config.trading_password == "pass123"


class TestSettings:
    def test_total_spread_bps(self):
        """Test total spread calculation"""
        settings = Settings(
            exchange__deltadefi_api_key="test_key",
            trading__anchor_bps=5,
            trading__venue_spread_bps=3,
        )

        assert settings.total_spread_bps == 8

    def test_deltadefi_ws_url_derivation(self):
        """Test WebSocket URL derivation - URLs are handled by DeltaDeFi SDK"""
        # Since URLs are hardcoded in DeltaDeFi SDK, just test basic settings loading
        settings = Settings()
        # The deltadefi_ws_url property should exist and return a string
        ws_url = settings.deltadefi_ws_url
        assert isinstance(ws_url, str)

    def test_side_enabled(self):
        """Test side enablement checking"""
        with patch.dict(
            os.environ,
            {
                "EXCHANGE__DELTADEFI_API_KEY": "test_key",
                "TRADING__SIDE_ENABLE": '["bid"]',
            },
        ):
            settings = Settings()

            assert settings.is_side_enabled("bid") is True
            assert settings.is_side_enabled("ask") is False
            assert settings.is_side_enabled("BID") is True  # Case insensitive

    @patch.dict(
        os.environ,
        {
            "EXCHANGE__DELTADEFI_API_KEY": "env_test_key",
            "TRADING__ANCHOR_BPS": "10",
            "TRADING__QTY": "200.5",
        },
    )
    def test_environment_variable_loading(self):
        """Test loading configuration from environment variables"""
        settings = Settings()

        assert settings.exchange.deltadefi_api_key == "env_test_key"
        assert settings.trading.anchor_bps == 10
        assert settings.trading.qty == 200.5

    def test_nested_config_structure(self):
        """Test nested configuration structure"""
        settings = Settings(exchange__deltadefi_api_key="test_key")

        assert isinstance(settings.trading, TradingConfig)
        assert isinstance(settings.exchange, ExchangeConfig)
        assert isinstance(settings.risk, RiskConfig)
        assert isinstance(settings.system, SystemConfig)


class TestRiskConfig:
    def test_default_risk_values(self):
        """Test default risk configuration"""
        config = RiskConfig()

        assert config.enable_oms is True
        assert config.max_position_size == 5000.0
        assert config.max_daily_loss == 1000.0
        assert config.emergency_stop is False


class TestSystemConfig:
    def test_default_system_values(self):
        """Test default system configuration"""
        config = SystemConfig()

        assert config.mode == "testnet"
        assert config.log_level == "INFO"
        assert config.db_path == "trading_bot.db"
        assert config.max_orders_per_second == 5.0
