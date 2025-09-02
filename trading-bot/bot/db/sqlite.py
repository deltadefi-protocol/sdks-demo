"""
SQLite connection manager with WAL mode, migrations, and connection pooling
"""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import sqlite3
from typing import Any

import aiosqlite
import structlog

from ..config import settings

logger = structlog.get_logger()


class DatabaseError(Exception):
    """Base exception for database operations"""


class MigrationError(DatabaseError):
    """Exception raised during database migrations"""


class SQLiteManager:
    """
    SQLite database manager with connection pooling and migrations

    Features:
    - WAL mode for better concurrency
    - Automatic schema migrations
    - Connection pooling for async operations
    - Transaction management
    - Foreign key enforcement
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or settings.system.db_path)
        self.schema_path = Path(__file__).parent / "schema.sql"
        self._connection_pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the database with schema and optimizations"""
        if self._initialized:
            return

        logger.info("Initializing SQLite database", db_path=str(self.db_path))

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create and configure database
        async with aiosqlite.connect(self.db_path) as conn:
            # Enable WAL mode for better concurrency
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=10000")
            await conn.execute("PRAGMA temp_store=memory")

            # Enable foreign keys
            await conn.execute("PRAGMA foreign_keys=ON")

            # Run schema migrations
            await self._run_migrations(conn)

            await conn.commit()

        self._initialized = True
        logger.info("Database initialized successfully")

    async def apply_schema(self) -> None:
        """Apply database schema (called during initialization)"""
        # Schema is already applied during initialize()
        # This method exists for compatibility with main.py
        if not self._initialized:
            await self.initialize()
        logger.debug("Database schema is up to date")

    async def _run_migrations(self, conn: aiosqlite.Connection) -> None:
        """Run database schema migrations"""
        try:
            if not self.schema_path.exists():
                raise MigrationError(f"Schema file not found: {self.schema_path}")

            # Check if we need to migrate by checking if quote_id column exists
            cursor = await conn.execute("PRAGMA table_info(quotes)")
            columns = await cursor.fetchall()
            await cursor.close()
            
            has_quote_id = any(column[1] == 'quote_id' for column in columns)
            
            if not has_quote_id and columns:
                # Need to migrate existing schema - drop and recreate
                logger.info("Migrating database schema - dropping existing tables")
                
                # Drop views first (they depend on tables)
                drop_views = [
                    "DROP VIEW IF EXISTS v_active_orders",
                    "DROP VIEW IF EXISTS v_quotes_with_orders", 
                    "DROP VIEW IF EXISTS v_daily_summary"
                ]
                
                for sql in drop_views:
                    await conn.execute(sql)
                
                # Drop tables (in reverse dependency order)
                drop_tables = [
                    "DROP TABLE IF EXISTS fills",
                    "DROP TABLE IF EXISTS orders", 
                    "DROP TABLE IF EXISTS quotes",
                    "DROP TABLE IF EXISTS outbox",
                    "DROP TABLE IF EXISTS positions",
                    "DROP TABLE IF EXISTS account_balances",
                    "DROP TABLE IF EXISTS trading_sessions"
                ]
                
                for sql in drop_tables:
                    await conn.execute(sql)
                
                logger.info("Existing tables dropped, creating new schema")
            
            # Read and execute new schema
            schema_sql = self.schema_path.read_text()
            await conn.executescript(schema_sql)

            logger.info("Database schema migrations completed")

        except Exception as e:
            raise MigrationError(f"Migration failed: {e}") from e

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection from the pool"""
        if not self._initialized:
            await self.initialize()

        async with self._pool_lock:
            if self._connection_pool:
                conn = self._connection_pool.pop()
            else:
                conn = await aiosqlite.connect(self.db_path)
                conn.row_factory = aiosqlite.Row

                # Configure connection
                await conn.execute("PRAGMA foreign_keys=ON")

        try:
            yield conn
        finally:
            # Return connection to pool if still usable
            if conn and not conn.in_transaction:
                async with self._pool_lock:
                    if len(self._connection_pool) < 10:  # Max pool size
                        self._connection_pool.append(conn)
                    else:
                        await conn.close()
            elif conn:
                await conn.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get a database connection within a transaction"""
        async with self.get_connection() as conn:
            try:
                await conn.execute("BEGIN")
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def execute(
        self,
        query: str,
        parameters: tuple = (),
        fetch_one: bool = False,
        fetch_all: bool = False,
    ) -> Any:
        """Execute a single query"""
        async with self.get_connection() as conn:
            cursor = await conn.execute(query, parameters)

            if fetch_one:
                return await cursor.fetchone()
            elif fetch_all:
                return await cursor.fetchall()
            else:
                await conn.commit()
                return cursor.lastrowid

    async def execute_many(self, query: str, parameters_list: list[tuple]) -> None:
        """Execute query with multiple parameter sets"""
        async with self.get_connection() as conn:
            await conn.executemany(query, parameters_list)
            await conn.commit()

    async def fetch_one(
        self, query: str, parameters: tuple = ()
    ) -> aiosqlite.Row | None:
        """Fetch a single row"""
        return await self.execute(query, parameters, fetch_one=True)

    async def fetch_all(
        self, query: str, parameters: tuple = ()
    ) -> list[aiosqlite.Row]:
        """Fetch all rows"""
        return await self.execute(query, parameters, fetch_all=True)

    async def close(self) -> None:
        """Close all connections in the pool"""
        async with self._pool_lock:
            for conn in self._connection_pool:
                try:
                    await conn.close()
                except Exception as e:
                    logger.warning("Error closing connection", error=str(e))

            self._connection_pool.clear()

        logger.info("Database connections closed")

    @contextmanager
    def sync_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a synchronous connection for non-async contexts
        WARNING: Use sparingly, prefer async methods
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")

        try:
            yield conn
        finally:
            conn.close()

    def execute_sync(
        self,
        query: str,
        parameters: tuple = (),
        fetch_one: bool = False,
        fetch_all: bool = False,
    ) -> Any:
        """Synchronous query execution for non-async contexts"""
        with self.sync_connection() as conn:
            cursor = conn.execute(query, parameters)

            if fetch_one:
                return cursor.fetchone()
            elif fetch_all:
                return cursor.fetchall()
            else:
                conn.commit()
                return cursor.lastrowid

    async def get_table_info(self, table_name: str) -> list[aiosqlite.Row]:
        """Get table schema information"""
        return await self.fetch_all("PRAGMA table_info(?)", (table_name,))

    async def get_tables(self) -> list[str]:
        """Get all table names"""
        rows = await self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [row["name"] for row in rows]

    async def vacuum(self) -> None:
        """Vacuum the database to reclaim space"""
        logger.info("Starting database vacuum")
        async with self.get_connection() as conn:
            await conn.execute("VACUUM")
        logger.info("Database vacuum completed")

    async def analyze(self) -> None:
        """Update database statistics for query optimization"""
        async with self.get_connection() as conn:
            await conn.execute("ANALYZE")
        logger.info("Database analysis completed")

    async def get_database_size(self) -> dict[str, Any]:
        """Get database size statistics"""
        page_count = await self.fetch_one("PRAGMA page_count")
        page_size = await self.fetch_one("PRAGMA page_size")

        total_pages = page_count["page_count"] if page_count else 0
        page_size_bytes = page_size["page_size"] if page_size else 0
        total_size_bytes = total_pages * page_size_bytes

        return {
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "total_pages": total_pages,
            "page_size_bytes": page_size_bytes,
            "file_path": str(self.db_path),
        }


# Global database manager instance
db_manager = SQLiteManager()


async def init_database() -> None:
    """Initialize the global database manager"""
    await db_manager.initialize()


async def close_database() -> None:
    """Close the global database manager"""
    await db_manager.close()


# Convenience functions for common operations
async def get_connection():
    """Get a database connection (async context manager)"""
    return db_manager.get_connection()


async def transaction():
    """Get a database transaction (async context manager)"""
    return db_manager.transaction()


async def execute(query: str, parameters: tuple = ()) -> Any:
    """Execute a query"""
    return await db_manager.execute(query, parameters)


async def fetch_one(query: str, parameters: tuple = ()) -> aiosqlite.Row | None:
    """Fetch one row"""
    return await db_manager.fetch_one(query, parameters)


async def fetch_all(query: str, parameters: tuple = ()) -> list[aiosqlite.Row]:
    """Fetch all rows"""
    return await db_manager.fetch_all(query, parameters)
