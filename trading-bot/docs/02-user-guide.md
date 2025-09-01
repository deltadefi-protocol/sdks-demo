# User Guide

## Prerequisites

- Python 3.11 or later
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- DeltaDeFi API key (add header X-API-KEY) and trading passcode
- ADA/USDM balances on DeltaDeFi; pair symbol is ADAUSDM

## Installation

### Using uv (recommended)

1. **Install dependencies:**

   ```sh
   make install
   ```

2. **Set up pre-commit hooks:**

   ```sh
   make hooks
   ```

### Using pip (alternative)

1. **Create virtual environment:**

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**

   ```sh
   pip install -e .[dev]
   ```

## Configuration

1. **Copy environment template:**

   ```sh
   cp .env.example .env
   ```

2. **Edit `.env` with your settings:**

   ```bash
   BINANCE_WS_URL=wss://stream.binance.com:9443/ws/adausdt@bookTicker
   DELTADEFI_API_KEY=your_api_key_here
   DELTADEFI_BASE_URL=https://api-staging.deltadefi.io
   ```

## Running the Bot

### Development Mode

```sh
make run
```

Or directly:

```sh
uv run python -m bot.main
```

### With Custom Parameters

```sh
uv run python -m bot.main --anchor-bps 5 --venue-spread-bps 3 --qty 100
```

## Development Commands

- `make help` - Show all available commands
- `make test` - Run tests with pytest
- `make fmt` - Format code with ruff
- `make lint` - Lint code with ruff
- `make type` - Type check with mypy
- `make precommit` - Run all quality checks
- `make clean` - Remove caches and build artifacts

## Monitoring

The bot logs structured JSON output with the following information:

- **WebSocket Status**: Connection state and market data reception
- **Order Management**: Rate limiting status and order submissions
- **System Health**: Periodic status reports every 30 seconds

Example log output:

```json
{
  "event": "Trading Bot Status",
  "timestamp": "2025-09-01T12:00:00Z",
  "orders_submitted": 42,
  "rate_limit_tokens": 4.8,
  "websocket_connected": true
}
```
