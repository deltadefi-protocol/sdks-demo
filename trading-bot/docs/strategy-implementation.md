# Strategy Implementation

1. Trigger of Actions: bot/main.py:242-290

   The main trigger is Binance WebSocket price updates. The entry point is \_process_binance_message() which:

   - Receives real-time price data from Binance
   - Creates BookTicker objects
   - Generates quotes via QuoteEngine
   - Processes quotes through the pipeline

2. When to Cancel Orders: bot/quote_to_order_pipeline.py:757-819

   Order replacement strategy - cancels existing orders before creating new ones:

   - cancel_active_quotes_for_symbol() - cancels all active quotes/orders for a symbol
   - Triggered on every new quote (aggressive replacement enabled by default)
   - Also cancels on quote expiration: cleanup_expired_quotes() at line 821

3. When to Open Orders: bot/quote.py:72-127

   Quote generation logic in generate_quote():

   - Time threshold: Must wait min_requote_ms (100ms default) between quotes
   - Price threshold: Price must move by requote_tick_threshold (0.0001 default)
   - Data freshness: Market data must be less than stale_ms (5000ms) old
   - Sides enabled: Only creates orders for enabled sides (["bid", "ask"] by default)

4. Order Size Determination: bot/quote.py:129-191

   In \_calculate_bid() and \_calculate_ask():

   Line 145-149

   max_orders = settings.risk.max_open_orders
   target_notional_per_order = settings.risk.max_position_size / max_orders
   bid_qty = target_notional_per_order / bid_price
   bid_qty = max(bid_qty, settings.trading.min_quote_size)

   Size calculation: max_position_size / max_open_orders = per_order_size

   - Default: 5000 / 10 = 500 notional per order
   - Minimum size: min_quote_size (10.0 default)
   - Optional maximum: trading.qty if configured

5. Action Frequency: bot/config.py:40-48

   Rate limiting and timing controls:

   - Min requote interval: min_requote_ms = 100ms (max 10 quotes/second)
   - Max order rate: max_orders_per_second = 5.0 (DeltaDeFi limit)
   - Quote TTL: quote_ttl_ms = 2000ms (quotes expire after 2 seconds)
   - Price threshold: requote_tick_threshold = 0.0001 (must move 0.01%)

   The bot runs a market-making strategy with aggressive order replacement, constantly updating quotes based on
   Binance prices with configured spreads and risk limits.
