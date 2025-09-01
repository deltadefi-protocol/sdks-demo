# Production Deployment Guide

Complete guide for deploying the DeltaDeFi trading bot in production environments.

> **📝 Development Setup**: For local development, see [User Guide](02-user-guide.md)

## Overview

This guide covers production deployment methods, monitoring setup, security hardening, and operational procedures for the DeltaDeFi trading bot.

### Prerequisites

- **Server Requirements**: Linux server (Ubuntu 20.04+), Python 3.11+, 2GB+ RAM, 10GB+ disk
- **Network**: Reliable internet with low latency to exchanges, outbound HTTPS/WSS access
- **Credentials**: DeltaDeFi API key with trading permissions, sufficient ADA/USDM balances

## Deployment Methods

### Method 1: Direct Installation (Recommended)

```sh
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone <repository-url> && cd trading-bot
uv venv && uv pip install -e .

# Configure production environment
cp .env.example .env.prod
# Edit .env.prod with production credentials

# Run with production config
uv run --env-file .env.prod python -m bot.main
```

### Method 2: Docker Deployment

**Production Dockerfile:**

```dockerfile
FROM python:3.11-slim AS base

# Install system dependencies and uv
RUN apt-get update && apt-get install -y curl sqlite3 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN groupadd -r trading && useradd -r -g trading trading

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv venv && uv pip install -e .

# Copy application
COPY bot/ ./bot/
COPY architecture/ ./architecture/
COPY docs/ ./docs/
COPY README.md ./

# Set up directories and permissions
RUN mkdir -p /app/logs /app/data && \
    chown -R trading:trading /app

USER trading

# Environment and health check
ENV PYTHONPATH=/app DB_PATH=/app/data/trading_bot.db LOG_LEVEL=INFO
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD sqlite3 /app/data/trading_bot.db "SELECT COUNT(*) FROM orders WHERE created_at > datetime('now', '-2 minutes');" || exit 1

CMD ["uv", "run", "python", "-m", "bot.main"]
```

**Docker Compose:**

```yaml
version: "3.8"

services:
  trading-bot:
    build: .
    container_name: deltadefi-trading-bot
    environment:
      - DELTADEFI_API_KEY=${DELTADEFI_API_KEY}
      - TRADING_PASSWORD=${TRADING_PASSWORD}
      - SYSTEM_MODE=${SYSTEM_MODE:-testnet}
      - TOTAL_SPREAD_BPS=${TOTAL_SPREAD_BPS:-8}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./backups:/app/backups
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

  # Automated database backup
  db-backup:
    image: alpine:latest
    volumes:
      - ./data:/data
      - ./backups:/backups
    command: >
      sh -c "while true; do
        cp /data/trading_bot.db /backups/trading_bot_backup_$$(date +%Y%m%d_%H%M%S).db;
        find /backups -name '*.db' -mtime +7 -delete;
        sleep 86400;
      done"
    restart: unless-stopped
```

**Deploy with Docker:**

```sh
# Create directories and environment
mkdir -p logs data backups
cp .env.example .env.prod
# Edit .env.prod with production values

# Build and start
docker-compose --env-file .env.prod up -d

# Monitor
docker-compose logs -f trading-bot
```

## Environment Configuration

> **📝 Complete Configuration**: See [CONFIG.md](../CONFIG.md) for full configuration system details

### Production Environment Variables

```bash
# Required
DELTADEFI_API_KEY=your_production_api_key
TRADING_PASSWORD=your_secure_trading_password
SYSTEM_MODE=mainnet

# Trading Parameters
TOTAL_SPREAD_BPS=6
QTY=500
SYMBOL_SRC=ADAUSDT
SYMBOL_DST=ADAUSDM

# Risk Management
MAX_POSITION_SIZE=50000
MAX_DAILY_LOSS=5000
EMERGENCY_STOP=false

# System
DB_PATH=/app/data/trading_bot.db
LOG_LEVEL=INFO
MAX_ORDERS_PER_SECOND=5
```

## System Service Management

### Systemd Service (Linux)

**Create `/etc/systemd/system/deltadefi-trading-bot.service`:**

