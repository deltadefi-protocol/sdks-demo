# User Guide

Complete setup, configuration, and operational guide for the DeltaDeFi trading bot.

> **📝 Quick Start**: For immediate setup, see the [README](../README.md#quick-start)

## Prerequisites

- Python 3.11+ and [uv](https://github.com/astral-sh/uv) package manager
- DeltaDeFi API key and trading password
- Sufficient ADA/USDM balances on DeltaDeFi for trading pair ADAUSDM
- Basic understanding of market making concepts

## Installation

```sh
# Clone and install
git clone <repository-url> && cd trading-bot
make install && make hooks
```

> **👩‍💻 Alternative methods**: See [Development Guide](../DEVELOPMENT.md) for pip installation

## Configuration

> **📝 Complete Configuration Guide**: See [CONFIG.md](../CONFIG.md) for the full configuration system

### Quick Setup

1. **Copy and edit environment file:**

   ```sh
   cp .env.example .env
   # Edit .env with your DeltaDeFi API key and trading password
   ```

2. **Key required settings:**

   ```bash
   DELTADEFI_API_KEY=your_api_key_here
   TRADING_PASSWORD=your_trading_password
   SYSTEM_MODE=testnet  # or mainnet
   ```

### Trading Parameters

Customize trading behavior by editing `config.yaml` or using environment variables:

- **Spread Control**: `TOTAL_SPREAD_BPS=8` (basis points)
- **Order Size**: `QTY=100` (quantity per order)
- **Symbols**: `SYMBOL_SRC=ADAUSDT`, `SYMBOL_DST=ADAUSDM`
- **Risk Limits**: `MAX_POSITION_SIZE=10000`, `MAX_DAILY_LOSS=1000`

## Running the Bot

### Standard Operation

```sh
# Start with default configuration
make run

# Or with custom parameters
uv run python -m bot.main --total-spread-bps 6 --qty 200

# View all options
uv run python -m bot.main --help
```

> **🚀 Production Deployment**: See [Deployment Guide](03-deployment.md) for production setup

## Development Commands

```sh
make help          # Show all commands
make test          # Run test suite
make fmt           # Format code
make lint          # Lint code
make precommit     # All quality checks
```

> **👩‍💻 Development Setup**: See [Development Guide](../DEVELOPMENT.md) for detailed development workflow

## Monitoring and Operations

### Real-time Monitoring

The bot provides structured JSON logging for comprehensive monitoring:

```sh
# Follow real-time logs with formatting
tail -f logs/trading-bot.log | jq '.'

# Monitor critical events
tail -f logs/trading-bot.log | jq 'select(.level == "ERROR" or .level == "WARNING")'

# Track order flow
tail -f logs/trading-bot.log | jq 'select(.event | contains("order"))'

# Check system health reports
tail -f logs/trading-bot.log | jq 'select(.event == "Trading Bot Status")'
```

### Key Performance Metrics

Monitor these essential metrics for bot health:

- **Orders Submitted**: Total orders sent to exchange
- **Rate Limit Tokens**: Available tokens (0-5, should stay above 1)
- **WebSocket Status**: Connection health to both exchanges
- **Position Size**: Current ADA position relative to limits
- **Daily P&L**: Profit/loss tracking
- **Fill Rate**: Percentage of orders successfully filled

### Health Checks

```sh
# Verify bot responsiveness (recent activity within 2 minutes)
sqlite3 trading_bot.db "SELECT COUNT(*) FROM orders WHERE created_at > datetime('now', '-2 minutes');"

# Check database integrity
sqlite3 trading_bot.db "PRAGMA integrity_check;"

# Monitor recent performance
sqlite3 trading_bot.db "SELECT DATE(created_at) as date, COUNT(*) as orders, SUM(CASE WHEN state = 'filled' THEN 1 ELSE 0 END) as filled FROM orders WHERE created_at >= date('now', '-7 days') GROUP BY DATE(created_at);"
```

## Advanced Usage

### Custom Trading Parameters

```sh
# Tighter spreads for active markets
uv run python -m bot.main --total-spread-bps 4

# Larger orders for institutional trading
uv run python -m bot.main --qty 1000

# Mainnet trading with custom risk limits
SYSTEM_MODE=mainnet MAX_POSITION_SIZE=50000 make run
```

### Database Operations

```sh
# View recent order history
sqlite3 trading_bot.db "SELECT * FROM orders ORDER BY created_at DESC LIMIT 10;"

# Check current position
sqlite3 trading_bot.db "SELECT SUM(CASE WHEN side = 'buy' THEN quantity ELSE -quantity END) as net_position FROM orders WHERE state = 'filled' AND symbol = 'ADAUSDM';"

# Analyze daily performance
sqlite3 trading_bot.db "SELECT DATE(created_at) as date, COUNT(*) as orders, AVG(fill_price) as avg_price FROM orders WHERE state = 'filled' GROUP BY DATE(created_at) ORDER BY date DESC;"
```

## Risk Management

### Emergency Procedures

**Immediate Stop:**

```sh
# Graceful shutdown
pkill -SIGTERM -f "python -m bot.main"

# Force stop if needed
pkill -SIGKILL -f "python -m bot.main"
```

**Position Monitoring:**
Set risk limits in your configuration:

```yaml
# config.yaml - Risk settings
risk:
  max_position_size: 10000 # Maximum ADA position
  max_daily_loss: 1000 # Daily loss limit in USD
  emergency_stop: false # Emergency halt flag
  position_check_interval: 30 # Check frequency (seconds)
```

## Troubleshooting

### Common Issues

**Connection Problems:**

```sh
# Test exchange connectivity
curl -I https://api-staging.deltadefi.io/health
curl -I https://api.binance.com/api/v3/ping

# Verify WebSocket connectivity
wscat wss://stream.binance.com:9443/ws/adausdt@bookTicker
```

**Authentication Issues:**

```sh
# Test API key
curl -H "X-API-KEY: your_key" https://api-staging.deltadefi.io/account/balance

# Verify trading password setup
# (Validation occurs automatically during bot startup)
```

**Database Issues:**

```sh
# Rebuild database if corrupted (CAUTION: loses data)
rm trading_bot.db*
uv run python -m bot.main --init-db
```

### Error Codes

| Error Code | Description                 | Solution                           |
| ---------- | --------------------------- | ---------------------------------- |
| `CONN_001` | WebSocket connection failed | Check network and exchange status  |
| `AUTH_002` | API authentication failed   | Verify API key and permissions     |
| `RATE_003` | Rate limit exceeded         | Wait or reduce trading frequency   |
| `RISK_004` | Risk limit breached         | Check position size and daily loss |
| `DB_005`   | Database operation failed   | Check disk space and permissions   |

### Log Levels

Control logging verbosity:

```sh
# Debug mode (development)
LOG_LEVEL=DEBUG make run

# Production logging
LOG_LEVEL=INFO make run

# Minimal output
LOG_LEVEL=WARNING make run
```

## Configuration Reference

> **📝 Complete Reference**: See [CONFIG.md](../CONFIG.md) for all configuration options and the two-tier configuration system

### Essential Variables

| Variable            | Description                    | Default   | Required |
| ------------------- | ------------------------------ | --------- | -------- |
| `DELTADEFI_API_KEY` | DeltaDeFi API key              | -         | ✅       |
| `TRADING_PASSWORD`  | DeltaDeFi trading password     | -         | ✅       |
| `SYSTEM_MODE`       | Trading mode (testnet/mainnet) | `testnet` | ❌       |
| `TOTAL_SPREAD_BPS`  | Total spread in basis points   | `8`       | ❌       |

---

> **📚 Related Documentation:**
>
> - [Deployment Guide](03-deployment.md) - Production deployment and operations
> - [Architecture Overview](architecture/overview.md) - System design and components
> - [Development Guide](../DEVELOPMENT.md) - Code standards and development workflow
