# DeltaDeFi Trading Bot Demo

## Development Setup

1. **Create and activate a virtual environment:**

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**

   ```sh
   pip install -e .
   ```

## Structure

```sh
trading-bot/
  pyproject.toml
  README.md
  Makefile
  docs/
    01-architecture.md
    02-user-guide.md
    03-deployment.md
  bot/
    __init__.py
    main.py                 # asyncio entrypoint: wire tasks, graceful shutdown
    config.py               # Pydantic settings (env + YAML)
    logging.py              # structured logs
    binance_ws.py           # listen: adausdt@bookTicker → yield BBO(bid,ask,ts)
    quote.py                # ±bps math, (optional) don't-cross clamp
    signer.py               # sign(tx_hex) -> signed_tx (pluggable)
    deltadefi.py            # REST build/submit + Account WS (source of truth)
    oms.py                  # tiny FSM per side; uses repos below (one file)
    db/
      __init__.py
      sqlite.py             # connect(path)->conn, WAL+PRAGMAs, migrations runner
      schema.sql            # DDL (quotes, orders, fills, outbox)
      repo.py               # small repos: QuotesRepo, OrdersRepo, FillsRepo, OutboxRepo
      outbox_worker.py      # reads outbox, calls DeltaDeFi build/submit/cancel* safely

  tests/
    test_quote.py
    test_repos.py

```