```ini
[Unit]
Description=DeltaDeFi Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=trading
Group=trading
WorkingDirectory=/opt/trading-bot

Environment=PATH=/opt/trading-bot/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=/opt/trading-bot
EnvironmentFile=/opt/trading-bot/.env.prod

ExecStartPre=/bin/mkdir -p /opt/trading-bot/logs /opt/trading-bot/data
ExecStartPre=/bin/chown -R trading:trading /opt/trading-bot/logs /opt/trading-bot/data
ExecStart=/opt/trading-bot/.venv/bin/python -m bot.main

Restart=always
RestartSec=10
StartLimitInterval=300
StartLimitBurst=5

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/trading-bot/logs /opt/trading-bot/data

# Logging
StandardOutput=append:/opt/trading-bot/logs/service.log
StandardError=append:/opt/trading-bot/logs/service-error.log

[Install]
WantedBy=multi-user.target
```

**Service Management:**

```sh
# Install and start
sudo systemctl daemon-reload
sudo systemctl enable deltadefi-trading-bot
sudo systemctl start deltadefi-trading-bot

# Monitor
sudo systemctl status deltadefi-trading-bot
sudo journalctl -u deltadefi-trading-bot -f

# Operations
sudo systemctl restart deltadefi-trading-bot
sudo systemctl stop deltadefi-trading-bot
```

## Production Monitoring

### Structured Logging and Analysis

```sh
# Follow real-time logs
tail -f logs/trading-bot.log | jq '.'

# Monitor errors and warnings
tail -f logs/trading-bot.log | jq 'select(.level == "ERROR" or .level == "WARNING")'

# Track order activity
tail -f logs/trading-bot.log | jq 'select(.event | contains("order"))'

# System health monitoring
tail -f logs/trading-bot.log | jq 'select(.event == "Trading Bot Status")'
```

### Health Monitoring Script

**Create `health_check.sh`:**

```bash
#!/bin/bash
# Comprehensive health monitoring

# Check process
if ! pgrep -f "python -m bot.main" > /dev/null; then
    echo "ERROR: Trading bot process not running"
    exit 1
fi

# Check recent activity
if ! sqlite3 trading_bot.db "SELECT COUNT(*) FROM orders WHERE created_at > datetime('now', '-2 minutes');" | grep -q '[1-9]'; then
    echo "WARNING: No recent trading activity"
fi

# Database integrity
if ! sqlite3 trading_bot.db "PRAGMA integrity_check;" | grep -q "ok"; then
    echo "ERROR: Database integrity failed"
    exit 1
fi

# WebSocket connectivity check
if ! tail -n 20 logs/trading-bot.log | jq -r 'select(.websocket_connected == true)' | head -1 | grep -q .; then
    echo "ERROR: WebSocket disconnected"
    exit 1
fi

echo "OK: All health checks passed"
```

### Performance Monitoring

```sh
# Trading performance analysis
sqlite3 trading_bot.db <<EOF
.mode column
.headers on
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_orders,
    SUM(CASE WHEN state = 'filled' THEN 1 ELSE 0 END) as filled_orders,
    ROUND(AVG(CASE WHEN state = 'filled' THEN fill_price END), 4) as avg_fill_price,
    ROUND(SUM(CASE WHEN state = 'filled' THEN quantity * fill_price END), 2) as total_volume
FROM orders
WHERE created_at >= date('now', '-7 days')
GROUP BY DATE(created_at)
ORDER BY date DESC;
EOF

# Current position status
sqlite3 trading_bot.db "SELECT symbol, SUM(CASE WHEN side = 'buy' THEN quantity ELSE -quantity END) as net_position FROM orders WHERE state = 'filled' GROUP BY symbol;"
```

### Alerting System

**Email alerts for critical events (`alert_system.sh`):**

```bash
#!/bin/bash
EMAIL="admin@yourcompany.com"
SUBJECT_PREFIX="[TRADING BOT ALERT]"

# Check for critical errors
if tail -n 50 logs/trading-bot.log | jq -r 'select(.level == "ERROR")' | grep -q .; then
    ERROR_MSG=$(tail -n 50 logs/trading-bot.log | jq -r 'select(.level == "ERROR") | [.timestamp, .error] | @csv' | tail -3)
    echo "$ERROR_MSG" | mail -s "$SUBJECT_PREFIX Critical Errors" $EMAIL
fi

# Position limit monitoring
POSITION=$(sqlite3 trading_bot.db "SELECT ABS(SUM(CASE WHEN side = 'buy' THEN quantity ELSE -quantity END)) FROM orders WHERE state = 'filled';" 2>/dev/null || echo "0")
if [ "${POSITION:-0}" -gt "45000" ]; then
    echo "Position size: $POSITION exceeds 45,000 threshold" | mail -s "$SUBJECT_PREFIX Position Alert" $EMAIL
fi
```

