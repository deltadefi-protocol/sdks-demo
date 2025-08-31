# DeltaDeFi Trading Bot Demo

## Structure

```sh
trading-bot/
  bot/
    __init__.py
    config.py                # symbol, bps, sizes, risk caps
    strategy/grid_peg.py     # ±5 bps logic, tick snapping
    venue/base.py            # Exchange interface
    venue/binance.py         # WS bookTicker + REST/WSS orders
    risk/manager.py
    oms/manager.py           # state machine: idle→working→filled/canceled
    storage/sqlite.py        # fills, positions, pnl
    cli.py                   # run backtest, paper, live (binance, deltadefi)
  docs/
    01-architecture.md       # satisfies Milestone 4 “full logic” doc
    02-user-guide.md         # UX: config→run→monitor (Milestone 4)
    03-deployment.md         # Docker, GCP/AWS scripts (Milestone 4)
  deploy/
    docker-compose.yaml
    systemd.service
  tests/
    unit/  integration/
  LICENSE (Apache-2.0)
  README.md
```
