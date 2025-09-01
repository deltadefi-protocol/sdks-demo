# Architecture

## Goal

Continuously mirror Binance BBO for `ADAUSDT` and post maker limit orders on DeltaDeFi `ADAUSDM` with an added spread buffer.

## Implementation Status

The current implementation includes:

- **WebSocket Market Data**: Real-time Binance WebSocket connection for ADAUSDT book ticker
- **Order Management System**: Rate-limited order manager with token bucket rate limiter (5 orders/second)
- **Structured Logging**: JSON structured logs with contextual information
- **Async/Await Architecture**: Modern Python async patterns throughout
- **Type Safety**: Full type hints and mypy type checking
- **Code Quality**: Ruff linting, formatting, and pre-commit hooks

## Technology Stack

- **Python 3.11+**: Modern Python with async/await
- **uv**: Fast Python package manager and dependency resolver
- **Pydantic**: Data validation and settings management
- **structlog**: Structured logging with JSON output
- **aiohttp**: Async HTTP client for API calls
- **pytest**: Testing framework with async support

## High-level design

```sh
[Binance WS: adausdt@bookTicker]
         │
         ▼
   [Quote Engine]
   - total_bps = anchor_bps + venue_spread_bps
   - bid = bestBid * (1 - total_bps/10000)
   - ask = bestAsk * (1 + total_bps/10000)
         │
         ▼
[DeltaDeFi Orderer]
  build /orders/build → sign(tx_hex) → submit /orders/submit
         │
         ▼
[Account WS stream]  (fills / order status)

```

## External interfaces

- Binance market data (WS): wss://stream.binance.com:9443/ws/adausdt@bookTicker (individual symbol book-ticker, real-time; supports combined streams).

- DeltaDeFi REST base (pre-prod): <https://api-staging.deltadefi.io> (Mainnet TBA). Auth via X-API-KEY.

- DeltaDeFi order flow: build POST /orders/build → returns {order_id, tx_hex}; sign tx; submit POST /orders/submit with {order_id, signed_tx}. Use type=limit, symbol="ADAUSDM".

- DeltaDeFi account WS: /accounts/stream?api_key=… (balances, open_orders, trading_history, orders_history).

## Core components

- Binance WS client: resilient WS (ping/pong, reconnect <24h).

- Quote engine: computes padded quotes from Binance BBO; clamps to min/max price, size; optional guard not to cross DeltaDeFi top of book (subscribe /market/depth/:symbol if needed).

- Orderer: DeltaDeFi build→sign→submit; idempotent client order IDs (app-side), retry with backoff on 5xx/timeout

- Account feed: consume order/balance updates; this is the source of truth for state.

## Config

```yaml
symbol_src: ADAUSDT # Binance
symbol_dst: ADAUSDM # DeltaDeFi
anchor_bps: 5 # distance from Binance BBO
venue_spread_bps: 3 # extra buffer for cross-venue risk
side_enable: [bid, ask] # which sides to quote
qty: 100 # ADA units; validate against balances
max_skew: 2_000 # ADA; pause bids if long beyond this
ddefi_api_key: "..."
```

## Connection management

- 24h session rule: single connections to stream.binance.com are closed at ~24h; implement reconnect & resubscribe. (Documented on User Data Streams & SBE; apply same policy expectation to market streams).

- Ping/pong: respond to server pings to avoid disconnects. (General WS rule)

## Config surface (env or YAML)

- symbol[], bps, min_quote_size, max_inv, max_open_notional, requote_tick_threshold, min_requote_ms, stale_ms, mode={paper|testnet|live}, enable_oms={true|false}.

## Failure & safety

- Stale feed ⇒ cancel quotes (if OMS enabled).

- Clock/latency drift ⇒ widen or pause.

- Rate limits ⇒ exponential backoff; respect request weights (see Spot docs).
