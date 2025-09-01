"""
Configuration management using Pydantic settings
Supports environment variables and YAML configuration files
"""

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingConfig(BaseModel):
    """Trading strategy configuration"""

    symbol_src: str = Field(default="ADAUSDT", description="Source symbol (Binance)")
    symbol_dst: str = Field(
        default="ADAUSDM", description="Destination symbol (DeltaDeFi)"
    )
    anchor_bps: int = Field(
        default=5, description="Distance from Binance BBO in basis points"
    )
    venue_spread_bps: int = Field(
        default=3, description="Extra buffer for cross-venue risk in basis points"
    )
    side_enable: list[str] = Field(
        default=["bid", "ask"], description="Which sides to quote"
    )
    qty: float = Field(default=100.0, description="Order quantity in ADA units")
    max_skew: float = Field(
        default=2000.0, description="Maximum position skew in ADA before pausing"
    )

    # Price limits
    min_quote_size: float = Field(default=10.0, description="Minimum quote size")
    max_open_notional: float = Field(
        default=10000.0, description="Maximum open notional value"
    )

    # Timing controls
    requote_tick_threshold: float = Field(
        default=0.0001, description="Minimum price change to trigger requote"
    )
    min_requote_ms: int = Field(
        default=100, description="Minimum time between requotes in milliseconds"
    )
    stale_ms: int = Field(
        default=5000, description="Time before market data is considered stale"
    )


class ExchangeConfig(BaseModel):
    """Exchange connection configuration"""

    # DeltaDeFi API credentials
    deltadefi_api_key: str = Field(default="", description="DeltaDeFi API key")
    trading_password: str = Field(
        default="", description="Trading password for operation key decryption"
    )

    # URLs are hardcoded in DeltaDeFi SDK based on network mode:
    # - testnet: api-staging.deltadefi.io, stream-staging.deltadefi.io
    # - mainnet: api-dev.deltadefi.io, stream.deltadefi.io
    # - binance: stream.binance.com:9443 (public WebSocket)


class RiskConfig(BaseModel):
    """Risk management configuration"""

    enable_oms: bool = Field(default=True, description="Enable order management system")
    max_position_size: float = Field(
        default=5000.0, description="Maximum position size"
    )
    max_daily_loss: float = Field(
        default=1000.0, description="Maximum daily loss limit"
    )
    emergency_stop: bool = Field(default=False, description="Emergency stop flag")


class SystemConfig(BaseModel):
    """System and operational configuration"""

    mode: str = Field(
        default="testnet", description="Trading mode: paper, testnet, or live"
    )
    log_level: str = Field(default="INFO", description="Logging level")
    db_path: str = Field(default="trading_bot.db", description="SQLite database path")

    # Rate limiting
    max_orders_per_second: float = Field(
        default=5.0, description="Maximum orders per second"
    )

    # Connection management
    reconnect_delay: float = Field(
        default=5.0, description="Delay between reconnection attempts"
    )
    max_reconnect_attempts: int = Field(
        default=10, description="Maximum reconnection attempts"
    )


class Settings(BaseSettings):
    """Main application settings"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        yaml_file="config.yaml",  # Support YAML config file
        yaml_file_encoding="utf-8",
    )

    # Nested configuration sections
    trading: TradingConfig = Field(default_factory=TradingConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)

    @property
    def total_spread_bps(self) -> int:
        """Calculate total spread in basis points"""
        return self.trading.anchor_bps + self.trading.venue_spread_bps

    @property
    def deltadefi_ws_url(self) -> str:
        """Get DeltaDeFi WebSocket URL"""
        if self.exchange.deltadefi_ws_url:
            return self.exchange.deltadefi_ws_url

        # Convert HTTP to WebSocket URL
        base = self.exchange.deltadefi_base_url
        if base.startswith("https://"):
            return base.replace("https://", "wss://")
        elif base.startswith("http://"):
            return base.replace("http://", "ws://")
        return base

    def is_side_enabled(self, side: str) -> bool:
        """Check if a trading side is enabled"""
        return side.lower() in [s.lower() for s in self.trading.side_enable]

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "Settings":
        """Load settings from YAML file"""
        import yaml

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        return cls(**data)


# Global settings instance
settings = Settings()
