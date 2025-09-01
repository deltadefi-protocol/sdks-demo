# Deployment

## Local Development

### Quick Start

```sh
# Install and run
make install
make run
```

### With Custom Parameters

```sh
uv run python -m bot.main --anchor-bps 5 --venue-spread-bps 3 --qty 100
```

## Production Deployment

### Using uv (recommended)

```sh
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone <repository-url>
cd trading-bot
uv venv
uv pip install -e .

# Set up environment
cp .env.example .env
# Edit .env with production values

# Run
uv run python -m bot.main
```

### Using pip

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Set up environment
cp .env.example .env
# Edit .env with production values

# Run
python -m bot.main
```

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY bot/ ./bot/
COPY .env.example ./.env

# Install dependencies
RUN uv venv && uv pip install -e .

# Set environment variables
ENV BINANCE_WS_URL="wss://stream.binance.com:9443/ws/adausdt@bookTicker"
ENV DELTADEFI_BASE_URL="https://api-staging.deltadefi.io"
ENV DELTADEFI_API_KEY=""

# Run the bot
CMD ["uv", "run", "python", "-m", "bot.main"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  trading-bot:
    build: .
    environment:
      - DELTADEFI_API_KEY=${DELTADEFI_API_KEY}
      - DELTADEFI_BASE_URL=https://api-staging.deltadefi.io
      - BINANCE_WS_URL=wss://stream.binance.com:9443/ws/adausdt@bookTicker
    volumes:
      - ./logs:/app/logs
    restart: unless-stopped
```

### Build and Run

```sh
# Build image
docker build -t trading-bot .

# Run with environment variables
docker run -e DELTADEFI_API_KEY=your_api_key trading-bot

# Or use docker-compose
docker-compose up -d
```

## Environment Variables

Required environment variables:

```bash
# DeltaDeFi Configuration
DELTADEFI_API_KEY=your_api_key_here
DELTADEFI_BASE_URL=https://api-staging.deltadefi.io

# Binance WebSocket
BINANCE_WS_URL=wss://stream.binance.com:9443/ws/adausdt@bookTicker

# Optional: Trading Parameters
ANCHOR_BPS=5
VENUE_SPREAD_BPS=3
QUANTITY=100
```

## Monitoring and Logging

The bot outputs structured JSON logs. To monitor in production:

```sh
# Follow logs
tail -f logs/trading-bot.log | jq

# Monitor specific events
tail -f logs/trading-bot.log | jq 'select(.event == "order_submitted")'

# Check system status
tail -f logs/trading-bot.log | jq 'select(.event == "Trading Bot Status")'
```

## Health Checks

The bot logs status every 30 seconds. For health monitoring:

```sh
# Check if bot is responsive (should show recent status within 60s)
tail -n 100 logs/trading-bot.log | jq 'select(.event == "Trading Bot Status") | .timestamp' | head -1
```

## Systemd Service (Linux)

Create `/etc/systemd/system/trading-bot.service`:

```ini
[Unit]
Description=DeltaDeFi Trading Bot
After=network.target

[Service]
Type=exec
User=trading
WorkingDirectory=/opt/trading-bot
Environment=PATH=/opt/trading-bot/.venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=/opt/trading-bot/.env
ExecStart=/opt/trading-bot/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```sh
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```
