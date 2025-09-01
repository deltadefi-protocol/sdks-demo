# Configuration Guide

The trading bot uses a **two-tier configuration system** that separates secrets from trading parameters.

## Configuration Files

### 1. `.env` - Secrets & Environment Settings

**Keep private** - Contains sensitive data that should never be committed to version control:

```bash
# Required API credentials
EXCHANGE__DELTADEFI_API_KEY=your_api_key_here
EXCHANGE__TRADING_PASSWORD=your_trading_password_here

# Environment-specific URLs
EXCHANGE__DELTADEFI_BASE_URL=https://api-staging.deltadefi.io
EXCHANGE__BINANCE_WS_URL=wss://stream.binance.com:9443/ws

# System settings
SYSTEM__MODE=testnet
SYSTEM__LOG_LEVEL=INFO
SYSTEM__DB_PATH=trading_bot.db
```

### 2. `config.yaml` - Trading Strategy Settings

**Version controlled** - Contains trading parameters that can be shared and modified:

```yaml
trading:
  symbol_src: ADAUSDT # Binance source symbol
  symbol_dst: ADAUSDM # DeltaDeFi destination symbol
  anchor_bps: 5 # Spread from Binance prices
  venue_spread_bps: 3 # Cross-venue risk buffer
  qty: 100.0 # Order quantity
  side_enable: ["bid", "ask"]

risk:
  max_position_size: 5000.0
  max_daily_loss: 1000.0
  emergency_stop: false
```

## Setup Instructions

1. **Copy environment template:**

   ```bash
   cp .env.example .env
   ```

2. **Fill in your DeltaDeFi credentials in `.env`:**

   - Get API key from DeltaDeFi platform
   - Use your trading password

3. **Customize trading strategy in `config.yaml`:**

   - Adjust spreads, position sizes, symbols as needed
   - These settings can be safely committed to git

4. **Run the bot:**

   ```bash
   python -m bot.main
   ```

## Configuration Priority

Settings are loaded in this order (later overrides earlier):

1. Default values in code
2. `config.yaml` file
3. `.env` environment variables
4. System environment variables

## Benefits of This Approach

✅ **Secrets stay private** - API keys never accidentally committed  
✅ **Strategy parameters in version control** - Easy to track changes  
✅ **Environment-specific deployments** - Different `.env` per environment  
✅ **Team collaboration** - Share `config.yaml` safely  
✅ **Configuration validation** - Pydantic validates all settings

## Environment Variables Override

You can still override any setting with environment variables using `__` delimiter:

```bash
# Override trading quantity
TRADING__QTY=200.0

# Override risk limits
RISK__MAX_POSITION_SIZE=10000.0
```

This is useful for deployment environments where you can't modify config files.
