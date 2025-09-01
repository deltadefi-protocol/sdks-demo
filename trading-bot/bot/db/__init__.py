"""
Database package initialization

Provides convenient imports and initialization functions for the trading bot database layer.
Exports key components: repositories, database manager, and utility functions.
"""

from .outbox_worker import (
    cleanup_outbox_events,
    get_outbox_stats,
    start_outbox_worker,
    stop_outbox_worker,
)
from .repo import (
    balance_repo,
    fill_repo,
    order_repo,
    outbox_repo,
    position_repo,
    quote_repo,
    session_repo,
)
from .sqlite import close_database, db_manager, init_database

__all__ = [
    "balance_repo",
    "cleanup_outbox_events",
    "close_database",
    "db_manager",
    "fill_repo",
    "get_outbox_stats",
    "init_database",
    "order_repo",
    "outbox_repo",
    "position_repo",
    "quote_repo",
    "session_repo",
    "start_outbox_worker",
    "stop_outbox_worker",
]


async def initialize_database() -> None:
    """
    Initialize the complete database system

    This function:
    1. Initializes the SQLite database with schema
    2. Starts the outbox worker for event processing
    3. Sets up all repositories
    """
    # Initialize database schema and connections
    await init_database()

    # Start outbox worker for event processing
    # Note: This is started as a background task, caller should manage lifecycle
    import asyncio

    asyncio.create_task(start_outbox_worker())


async def shutdown_database() -> None:
    """
    Gracefully shutdown the database system

    This function:
    1. Stops the outbox worker
    2. Closes all database connections
    3. Cleans up resources
    """
    # Stop outbox worker first
    await stop_outbox_worker()

    # Close database connections
    await close_database()
