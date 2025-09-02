-- Trading Bot Database Schema
-- SQLite DDL for quotes, orders, fills, and outbox pattern

-- Enable foreign key constraints
PRAGMA foreign_keys = ON;

-- ============================================================================
-- QUOTES TABLE
-- Stores generated quotes from the quote engine
-- ============================================================================
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id TEXT NOT NULL UNIQUE,              -- UUID for quote identification
    timestamp REAL NOT NULL,                    -- Unix timestamp when quote was generated
    symbol_src TEXT NOT NULL,                   -- Source symbol (e.g., "ADAUSDT")  
    symbol_dst TEXT NOT NULL,                   -- Destination symbol (e.g., "ADAUSDM")
    
    -- Source market data
    source_bid_price REAL NOT NULL,
    source_bid_qty REAL NOT NULL,
    source_ask_price REAL NOT NULL,
    source_ask_qty REAL NOT NULL,
    
    -- Generated quote data
    bid_price REAL,                             -- NULL if bid side disabled
    bid_qty REAL,                               -- NULL if bid side disabled
    ask_price REAL,                             -- NULL if ask side disabled
    ask_qty REAL,                               -- NULL if ask side disabled
    
    -- Order tracking
    bid_order_id TEXT,                          -- Order ID for bid side
    ask_order_id TEXT,                          -- Order ID for ask side
    
    -- Status tracking
    status TEXT NOT NULL DEFAULT 'generated' CHECK (
        status IN ('generated', 'persisted', 'orders_created', 'orders_submitted', 'expired', 'cancelled')
    ),
    
    -- Metadata
    spread_bps REAL,                            -- Calculated spread in basis points
    mid_price REAL,                             -- Mid price from generated quote
    total_spread_bps INTEGER NOT NULL,          -- Total spread used (anchor + venue)
    sides_enabled TEXT NOT NULL,                -- JSON array of enabled sides
    strategy TEXT DEFAULT 'market_maker',       -- Trading strategy used
    
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    updated_at REAL NOT NULL DEFAULT (unixepoch()),
    expires_at REAL                                 -- When quote expires (unix timestamp)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_quotes_quote_id ON quotes(quote_id);
CREATE INDEX IF NOT EXISTS idx_quotes_timestamp ON quotes(timestamp);
CREATE INDEX IF NOT EXISTS idx_quotes_symbol_dst ON quotes(symbol_dst);
CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status);
CREATE INDEX IF NOT EXISTS idx_quotes_created_at ON quotes(created_at);

