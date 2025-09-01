# DeltaDeFi Trading Bot Demo

A Python trading bot that connects to Binance WebSocket for market data and implements automated trading strategies on DeltaDeFi.

## Prerequisites

- Python 3.11 or later
- [uv](https://github.com/astral-sh/uv) (recommended package manager)

## Development Setup

### Using uv (recommended)

1. **Install dependencies and create virtual environment:**

   ```sh
   make install
   ```

   Or manually:

   ```sh
   uv venv
   uv pip install -e . --group dev
   ```

2. **Set up pre-commit hooks:**

   ```sh
   make hooks
   ```

### Using pip (alternative)

1. **Create and activate a virtual environment:**

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**

   ```sh
   pip install -e .[dev]
   ```

## Running the Bot

```sh
make run
```

Or directly:

```sh
uv run python -m bot.main
```

## Development Commands

- `make help` - Show all available commands
- `make test` - Run tests with pytest
- `make fmt` - Format code with ruff
- `make lint` - Lint code with ruff
- `make type` - Type check with mypy
- `make precommit` - Run all quality checks

## Architecture

The trading bot is built with Python 3.11+ and uses modern async/await patterns with structured logging and rate limiting.

### Key Features

- **WebSocket Market Data**: Connects to Binance WebSocket for real-time price feeds
- **Rate Limited Order Management**: Token bucket rate limiter (5 orders/second) for DeltaDeFi API
- **Structured Logging**: JSON structured logs with contextual information
- **Graceful Shutdown**: Proper signal handling and resource cleanup
- **Modern Python**: Type hints, Pydantic models, async/await throughout

## Project Structure

```sh
trading-bot/
  pyproject.toml            # Modern Python project configuration (uv + ruff + mypy)
  uv.lock                   # Dependency lock file
  Makefile                  # Development workflow automation
  README.md
  .env.example              # Environment variables template
  docs/
    01-architecture.md      # High-level design and architecture
    02-user-guide.md        # User guide and configuration
    03-deployment.md        # Deployment instructions
  bot/
    __init__.py
    main.py                 # Main entry point with TradingBot class
    log_config.py           # Structured logging configuration
    binance_ws.py           # Binance WebSocket client for market data
    order_manager.py        # Order management with rate limiting
    rate_limiter.py         # Token bucket rate limiter implementation
    config.py               # Pydantic settings (env + YAML)
    quote.py                # ±bps math, (optional) don't-cross clamp
    deltadefi.py            # REST build/submit + Account WS (source of truth)
    oms.py                  # tiny FSM per side; uses repos below (one file)
    db/
      __init__.py
      sqlite.py             # connect(path)->conn, WAL+PRAGMAs, migrations runner
      schema.sql            # DDL (quotes, orders, fills, outbox)
      repo.py               # small repos: QuotesRepo, OrdersRepo, FillsRepo, OutboxRepo
      outbox_worker.py      # reads outbox, calls DeltaDeFi build/submit/cancel* safely
  tests/
    test_quote.py
    test_repos.py
```

## Dependencies

Core dependencies:

- **pycardano**: Cardano blockchain integration
- **aiohttp**: Async HTTP client for API calls
- **pydantic**: Data validation and settings management
- **structlog**: Structured logging
- **sidan-binance-py**: Binance WebSocket client

Development dependencies:

- **pytest + pytest-asyncio**: Testing framework
- **ruff**: Fast Python linter and formatter
- **mypy**: Static type checker
- **pre-commit**: Git hooks for code quality
