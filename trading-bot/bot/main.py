"""
Trading Bot Main Entry Point

Integrates the complete trading system:
- Binance WebSocket price feeds
- Quote generation and persistence
- Order management with DeltaDeFi
- Account state management
- Database persistence with outbox pattern
- Rate limiting and error handling
"""

import asyncio
import signal
import sys
import time
from typing import Any, Dict

import structlog

from .account_manager import AccountManager
from .binance_ws import BinanceWebSocket
from .config import settings
from .db.outbox_worker import OutboxWorker
from .db.sqlite import db_manager
from .deltadefi import DeltaDeFiClient
from .log_config import setup_logging
from .oms import OrderManagementSystem
from .quote import QuoteEngine, create_book_ticker_from_binance
from .quote_to_order_pipeline import QuoteToOrderPipeline
from .rate_limiter import TokenBucketRateLimiter
from .unregistered_order_cleanup import UnregisteredOrderCleanupService
from .asset_ratio_manager import AssetRatioManager

# Setup logging first
setup_logging()

# Suppress verbose WebSocket logging from binance library to reduce log spam
import logging
import sys
import os

# Set various logging levels to reduce WebSocket spam
logging.getLogger("binance").setLevel(logging.ERROR)
logging.getLogger("websocket").setLevel(logging.ERROR)
logging.getLogger("websockets").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# Redirect stdout temporarily during WebSocket creation to suppress print statements
class SuppressPrints:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout

logger = structlog.get_logger()


