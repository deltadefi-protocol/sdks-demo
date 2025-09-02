# Trading Strategy Specification

Cross-exchange market making system providing liquidity on DeltaDeFi based on Binance market data.

## Market Pair

- **Source**: Binance ADAUSDT (data feed)
- **Target**: DeltaDeFi ADAUSDM (order execution)

## Objective

Mirror Binance prices with configurable spreads while maintaining 1:1 USDM:ADA value ratio.

## Key Behaviors

1. Spread liquidity across multiple price layers
2. Use 100% of available capital for market making
3. Maintain 1:1 USDM:ADA value ratio
4. Adjust spreads/liquidity based on asset imbalances
5. Cancel unregistered orders
6. Follow Binance price movements

## Market Data

- **Source**: Binance WebSocket book ticker (ADAUSDT)
- **Frequency**: Real-time (~100ms intervals)
- **Validation**: Reject data >5000ms old, ensure bid < ask > 0

## Quote Generation

### Spread Configuration

- `base_spread_bps`: Starting spread from refernce price (8 bps)
- `tick_spread_bps`: Incremental spread between layers (10 bps = 0.1%)
- `num_layers`: Layers per side (10)
- `layer_liquidity_multiplier`: Liquidity growth per layer (1.0 = 100%)

### Price Calculation

The multi-layer prices are calculated based on below:

```text
bid_reference_price = binance_bid
ask_reference_price = binance_ask
for layer_i in range(1, num_layers + 1):
    spread_bps = base_spread_bps + (layer_i - 1) * tick_spread_bps
    bid_price_layer_i = bid_reference_price * (1 - spread_bps/10000)
    ask_price_layer_i = ask_reference_price * (1 + spread_bps/10000)
```

### Requote Triggers

1. 100ms elapsed since last quote
2. Price moves ≥ tick_spread_bps / 2 (0.04% in this example)
3. Startup/reconnection

### Quote Validation

- Ensure bid < ask
- Enable bid/ask sides independently

## Asset Ratio Management

### Target Ratio: 1:1 USDM:ADA value

- `current_ratio = usdm_value / ada_value`
- Monitor via WebSocket balance feeds

### Dynamic Adjustment

The detail adjustment refer to [docs/price-skew.md](./price-skew.md)

#### Excess USDM (USDM > ADA)

- **Bid orders**: More liquidity, tighter spreads, larger sizes
- **Ask orders**: Less liquidity, wider spreads, smaller sizes

#### Excess ADA (ADA > USDM)

- **Ask orders**: More liquidity, tighter spreads, larger sizes
- **Bid orders**: Less liquidity, wider spreads, smaller sizes

### Capital Utilization

- Use 100% of available balance for market making
- Adjust bid/ask allocation based on asset ratio
- Maintain minimal operational reserves (configure in `config.yaml`)

## Order Management

### Replacement Strategy

- Cancel ALL existing orders before submitting new layer set
- Replace entire layer structure atomically
- Ensure consistent liquidity distribution

### Order Cleanup

- All orders must be registered in database
- Cancel unregistered orders (startup + periodic checks)
- Prevent external order interference

### Order Sizing

#### Layer Sizing Formula

```text
base_layer_notional = total_liquidity / num_layers
for layer_i in range(1, num_layers + 1):
    growth_factor = 1 + (layer_i - 1) * layer_liquidity_multiplier
    layer_quantity = (base_layer_notional * growth_factor) / layer_price
```

#### Example (5000 ADA, 10 layers, 100% growth)

Base: 500 ADA per layer

- Layer 1: 90.9 ADA (8 bps)
- Layer 2: 181.8 ADA (18 bps)
- Layer 3: 272.7 ADA (28 bps)
- ...
- Layer 10: 909.1 ADA (98 bps)

### Order States

`IDLE → PENDING → WORKING → FILLED/CANCELLED/REJECTED`

## Risk Management

### Limits

- Max position: 5000 ADA
- Max skew: 2000 ADA
- Max open orders: 50
- Max daily loss: 1000 units
- Emergency stop available

### Pre-Trade Checks

1. Emergency stop not active
2. Position limits not exceeded
3. Daily loss limits not hit
4. Order count within limits
5. Minimum size requirements met

## Execution Timing

- Quote generation: Max 10/second, min 100ms interval
- Order submission: Max 5/second (API limit)
- Quote TTL: 2000ms
- Data aggregation: 200ms window

## Fill Handling

- Real-time WebSocket fill tracking
- Position calculation with weighted average pricing
- Realized/unrealized PnL tracking
- Fill reconciliation between OMS and exchange

## State Persistence

- Database storage of quotes and orders
- Order state machine persistence
- Reliable delivery with retry logic

## Configuration Parameters

### Trading Parameters

- `symbol_src`: "ADAUSDT"
- `symbol_dst`: "ADAUSDM"
- `base_spread_bps`: 8
- `tick_spread_bps`: 10
- `num_layers`: 10
- `layer_liquidity_multiplier`: 1.0
- `total_liquidity`: 5000.0

### Asset Ratio Parameters

- `target_asset_ratio`: 1.0
- `ratio_tolerance`: 0.1
- `spread_adjustment_factor`: 2.0
- `liquidity_adjustment_factor`: 1.5
- `use_full_capital`: true

### Risk Parameters

- `max_position_size`: 5000.0
- `max_daily_loss`: 1000.0
- `max_open_orders`: 50
- `max_skew`: 2000.0
- `emergency_stop`: false

### Timing Parameters

- `min_requote_ms`: 100
- `requote_tick_threshold`: 0.0001
- `stale_ms`: 5000
- `quote_ttl_ms`: 2000
- `cleanup_check_interval_ms`: 30000

## Performance Targets

- Sub-200ms quote latency
- ±1bp spread accuracy
- 99%+ uptime
- 95%+ order fill rate
- 98%+ capital deployment
- 1:1 USDM:ADA ratio maintenance