-- ============================================================================
-- ORDERS TABLE
-- Tracks all orders throughout their lifecycle
-- ============================================================================
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,              -- Client-side order ID (UUID)
    quote_id TEXT,                              -- Reference to originating quote (UUID)
    
    -- Order details
    symbol TEXT NOT NULL,                       -- Trading symbol (e.g., "ADAUSDM")
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell', 'bid', 'ask')),
    order_type TEXT NOT NULL CHECK (order_type IN ('limit', 'market')),
    price REAL,                                 -- NULL for market orders
    quantity REAL NOT NULL,
    
    -- Order state
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'submitted', 'filled', 'partially_filled', 'canceled', 'rejected', 'failed')
    ),
    
    -- DeltaDeFi specific
    deltadefi_order_id TEXT,                    -- DeltaDeFi's order ID
    tx_hex TEXT,                                -- Transaction hex from build endpoint
    signed_tx TEXT,                             -- Signed transaction
    tx_hash TEXT,                               -- Transaction hash after submission
    
    -- Execution tracking
    filled_quantity REAL NOT NULL DEFAULT 0,
    remaining_quantity REAL,                    -- quantity - filled_quantity
    avg_fill_price REAL,                        -- Average fill price
    
    -- Timestamps
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    submitted_at REAL,                          -- When submitted to DeltaDeFi
    last_updated REAL NOT NULL DEFAULT (unixepoch()),
    
    -- Error tracking
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    FOREIGN KEY (quote_id) REFERENCES quotes(quote_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_deltadefi_id ON orders(deltadefi_order_id);

-- ============================================================================
-- FILLS TABLE
-- Records all trade executions/fills
-- ============================================================================
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id TEXT NOT NULL UNIQUE,               -- Unique fill identifier
    order_id TEXT NOT NULL,                     -- Reference to parent order
    
    -- Fill details
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell', 'bid', 'ask')),
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    
    -- Execution details
    executed_at REAL NOT NULL,                  -- When the fill occurred
    trade_id TEXT,                              -- Exchange trade ID
    commission REAL DEFAULT 0,                  -- Trading fees
    commission_asset TEXT,                      -- Asset used for fees
    
    -- Metadata
    is_maker BOOLEAN DEFAULT TRUE,              -- Whether this was a maker fill
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_fill_id ON fills(fill_id);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_symbol ON fills(symbol);
CREATE INDEX IF NOT EXISTS idx_fills_executed_at ON fills(executed_at);

-- ============================================================================
-- OUTBOX TABLE
-- Implements transactional outbox pattern for reliable message delivery
-- ============================================================================
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,              -- Unique event identifier
    event_type TEXT NOT NULL,                   -- Type of event (order_submit, order_cancel, etc.)
    aggregate_id TEXT NOT NULL,                 -- ID of the aggregate (order_id, etc.)
    
    -- Event payload
    payload TEXT NOT NULL,                      -- JSON payload for the event
    
    -- Processing state
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'completed', 'failed', 'dead_letter')
    ),
    
    -- Retry logic
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 5,
    next_retry_at REAL,                         -- When to retry (unix timestamp)
    
    -- Timestamps
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    processed_at REAL,
    
    -- Error tracking
    error_message TEXT,
    last_error_at REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_event_id ON outbox(event_id);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);
CREATE INDEX IF NOT EXISTS idx_outbox_event_type ON outbox(event_type);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate_id ON outbox(aggregate_id);
CREATE INDEX IF NOT EXISTS idx_outbox_next_retry ON outbox(next_retry_at);
CREATE INDEX IF NOT EXISTS idx_outbox_created_at ON outbox(created_at);

-- ============================================================================
-- POSITIONS TABLE
-- Tracks current positions and P&L
-- ============================================================================
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,                -- Trading symbol
    
    -- Position details
    quantity REAL NOT NULL DEFAULT 0,           -- Net position (positive = long, negative = short)
    avg_entry_price REAL DEFAULT 0,             -- Average entry price
    
    -- P&L tracking
    realized_pnl REAL NOT NULL DEFAULT 0,       -- Realized profit/loss
    unrealized_pnl REAL DEFAULT 0,              -- Unrealized profit/loss (calculated)
    
    -- Risk metrics
    max_position REAL DEFAULT 0,                -- Maximum position size reached
    drawdown REAL DEFAULT 0,                    -- Current drawdown
    
    -- Timestamps
    created_at REAL NOT NULL DEFAULT (unixepoch()),
    last_updated REAL NOT NULL DEFAULT (unixepoch())
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);

-- ============================================================================
-- ACCOUNT_BALANCES TABLE
-- Tracks account balances from DeltaDeFi
-- ============================================================================
CREATE TABLE IF NOT EXISTS account_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,                        -- Asset symbol (e.g., "ADA", "USDM")
    
    -- Balance details
    available REAL NOT NULL DEFAULT 0,          -- Available balance
    locked REAL NOT NULL DEFAULT 0,             -- Locked in orders
    total REAL NOT NULL DEFAULT 0,              -- Total balance (available + locked)
    
    -- Timestamps
    updated_at REAL NOT NULL DEFAULT (unixepoch()),
    created_at REAL NOT NULL DEFAULT (unixepoch())
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_balances_asset ON account_balances(asset);

