# Trading Strategy Specification

## Overview

This document specifies the business logic and trading strategy for the DeltaDeFi Trading Bot - a cross-exchange market making system that provides liquidity by continuously quoting bid and ask prices on DeltaDeFi based on real-time Binance market data.

### Strategy Type

Cross-Exchange Market Making

### Market Pair

- **Source Market**: Binance ADAUSDT (data feed)
- **Target Market**: DeltaDeFi ADAUSDM (order execution)

## Market Data Ingestion

### Data Source

- **Primary Feed**: Binance WebSocket book ticker stream
- **Update Frequency**: Real-time (typically 100ms intervals)
- **Data Points**: Best bid/ask prices and quantities

### Data Validation

- **Staleness Check**: Market data older than 5000ms is rejected
- **Price Validation**: Ensures bid < ask and prices > 0
- **Symbol Matching**: Filters for ADAUSDT updates only

## Behavior Description

1. Able to provide a depth of liquidity.

   Spread the liquidity across layers. e.g.

   With `total_liquidity=5000`, `num_layers=10`, `layer_liquidity_multiplier=1.0` (100%):

   **Base calculation**: 5000 ÷ 10 = 500 ADA base per layer
   **Layer progression** (100% growth per layer):

   - Layer 1: 500 × 1.0 = 500 ADA → **90.9 ADA** (after price adjustment)
   - Layer 2: 500 × 2.0 = 1000 ADA → **181.8 ADA**
   - Layer 3: 500 × 3.0 = 1500 ADA → **272.7 ADA**
   - Layer 4: 500 × 4.0 = 2000 ADA → **363.6 ADA**
   - Layer 5: 500 × 5.0 = 2500 ADA → **454.5 ADA**
   - Layer 6: 500 × 6.0 = 3000 ADA → **545.5 ADA**
   - Layer 7: 500 × 7.0 = 3500 ADA → **636.4 ADA**
   - Layer 8: 500 × 8.0 = 4000 ADA → **727.3 ADA**
   - Layer 9: 500 × 9.0 = 4500 ADA → **818.2 ADA**
   - Layer 10: 500 × 10.0 = 5000 ADA → **909.1 ADA**

2. Assume using all capital in the accounts for market making activity

3. Specify a golden ratio of assets. E.g. 1:1, keeping always keeping 1:1 in USDM value for both USDM and ADA

4. Adjust liquidity depth when out of ratio. E.g. when there is more USDM than ADA in the pool, more liquidity in buying ADA limit orders will be on book with less spread. Meanwhile, liquidity in sell ADA limit order will be placed with higher spread.

5. Any orders not registered in the trading bot db will be cancelled.

6. Expected behaviour will be orders moving along the market price at binance
