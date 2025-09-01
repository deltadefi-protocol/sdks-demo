"""
DeltaDeFi integration module using the official Python SDK

This module provides:
- DeltaDeFi REST API client wrapper with rate limiting
- Account WebSocket for real-time fills and balance updates
- Error handling and integration with bot configuration
"""

import asyncio
from collections.abc import Callable
from typing import Any

from deltadefi import ApiClient
import structlog

from bot.config import settings
from bot.rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger()


class DeltaDeFiClient:
    """DeltaDeFi client wrapper with rate limiting and error handling"""

    def __init__(
        self,
        api_key: str | None = None,
        trading_password: str | None = None,
        network: str | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
    ):
        self.api_key = api_key or settings.exchange.deltadefi_api_key
        self.trading_password = trading_password or settings.exchange.trading_password

        # Map system.mode to DeltaDeFi SDK network parameter
        system_mode = settings.system.mode.lower()
        if network:
            self.network = network
        elif system_mode in ["testnet", "preprod", "staging"]:
            self.network = "preprod"  # SDK uses 'preprod' for testnet
        elif system_mode == "mainnet":
            self.network = "mainnet"
        else:
            self.network = "preprod"  # Default to testnet
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(
            max_tokens=int(settings.system.max_orders_per_second),
            refill_rate=settings.system.max_orders_per_second,
        )

        self._client = ApiClient(
            network=self.network,
            api_key=self.api_key,
        )

        # Load operation key if trading password is provided
        self._operation_key_loaded = False
        if self.trading_password:
            try:
                self._client.load_operation_key(self.trading_password)
                self._operation_key_loaded = True
                logger.info("Operation key loaded successfully")
            except Exception as e:
                logger.error("Failed to load operation key", error=str(e))
                raise ValueError(f"Failed to load operation key: {e}") from e
        else:
            logger.warning(
                "No trading password provided - order submission will not work"
            )

        logger.info(
            "DeltaDeFi client initialized",
            network=self.network,
            api_key_present=bool(self.api_key),
            operation_key_loaded=self._operation_key_loaded,
        )

    async def get_account_balance(self) -> dict:
        """Get account balance from DeltaDeFi

        Returns:
            Account balance information
        """
        logger.debug("Getting account balance")

        try:
            balance = self._client.accounts.get_account_balance()
            logger.info("Account balance retrieved", balance=balance)
            return balance
        except Exception as e:
            logger.error("Failed to get account balance", error=str(e))
            raise

    async def get_market_price(self, symbol: str) -> dict:
        """Get market price for a symbol

        Args:
            symbol: Trading symbol (e.g., "ADAUSDM")

        Returns:
            Market price data
        """
        logger.debug("Getting market price", symbol=symbol)

        try:
            price = self._client.markets.get_market_price(symbol)
            logger.debug("Market price retrieved", symbol=symbol, price=price)
            return price
        except Exception as e:
            logger.error("Failed to get market price", symbol=symbol, error=str(e))
            raise

    async def get_aggregated_price(
        self,
        symbol: str,
        interval: str = "15m",
        start: int | None = None,
        end: int | None = None,
    ) -> dict:
        """Get aggregated price data for a symbol

        Args:
            symbol: Trading symbol (e.g., "ADAUSDM")
            interval: Time interval ("15m", "30m", "1h", "1d", "1w", "1M")
            start: Start timestamp
            end: End timestamp

        Returns:
            Aggregated price data
        """
        import time

        if start is None:
            start = int(time.time() - 86400)  # 24 hours ago
        if end is None:
            end = int(time.time())

        logger.debug("Getting aggregated price", symbol=symbol, interval=interval)

        try:
            price_data = self._client.markets.get_aggregated_price(
                symbol=symbol, interval=interval, start=start, end=end
            )
            logger.debug("Aggregated price retrieved", symbol=symbol)
            return price_data
        except Exception as e:
            logger.error("Failed to get aggregated price", symbol=symbol, error=str(e))
            raise

    async def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float | None = None,
        **kwargs,
    ) -> dict:
        """Submit an order to DeltaDeFi with rate limiting

        Args:
            symbol: Trading symbol
            side: "buy" or "sell"
            order_type: "limit" or "market"
            quantity: Order quantity (integer)
            price: Order price (required for limit orders)
            **kwargs: Additional parameters for the order

        Returns:
            Order submission result

        Raises:
            ValueError: If operation key is not loaded
        """
        if not self._operation_key_loaded:
            raise ValueError("Operation key not loaded - cannot submit orders")

        await self.rate_limiter.wait_for_token()

        logger.info(
            "Submitting order",
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            kwargs=kwargs,
        )

        try:
            # Use the SDK's post_order method which handles build/sign/submit
            result = self._client.post_order(
                symbol=symbol,
                side=side,  # SDK expects string, will handle conversion internally
                type=order_type,  # SDK expects string, will handle conversion internally
                quantity=quantity,
                price=price,
                **kwargs,
            )

            logger.info(
                "Order submitted successfully",
                result=result,
                symbol=symbol,
                side=side,
            )

            return result

        except Exception as e:
            logger.error(
                "Failed to submit order",
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                error=str(e),
            )
            raise

    async def cancel_order(self, order_id: str, **kwargs) -> dict:
        """Cancel an order

        Args:
            order_id: Order ID to cancel
            **kwargs: Additional parameters

        Returns:
            Cancel order result

        Raises:
            ValueError: If operation key is not loaded
        """
        if not self._operation_key_loaded:
            raise ValueError("Operation key not loaded - cannot cancel orders")

        await self.rate_limiter.wait_for_token()

        logger.info("Cancelling order", order_id=order_id)

        try:
            result = self._client.cancel_order(order_id=order_id, **kwargs)

            logger.info(
                "Order cancelled successfully",
                result=result,
                order_id=order_id,
            )

            return result

        except Exception as e:
            logger.error(
                "Failed to cancel order",
                order_id=order_id,
                error=str(e),
            )
            raise


