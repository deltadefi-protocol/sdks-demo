# Deployment

## Local

```sh
make run --anchor-bps 5 --venue-spread-bps 3 --qty 100
```

## Docker

```sh
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install .
COPY . .
ENV BINANCE_WS="wss://stream.binance.com:9443/ws/adausdt@bookTicker"
ENV DDEFI_BASE="https://api-staging.deltadefi.io"
CMD ["python","-m","bot.cli","run","--anchor-bps","5","--venue-spread-bps","3","--qty","100"]
```
