# User Demonstration Guide

A step-by-step guide for demonstrating the DeltaDeFi Trading Bot in a video walkthrough. This guide focuses on local deployment for easier demonstration.

**Video Duration**: 3-5 minutes
**Target Audience**: Developers and traders interested in automated market making

---

## Table of Contents

1. [Prerequisites Check](#1-prerequisites-check)
2. [Clone Repository](#2-clone-repository)
3. [Configure Environment Variables](#3-configure-environment-variables)
4. [Customize Trading Parameters](#4-customize-trading-parameters)
5. [Deploy Trading Bot Locally](#5-deploy-trading-bot-locally)
6. [Monitor Bot Activity](#6-monitor-bot-activity)
7. [Health Checks](#7-health-checks)
8. [Database Verification](#8-database-verification)
9. [Emergency Stop Demonstration](#9-emergency-stop-demonstration)
10. [Cleanup](#10-cleanup)

---

## 1. Prerequisites Check

### Show Terminal Commands

```bash
# Check Python version (requires 3.11+)
python3 --version

# Check if uv is installed
uv --version

# If uv not installed, show installation
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Expected Output

```
Python 3.11.x (or higher)
uv 0.x.x
```

---

## 2. Clone Repository

### Terminal Commands

```bash
# Clone the repository (replace with actual repo URL)
git clone https://github.com/deltadefi-protocol/sdks-demo.git
cd sdks-demo/trading-bot

# Show project structure
ls -la
```

### Expected Output

```
bot/
docs/
tests/
config.yaml
.env.example
Dockerfile
Makefile
README.md
pyproject.toml
...
```

---

## 3. Configure Environment Variables

### Step 3.1: Copy Environment File

```bash
# Copy the example environment file
cp .env.example .env

# Show the file structure
cat .env.example
```

### Expected Output

```bash
# DeltaDeFi API Credentials (REQUIRED)
EXCHANGE__DELTADEFI_API_KEY=your_api_key_here
EXCHANGE__TRADING_PASSWORD=your_trading_password_here

# System Configuration
SYSTEM__MODE=testnet
SYSTEM__LOG_LEVEL=INFO
SYSTEM__DB_PATH=trading_bot.db
...
```

### Step 3.2: Edit Environment File

```bash
# Open .env in your preferred editor
# For demo purposes, show editing the file
nano .env  # or vim, code, etc.
```

### Configuration to Set

```bash
# REQUIRED: Set your DeltaDeFi credentials
EXCHANGE__DELTADEFI_API_KEY=sk_test_abc123xyz...
EXCHANGE__TRADING_PASSWORD=your_secure_password

# Use testnet for demonstration
SYSTEM__MODE=testnet

# Set log level to INFO for clearer output
SYSTEM__LOG_LEVEL=INFO

# Database file location
SYSTEM__DB_PATH=trading_bot.db
```

---

## 4. Customize Trading Parameters

### Step 4.1: View Configuration File

```bash
# Display the trading configuration
cat config.yaml
```

### Expected Output

```yaml
trading:
  symbol_src: ADAUSDT # Binance source
  symbol_dst: ADAUSDM # DeltaDeFi destination

  # Multi-layer strategy
  base_spread_bps: 8 # Starting spread
  tick_spread_bps: 10 # Spread between layers
  num_layers: 10 # Layers per side
  total_liquidity: 5000.0 # Total liquidity

  # Asset ratio management
  target_asset_ratio: 1.0 # 1:1 USDM:ADA
  ratio_tolerance: 0.1 # 10% tolerance

risk:
  max_position_size: 5000.0
  max_daily_loss: 1000.0
  max_open_orders: 50
  emergency_stop: false

system:
  max_orders_per_second: 5.0
  cleanup_unregistered_orders: true
```

### Step 4.2: Explain Key Parameters

**Highlight each section in the video:**

#### Trading Parameters

| Parameter            | Value  | Description                                |
| -------------------- | ------ | ------------------------------------------ |
| `base_spread_bps`    | 8      | Starting spread from Binance price (0.08%) |
| `tick_spread_bps`    | 10     | Additional spread per layer (0.10%)        |
| `num_layers`         | 10     | Number of price levels per side            |
| `total_liquidity`    | 5000.0 | Total capital to deploy                    |
| `target_asset_ratio` | 1.0    | Target 1:1 USDM:ADA ratio                  |

#### Risk Parameters

| Parameter           | Value  | Description               |
| ------------------- | ------ | ------------------------- |
| `max_position_size` | 5000.0 | Maximum position size     |
| `max_daily_loss`    | 1000.0 | Daily loss limit          |
| `max_open_orders`   | 50     | Maximum concurrent orders |
| `emergency_stop`    | false  | Emergency halt flag       |

### Step 4.3: Customize for Demo

```bash
# For demonstration, you might want smaller values
# Edit config.yaml
nano config.yaml
```

**Suggested Demo Values:**

```yaml
trading:
  total_liquidity: 3000.0 # Smaller for demo
  num_layers: 5 # Fewer layers for clarity

risk:
  max_position_size: 3000.0 # Lower limits for safety
  max_daily_loss: 500.0
```

---

## 5. Deploy Trading Bot Locally

### Step 5.1: Install Dependencies

```bash
# Create virtual environment for project dependencies installation
make venv

# Install project dependencies
make install

# Install git hooks for development
make hooks
```

### Expected Output

```
Installing dependencies with uv...
✓ Dependencies installed successfully
✓ Git hooks installed
```

### Step 5.2: Start the Trading Bot

```bash
# Start the bot with default configuration
make run
```

### Step 5.3: Observe Initial Activity (Expected output example)

**Point out key events in the logs:**

1. ✅ Database initialization

```json
{
  "event": "Database initialized",
  "level": "INFO",
  "db_path": "trading_bot.db"
}
```

2. ✅ WebSocket connections (Binance + DeltaDeFi)

```json
{"event": "Connecting to Binance WebSocket", "level": "INFO", "symbol": "ADAUSDT"}
{"event": "Connected to Binance WebSocket successfully", "level": "INFO"}
{"event": "Connecting to DeltaDeFi", "level": "INFO", "mode": "testnet"}
{"event": "WebSocket connected successfully", "level": "INFO"}
```

3. ✅ Quote generation

```json
{
  "quote_id": "quote_id",
  "symbol_dst": "ADAUSDM",
  "bid_price": 0.634592,
  "ask_price": 0.635708,
  "status": "orders_submitted",
  "event": "\ud83c\udfaf Quote processed and orders submitted",
  "logger": "__main__",
  "level": "info",
  "timestamp": "2025-10-19T10:10:14.456531Z"
}
```

4. ✅ Order Submitteed to Pipeline

```json
{
  "order_id": "oms_1760868610328189",
  "quote_id": "8f93873f-01bb-4890-bc1e-ec44cac12471",
  "external_order_id": null,
  "symbol": "ADAUSDM",
  "side": "sell",
  "event": "Order submitted to DeltaDeFi",
  "logger": "bot.quote_to_order_pipeline",
  "level": "info",
  "timestamp": "2025-10-19T10:10:13.737666Z"
}
```

5. ✅ Order Being Submitted to Exchange

```json
{
  "symbol": "ADAUSDM",
  "side": "sell",
  "type": "limit",
  "quantity": 314,
  "price": 0.6376,
  "original_price": 0.637614,
  "kwargs": {},
  "event": "Submitting order",
  "logger": "bot.deltadefi",
  "level": "info",
  "timestamp": "2025-10-19T10:10:13.737940Z"
}
```

6. ✅ Order Successfully Accepted by Exchange

```json
{
  "result": {
    "order": {
      "order_id": "35efe46e-1fd0-4de8-8b9b-5b1fa25ef9f2",
      "status": "processing",
      "symbol": "ADAUSDM",
      "orig_qty": "314",
      "executed_qty": "0",
      "side": "sell",
      "price": 0.6376,
      "type": "limit",
      "fee_charged": "0",
      "fee_unit": "c69b981db7a65e339a6d783755f85a2e03afa1cece9714c55fe4c9135553444d",
      "executed_price": 0,
      "slippage": "0",
      "create_time": 1760868614,
      "update_time": 1760868614
    }
  },
  "symbol": "ADAUSDM",
  "side": "sell",
  "event": "Order submitted successfully",
  "logger": "bot.deltadefi",
  "level": "info",
  "timestamp": "2025-10-19T10:10:14.071430Z"
}
```

---

## 6. Monitor Bot Activity

### Step 6.1: Watch Real-Time Logs

You could watch the real-time logs in the same terminal that you run the `make run` command

### Step 6.2: Key Metrics to Highlight

**Status Report Example:**

```json
{
  "uptime_seconds": 228,
  "binance_messages": 5650,
  "quotes_generated": 5,
  "orders_submitted": 2,
  "last_quote_age_seconds": 57,
  "open_orders": 0,
  "max_orders": 50,
  "order_utilization_pct": 0.0,
  "total_positions": 0,
  "daily_pnl": 0.0,
  "active_quotes": 0,
  "pipeline_success_rate": 1.0,
  "websocket_connected": true,
  "balance_count": 0,
  "fills_processed": 0,
  "cleanup_enabled": true,
  "cleanup_runs": 4,
  "unregistered_orders_cancelled": 80,
  "cleanup_errors": 0,
  "event": "\ud83d\udcca Trading Bot System Status",
  "logger": "__main__",
  "level": "info",
  "timestamp": "2025-10-19T10:47:09.379661Z"
}
```

### Step 6.3: Explain Metrics

**Highlight key metrics on screen:**

| Metric                  | Example | Meaning                               |
| ----------------------- | ------- | ------------------------------------- |
| `uptime`                | 228     | Bot running time                      |
| `quotes_generated`      | 120     | Quotes created from Binance data      |
| `orders_submitted`      | 2400    | Total orders sent to exchange         |
| `open_orders`           | 20      | Current active orders (2 layers × 10) |
| `order_utilization_pct` | 40%     | % of max allowed orders               |
| `daily_pnl`             | +12.50  | Profit/loss today                     |
| `fills_processed`       | 15      | Orders that executed                  |
| `websocket_connected`   | true    | Live data feed status                 |

---

## 7. Emergency Stop Demonstration

### Graceful Shutdown (Recommended)

```bash
# Send SIGTERM in another terminal for graceful shutdown
pkill -SIGTERM -f "python -m bot.main"
```

**Expected Behavior:**

- Bot receives shutdown signal
- Exits cleanly

**Expected Log Output:**

```json
{
  "event": "\u2705 Trading Bot System stopped gracefully",
  "logger": "__main__",
  "level": "info",
  "timestamp": "2025-10-21T10:50:02.769976Z"
}
```

---

## 8. Cleanup

### Remove Database

```bash
# Remove database (optional - for demo reset)
rm trading_bot.db trading_bot.db-shm trading_bot.db-wal
```

### Remove Logs

```bash
# Clear logs
rm -rf logs/
```