class AccountWebSocket:
    """WebSocket client for real-time account updates using DeltaDeFi SDK"""

    def __init__(
        self,
        api_client: Any | None = None,
        network: str = "preprod",
        api_key: str | None = None,
    ):
        """Initialize AccountWebSocket with DeltaDeFi ApiClient

        Args:
            api_client: Optional existing ApiClient instance
            network: Network to connect to ("preprod" or "mainnet")
            api_key: API key for authentication
        """
        self.api_key = api_key or settings.exchange.deltadefi_api_key

        if api_client:
            self._client = api_client
        else:
            self._client = ApiClient(
                network=network,
                api_key=self.api_key,
            )

        self._account_callbacks: list[Callable] = []
        self._running = False

        logger.info(
            "Account WebSocket initialized with SDK",
            network=network,
            api_key_present=bool(self.api_key),
        )

    def add_account_callback(self, callback: Callable) -> None:
        """Add callback for account updates (balances, fills, order status)

        Args:
            callback: Async function to call when account data is received
        """
        self._account_callbacks.append(callback)
        logger.debug("Account callback added", callback=callback.__name__)

    async def start(self) -> None:
        """Start WebSocket connection and subscribe to account updates"""
        if not self.api_key:
            raise ValueError("API key is required for account WebSocket")

        self._running = True

        try:
            # Register account message handler
            self._client.websocket.register_handler(
                "account", self._handle_account_message
            )

            # Subscribe to account stream
            await self._client.websocket.subscribe_account()

            logger.info("Account WebSocket started and subscribed")

        except Exception as e:
            logger.error("Failed to start account WebSocket", error=str(e))
            raise

    async def stop(self) -> None:
        """Stop WebSocket connection"""
        self._running = False

        try:
            await self._client.websocket.disconnect()
            logger.info("Account WebSocket stopped")
        except Exception as e:
            logger.error("Error stopping account WebSocket", error=str(e))

    async def _handle_account_message(self, data: dict) -> None:
        """Handle incoming account WebSocket messages

        Args:
            data: Account message data from DeltaDeFi
        """
        try:
            # Log the account update
            sub_type = data.get("sub_type", "unknown")
            logger.info(
                "Account update received",
                sub_type=sub_type,
                data_keys=list(data.keys()) if isinstance(data, dict) else "non-dict",
            )

            # Call all registered callbacks
            for callback in self._account_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    logger.error(
                        "Error in account callback",
                        callback=callback.__name__,
                        error=str(e),
                    )

        except Exception as e:
            logger.error("Error handling account message", error=str(e), data=data)

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected"""
        return self._client.websocket.is_connected

    def get_subscriptions(self) -> dict:
        """Get current subscription status"""
        return self._client.websocket.subscriptions


class MarketDataWebSocket:
    """WebSocket client for market data using DeltaDeFi SDK"""

    def __init__(
        self,
        api_client: Any | None = None,
        network: str = "preprod",
        api_key: str | None = None,
    ):
        """Initialize MarketDataWebSocket with DeltaDeFi ApiClient

        Args:
            api_client: Optional existing ApiClient instance
            network: Network to connect to ("preprod" or "mainnet")
            api_key: API key for authentication
        """
        self.api_key = api_key or settings.exchange.deltadefi_api_key

        if api_client:
            self._client = api_client
        else:
            self._client = ApiClient(
                network=network,
                api_key=self.api_key,
            )

        self._trade_callbacks: list[Callable] = []
        self._depth_callbacks: list[Callable] = []
        self._price_callbacks: list[Callable] = []

        logger.info(
            "Market data WebSocket initialized",
            network=network,
            api_key_present=bool(self.api_key),
        )

    def add_trade_callback(self, callback: Callable) -> None:
        """Add callback for trade updates"""
        self._trade_callbacks.append(callback)
        self._client.websocket.register_handler("trade", self._handle_trade_message)
        logger.debug("Trade callback added", callback=callback.__name__)

    def add_depth_callback(self, callback: Callable) -> None:
        """Add callback for depth updates"""
        self._depth_callbacks.append(callback)
        self._client.websocket.register_handler("depth", self._handle_depth_message)
        logger.debug("Depth callback added", callback=callback.__name__)

    def add_price_callback(self, callback: Callable) -> None:
        """Add callback for price updates"""
        self._price_callbacks.append(callback)
        self._client.websocket.register_handler("price", self._handle_price_message)
        logger.debug("Price callback added", callback=callback.__name__)

    async def subscribe_trades(self, symbol: str) -> None:
        """Subscribe to trade stream for a symbol"""
        await self._client.websocket.subscribe_trades(symbol)
        logger.info("Subscribed to trades", symbol=symbol)

    async def subscribe_depth(self, symbol: str) -> None:
        """Subscribe to depth stream for a symbol"""
        await self._client.websocket.subscribe_depth(symbol)
        logger.info("Subscribed to depth", symbol=symbol)

    async def subscribe_price(self, symbol: str) -> None:
        """Subscribe to price stream for a symbol"""
        await self._client.websocket.subscribe_price(symbol)
        logger.info("Subscribed to price", symbol=symbol)

    async def disconnect(self) -> None:
        """Disconnect WebSocket"""
        await self._client.websocket.disconnect()

    async def _handle_trade_message(self, data) -> None:
        """Handle trade messages"""
        for callback in self._trade_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error("Error in trade callback", error=str(e))

    async def _handle_depth_message(self, data) -> None:
        """Handle depth messages"""
        for callback in self._depth_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error("Error in depth callback", error=str(e))

    async def _handle_price_message(self, data) -> None:
        """Handle price messages"""
        for callback in self._price_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error("Error in price callback", error=str(e))