-- ============================================================================
-- TRADING_SESSIONS TABLE  
-- Tracks bot trading sessions for analytics
-- ============================================================================
CREATE TABLE IF NOT EXISTS trading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,            -- Unique session identifier
    
    -- Session details
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'stopped', 'error')
    ),
    
    -- Configuration snapshot
    config_snapshot TEXT NOT NULL,              -- JSON of configuration used
    
    -- Performance metrics
    total_orders INTEGER DEFAULT 0,
    filled_orders INTEGER DEFAULT 0,
    total_volume REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    
    -- Error tracking
    error_message TEXT,
    
    created_at REAL NOT NULL DEFAULT (unixepoch())
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_session_id ON trading_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON trading_sessions(started_at);

-- ============================================================================
-- VIEWS
-- Convenient views for common queries
-- ============================================================================

-- Active orders view
CREATE VIEW IF NOT EXISTS v_active_orders AS
SELECT 
    o.*,
    q.spread_bps as quote_spread_bps,
    (o.quantity - o.filled_quantity) as remaining_qty
FROM orders o
LEFT JOIN quotes q ON o.quote_id = q.quote_id
WHERE o.status IN ('pending', 'submitted', 'partially_filled');

-- Recent quotes with orders
CREATE VIEW IF NOT EXISTS v_quotes_with_orders AS
SELECT 
    q.*,
    COUNT(o.id) as order_count,
    SUM(CASE WHEN o.status = 'filled' THEN 1 ELSE 0 END) as filled_count
FROM quotes q
LEFT JOIN orders o ON q.quote_id = o.quote_id
GROUP BY q.quote_id;

-- Daily trading summary
CREATE VIEW IF NOT EXISTS v_daily_summary AS
SELECT 
    date(created_at, 'unixepoch') as trading_date,
    symbol,
    COUNT(*) as total_orders,
    SUM(CASE WHEN status = 'filled' THEN 1 ELSE 0 END) as filled_orders,
    SUM(CASE WHEN status = 'filled' THEN quantity ELSE 0 END) as total_volume,
    AVG(CASE WHEN status = 'filled' THEN price ELSE NULL END) as avg_price
FROM orders
GROUP BY date(created_at, 'unixepoch'), symbol;

-- ============================================================================
-- TRIGGERS
-- Automatically maintain data consistency
-- ============================================================================

-- Update order remaining quantity when filled_quantity changes
CREATE TRIGGER IF NOT EXISTS tr_update_remaining_quantity
AFTER UPDATE OF filled_quantity ON orders
FOR EACH ROW
BEGIN
    UPDATE orders 
    SET remaining_quantity = quantity - filled_quantity,
        last_updated = unixepoch()
    WHERE id = NEW.id;
END;

-- Update order status when fully filled
CREATE TRIGGER IF NOT EXISTS tr_update_order_status_filled
AFTER UPDATE OF filled_quantity ON orders
FOR EACH ROW
WHEN NEW.filled_quantity >= NEW.quantity AND NEW.status != 'filled'
BEGIN
    UPDATE orders 
    SET status = 'filled',
        last_updated = unixepoch()
    WHERE id = NEW.id;
END;

-- Update position when fill occurs
CREATE TRIGGER IF NOT EXISTS tr_update_position_on_fill
AFTER INSERT ON fills
FOR EACH ROW
BEGIN
    INSERT OR REPLACE INTO positions (
        symbol, 
        quantity, 
        avg_entry_price,
        last_updated
    )
    VALUES (
        NEW.symbol,
        COALESCE((SELECT quantity FROM positions WHERE symbol = NEW.symbol), 0) + 
        CASE WHEN NEW.side IN ('buy', 'bid') THEN NEW.quantity ELSE -NEW.quantity END,
        -- Weighted average price calculation would go here
        NEW.price,
        unixepoch()
    );
END;