## Security Hardening

### System Security

```sh
# System updates and firewall
sudo apt update && sudo apt upgrade -y
sudo ufw enable
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh

# Disable unnecessary services
sudo systemctl disable apache2 nginx bluetooth

# Install monitoring tools
sudo apt install fail2ban logwatch
sudo systemctl enable fail2ban
```

### Application Security

```sh
# Create dedicated user
sudo useradd -r -s /bin/false -m -d /opt/trading-bot trading

# Secure permissions
sudo chmod 700 /opt/trading-bot
sudo chmod 600 /opt/trading-bot/.env.prod
sudo chown -R trading:trading /opt/trading-bot

# Log rotation
sudo tee /etc/logrotate.d/trading-bot << EOF
/opt/trading-bot/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 trading trading
    postrotate
        systemctl reload deltadefi-trading-bot
    endscript
}
EOF
```

## Backup and Recovery

### Automated Backup

```bash
#!/bin/bash
# backup.sh - Automated backup system

BACKUP_DIR="/opt/backups/trading-bot"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Database backup
sqlite3 /opt/trading-bot/data/trading_bot.db ".backup $BACKUP_DIR/trading_bot_$TIMESTAMP.db"

# Configuration backup
tar -czf $BACKUP_DIR/config_$TIMESTAMP.tar.gz -C /opt/trading-bot .env.prod config.yaml

# Cleanup old backups
find $BACKUP_DIR -name "*.db" -mtime +$RETENTION_DAYS -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $TIMESTAMP"
```

### Disaster Recovery

```bash
#!/bin/bash
# recovery.sh - Disaster recovery procedure

echo "Starting recovery process..."

# Stop service
sudo systemctl stop deltadefi-trading-bot

# Restore database (replace TIMESTAMP with actual backup)
cp /opt/backups/trading-bot/trading_bot_YYYYMMDD_HHMMSS.db /opt/trading-bot/data/trading_bot.db
chown trading:trading /opt/trading-bot/data/trading_bot.db

# Verify integrity
sqlite3 /opt/trading-bot/data/trading_bot.db "PRAGMA integrity_check;"

# Restart service
sudo systemctl start deltadefi-trading-bot

# Verify recovery
sudo systemctl status deltadefi-trading-bot
echo "Recovery completed. Monitor logs for proper operation."
```

## Emergency Procedures

### Emergency Stop

```bash
#!/bin/bash
# emergency_stop.sh - Immediate trading halt

echo "EMERGENCY STOP INITIATED" | logger -t trading-bot-emergency

# Stop service
sudo systemctl stop deltadefi-trading-bot

# Kill any remaining processes
sudo pkill -f "python -m bot.main"

# Set emergency flag
sqlite3 /opt/trading-bot/data/trading_bot.db "UPDATE config SET value='true' WHERE key='emergency_stop';"

# Send alert
echo "EMERGENCY STOP: Trading halted due to emergency conditions" | \
    mail -s "[CRITICAL] Trading Bot Emergency Stop" admin@yourcompany.com

echo "Emergency stop completed at $(date)" >> /opt/trading-bot/logs/emergency.log
```

## Troubleshooting

### Performance Issues

```sh
# System resource monitoring
top -p $(pgrep -f "python -m bot.main")
iotop -p $(pgrep -f "python -m bot.main")

# Network connectivity
ss -tulpn | grep python
netstat -i

# Database performance
sqlite3 trading_bot.db "EXPLAIN QUERY PLAN SELECT * FROM orders WHERE created_at > datetime('now', '-1 hour');"
```

### Network Issues

```sh
# Exchange connectivity tests
curl -w "@curl-format.txt" -o /dev/null -s https://api.binance.com/api/v3/ping
curl -w "@curl-format.txt" -o /dev/null -s https://api-mainnet.deltadefi.io/health

# DNS resolution
nslookup api.binance.com
nslookup api-mainnet.deltadefi.io
```

---

> **📚 Related Documentation:**
>
> - [User Guide](02-user-guide.md) - Configuration and operation
> - [Configuration Guide](../CONFIG.md) - Complete configuration system
> - [Architecture Overview](architecture/overview.md) - System design details