class TradingBot:
    """
    Complete trading bot integrating all components:
    - Market data ingestion (Binance)
    - Quote generation and persistence  
    - Order management (OMS)
    - DeltaDeFi integration
    - Account state management
    - Database persistence with outbox pattern
    """
    
    def __init__(self):
        # Core components
        self.deltadefi_client: DeltaDeFiClient | None = None
        self.oms: OrderManagementSystem | None = None
        self.account_manager: AccountManager | None = None
        self.quote_engine: QuoteEngine | None = None
        self.quote_pipeline: QuoteToOrderPipeline | None = None
        self.outbox_worker: OutboxWorker | None = None
        self.cleanup_service: UnregisteredOrderCleanupService | None = None
        self.asset_ratio_manager: AssetRatioManager | None = None
        
        # Market data
        self.binance_ws: BinanceWebSocket | None = None
        
        # State
        self.running = False
        self.start_time = 0.0
        self.last_quote_time = 0.0
        
        # Metrics
        self.quotes_generated = 0
        self.orders_submitted = 0
        self.binance_messages = 0
        
    async def start(self):
        """Start the complete trading bot system"""
        logger.info(
            "🚀 Starting Complete Trading Bot System",
            mode=settings.system.mode,
            trading_pair=f"{settings.trading.symbol_src} → {settings.trading.symbol_dst}",
            spread_bps=settings.total_spread_bps,
            sides_enabled=settings.trading.side_enable,
            api_key_present=bool(settings.exchange.deltadefi_api_key),
            trading_password_present=bool(settings.exchange.trading_password),
        )
        
        self.running = True
        self.start_time = time.time()
        
        try:
            # Step 1: Initialize database
            await self._initialize_database()
            
            # Step 2: Initialize core components
            await self._initialize_components()
            
            # Step 3: Start background services
            await self._start_services()
            
            # Step 4: Start market data feed
            await self._start_market_data()
            
            logger.info(
                "✅ Trading Bot System Started Successfully",
                components_initialized=8,  # Updated to include cleanup service
                database_ready=True,
                market_data_connected=True,
                deltadefi_ready=self.deltadefi_client._operation_key_loaded if self.deltadefi_client else False,
                cleanup_service_enabled=settings.system.cleanup_unregistered_orders,
            )
            
        except Exception as e:
            logger.error("Failed to start trading bot", error=str(e), exc_info=True)
            await self.stop()
            raise
    
    async def _initialize_database(self):
        """Initialize database and apply migrations"""
        logger.info("📊 Initializing database...")
        
        try:
            # Initialize database manager
            await db_manager.initialize()
            
            # Apply schema (migrations would go here)
            await db_manager.apply_schema()
            
            logger.info("✅ Database initialized successfully")
            
        except Exception as e:
            logger.error("Database initialization failed", error=str(e))
            raise
    
    async def _initialize_components(self):
        """Initialize all core trading components"""
        logger.info("🔧 Initializing core components...")
        
        # 1. DeltaDeFi client with rate limiting
        self.deltadefi_client = DeltaDeFiClient(
            rate_limiter=TokenBucketRateLimiter(
                max_tokens=int(settings.system.max_orders_per_second),
                refill_rate=settings.system.max_orders_per_second,
            )
        )
        
        # 2. Order Management System  
        self.oms = OrderManagementSystem()
        
        # 3. Account Manager for real-time balance/fill tracking
        self.account_manager = AccountManager(self.deltadefi_client)
        
        # 4. Asset Ratio Manager for ratio balancing
        self.asset_ratio_manager = AssetRatioManager()
        
        # 5. Quote Engine for price generation (with asset ratio manager)
        self.quote_engine = QuoteEngine(asset_ratio_manager=self.asset_ratio_manager)
        
        # 6. Quote-to-Order Pipeline
        self.quote_pipeline = QuoteToOrderPipeline(
            oms=self.oms,
            deltadefi_client=self.deltadefi_client,
        )
        
        # 7. Outbox Worker for reliable event processing
        self.outbox_worker = OutboxWorker()
        
        # 8. Unregistered Order Cleanup Service
        self.cleanup_service = UnregisteredOrderCleanupService(
            deltadefi_client=self.deltadefi_client,
            oms=self.oms
        )
        
        logger.info("✅ Core components initialized")
    
    async def _start_services(self):
        """Start background services"""
        logger.info("🏃 Starting background services...")
        
        # Run initial cleanup BEFORE starting any trading services
        # This ensures all unregistered orders are cancelled before new ones are placed
        await self.cleanup_service.run_initial_cleanup()
        
        # Start Account Manager (WebSocket + balance tracking)
        # Note: Account manager will handle DeltaDeFi WebSocket internally
        try:
            await self.account_manager.start()
        except Exception as e:
            logger.warning("Account manager failed to start, continuing with reduced functionality", error=str(e))
            # Continue without account manager - we can still do market making
            # Orders may have reduced risk management without real-time account data
        
        # Start Quote-to-Order Pipeline
        await self.quote_pipeline.start()
        
        # Start Outbox Worker for reliable event processing (as background task)
        asyncio.create_task(self.outbox_worker.start())
        
        # Start Unregistered Order Cleanup Service (for ongoing periodic cleanup)
        await self.cleanup_service.start()
        
        # Setup callbacks for integration
        self._setup_callbacks()
        
        logger.info("✅ Background services started")
    
    async def _start_market_data(self):
        """Start Binance market data feed"""
        logger.info("📡 Starting market data feed...")
        
        # Initialize Binance WebSocket with quote processing
        self.binance_ws = BinanceWebSocket(
            symbol=settings.trading.symbol_src.lower(),
            order_manager=None,  # We'll use our own pipeline
        )
        
        # Override the message handler to use our quote pipeline
        self.binance_ws._on_message = self._process_binance_message
        
        await self.binance_ws.start()
        
        logger.info("✅ Market data feed started", symbol=settings.trading.symbol_src)
    
    def _setup_callbacks(self):
        """Setup inter-component callbacks"""
        # Connect account manager to OMS for fill updates
        if self.account_manager:
            self.account_manager.fill_reconciler.add_fill_callback(self._on_fill_received)
        
        # Connect OMS to quote pipeline for order updates
        if self.oms:
            self.oms.add_order_callback(self._on_order_update)
        
        # Connect quote pipeline callbacks
        if self.quote_pipeline:
            self.quote_pipeline.add_quote_callback(self._on_quote_processed)
            self.quote_pipeline.add_order_callback(self._on_pipeline_order_update)
        
        logger.debug("✅ Inter-component callbacks configured")
    
    async def _process_binance_message(self, message: Dict[str, Any]):
        """
        Process incoming Binance WebSocket message and generate quotes
        
        This is the core trading logic entry point
        """
        try:
            self.binance_messages += 1
            
            # Create BookTicker from Binance data
            book_ticker = create_book_ticker_from_binance(message)
            
            logger.debug(
                "📈 Binance price update",
                symbol=book_ticker.symbol,
                bid=book_ticker.bid_price,
                ask=book_ticker.ask_price,
                spread=book_ticker.ask_price - book_ticker.bid_price,
            )
            
            # Generate quote using quote engine
            quote = self.quote_engine.generate_quote(book_ticker)
            
            if quote:
                self.quotes_generated += 1
                self.last_quote_time = time.time()
                
                # Process quote through pipeline (persist + create orders)
                try:
                    processed_quote = await self.quote_pipeline.process_quote(quote)
                    
                    logger.info(
                        "🎯 Quote processed and orders submitted",
                        quote_id=processed_quote.quote_id,
                        symbol_dst=processed_quote.symbol_dst,
                        bid_price=float(processed_quote.bid_price) if processed_quote.bid_price else None,
                        ask_price=float(processed_quote.ask_price) if processed_quote.ask_price else None,
                        status=processed_quote.status,
                    )
                    
                except Exception as e:
                    logger.error(
                        "Quote pipeline processing failed", 
                        error=str(e),
                        symbol=book_ticker.symbol,
                    )
            
        except Exception as e:
            logger.error("Error processing Binance message", error=str(e), message=message)
    
    async def _on_fill_received(self, fill):
        """Handle fill received from account manager"""
        logger.info(
            "💰 Fill received",
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            symbol=fill.symbol,
            side=fill.side,
            quantity=float(fill.quantity),
            price=float(fill.price),
        )
        
        # Update OMS with fill
        try:
            await self.oms.add_fill(
                order_id=fill.order_id,
                fill_quantity=fill.quantity,
                fill_price=fill.price,
                trade_id=fill.trade_id,
                fee=fill.commission,
            )
        except Exception as e:
            logger.error("Failed to update OMS with fill", fill_id=fill.fill_id, error=str(e))
    
    async def _on_order_update(self, order):
        """Handle order updates from OMS"""
        logger.debug(
            "📋 Order updated",
            order_id=order.order_id,
            state=order.state,
            filled_quantity=float(order.filled_quantity),
        )
    
    async def _on_quote_processed(self, quote):
        """Handle quote processed by pipeline"""
        logger.debug(
            "📊 Quote processed",
            quote_id=quote.quote_id,
            status=quote.status,
        )
    
    async def _on_pipeline_order_update(self, order):
        """Handle order updates from quote pipeline"""
        if order.state == "WORKING":
            self.orders_submitted += 1
        
        logger.debug(
            "🎯 Pipeline order updated",
            order_id=order.order_id,
            state=order.state,
        )
    
    async def stop(self):
        """Stop the trading bot gracefully"""
        logger.info("🛑 Stopping Trading Bot System...")
        self.running = False
        
        # Stop components in reverse order
        if self.binance_ws:
            await self.binance_ws.stop()
            logger.debug("✅ Market data feed stopped")
        
        if self.quote_pipeline:
            await self.quote_pipeline.stop()
            logger.debug("✅ Quote pipeline stopped")
        
        if self.outbox_worker:
            await self.outbox_worker.stop()
            logger.debug("✅ Outbox worker stopped")
        
        if self.cleanup_service:
            await self.cleanup_service.stop()
            logger.debug("✅ Cleanup service stopped")
        
        if self.account_manager:
            await self.account_manager.stop()
            logger.debug("✅ Account manager stopped")
        
        # Close database connections
        await db_manager.close()
        logger.debug("✅ Database connections closed")
        
        logger.info("✅ Trading Bot System stopped gracefully")
    
    async def run(self):
        """Main run loop with status monitoring"""
        await self.start()
        
        try:
            last_status_log = 0
            last_cleanup = 0
            
            while self.running:
                current_time = time.time()
                
                # Status logging every 30 seconds
                if current_time - last_status_log > 30:
                    await self._log_status()
                    last_status_log = current_time
                
                # Cleanup expired quotes more frequently (every 10 seconds)
                # With aggressive replacement, this is mainly a safety net
                if current_time - last_cleanup > 10:
                    if self.quote_pipeline:
                        expired_count = await self.quote_pipeline.cleanup_expired_quotes()
                        if expired_count > 0:
                            logger.debug("Background cleanup removed expired quotes", count=expired_count)
                    last_cleanup = current_time
                
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("🛑 Received keyboard interrupt")
        except Exception as e:
            logger.error("Trading bot error", error=str(e), exc_info=True)
        finally:
            await self.stop()
    
    async def _log_status(self):
        """Log comprehensive system status"""
        uptime = int(time.time() - self.start_time) if self.start_time > 0 else 0
        
        # Collect status from all components
        status = {
            "uptime_seconds": uptime,
            "binance_messages": self.binance_messages,
            "quotes_generated": self.quotes_generated,
            "orders_submitted": self.orders_submitted,
            "last_quote_age_seconds": int(time.time() - self.last_quote_time) if self.last_quote_time > 0 else None,
        }
        
        # OMS status
        if self.oms:
            portfolio = self.oms.get_portfolio_summary()
            status.update({
                "open_orders": portfolio["open_orders"],
                "max_orders": settings.risk.max_open_orders,
                "order_utilization_pct": round((portfolio["open_orders"] / settings.risk.max_open_orders) * 100, 1),
                "total_positions": portfolio["total_positions"],
                "daily_pnl": float(portfolio["daily_pnl"]),
            })
        
        # Quote pipeline status
        if self.quote_pipeline:
            pipeline_stats = await self.quote_pipeline.get_pipeline_stats()
            status.update({
                "active_quotes": pipeline_stats["active_quotes_count"],
                "pipeline_success_rate": pipeline_stats.get("success_rate", 0),
            })
        
        # Account manager status
        if self.account_manager:
            account_summary = self.account_manager.get_account_summary()
            status.update({
                "websocket_connected": account_summary["websocket_connected"],
                "balance_count": account_summary["balance_count"],
                "fills_processed": account_summary["fills_processed"],
            })
        
        # Cleanup service status
        if self.cleanup_service:
            cleanup_stats = self.cleanup_service.get_stats()
            status.update({
                "cleanup_enabled": cleanup_stats["enabled"],
                "cleanup_runs": cleanup_stats["cleanup_runs"],
                "unregistered_orders_cancelled": cleanup_stats["orders_cancelled"],
                "cleanup_errors": cleanup_stats["cleanup_errors"],
            })
        
        logger.info("📊 Trading Bot System Status", **status)


async def main():
    """Main entry point"""
    # Validate critical configuration
    if not settings.exchange.deltadefi_api_key:
        logger.error("❌ DELTADEFI_API_KEY is required")
        sys.exit(1)
    
    if not settings.exchange.trading_password:
        logger.error("❌ TRADING_PASSWORD is required for order submission")
        sys.exit(1)
    
    bot = TradingBot()
    
    # Handle shutdown signals gracefully
    def signal_handler(signum, _frame):
        logger.info(f"🛑 Received signal {signum}")
        # Create a task to stop the bot gracefully
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.run()
    except Exception as e:
        logger.error("💥 Trading bot crashed", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())