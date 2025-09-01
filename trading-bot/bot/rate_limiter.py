"""
Rate limiting utilities for DeltaDeFi order submission
"""

import asyncio
import time
from collections import deque

import structlog

logger = structlog.get_logger()


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for DeltaDeFi's 5 orders/second limit
    """

    def __init__(self, max_tokens: int = 5, refill_rate: float = 5.0):
        """
        Initialize rate limiter

        Args:
            max_tokens: Maximum tokens in bucket (5 for DeltaDeFi)
            refill_rate: Tokens added per second (5.0 for DeltaDeFi)
        """
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.tokens = max_tokens
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens for order submission

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens acquired, False if rate limited
        """
        async with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                logger.debug(
                    "Rate limit token acquired",
                    tokens_used=tokens,
                    tokens_remaining=self.tokens,
                )
                return True

            logger.warning(
                "Rate limit exceeded",
                tokens_requested=tokens,
                tokens_available=self.tokens,
                wait_time=self._time_until_available(tokens),
            )
            return False

    async def wait_for_token(self, tokens: int = 1) -> None:
        """
        Wait until enough tokens are available

        Args:
            tokens: Number of tokens needed
        """
        while not await self.acquire(tokens):
            wait_time = self._time_until_available(tokens)
            logger.info(
                "Waiting for rate limit tokens",
                wait_time=wait_time,
                tokens_needed=tokens,
            )
            await asyncio.sleep(min(wait_time, 0.1))  # Check every 100ms max

    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill

        if elapsed > 0:
            tokens_to_add = elapsed * self.refill_rate
            self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
            self.last_refill = now

    def _time_until_available(self, tokens: int) -> float:
        """Calculate time until enough tokens are available"""
        if self.tokens >= tokens:
            return 0.0

        tokens_needed = tokens - self.tokens
        return tokens_needed / self.refill_rate

    def get_status(self) -> dict:
        """Get current rate limiter status"""
        self._refill()
        return {
            "tokens_available": self.tokens,
            "max_tokens": self.max_tokens,
            "refill_rate": self.refill_rate,
            "utilization": (self.max_tokens - self.tokens) / self.max_tokens,
        }


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter as alternative implementation
    """

    def __init__(self, max_requests: int = 5, window_size: float = 1.0):
        """
        Initialize sliding window rate limiter

        Args:
            max_requests: Maximum requests per window (5 for DeltaDeFi)
            window_size: Window size in seconds (1.0 for per-second limit)
        """
        self.max_requests = max_requests
        self.window_size = window_size
        self.requests = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """
        Try to acquire permission for one request

        Returns:
            True if request allowed, False if rate limited
        """
        async with self._lock:
            now = time.time()

            # Remove requests outside the current window
            while self.requests and self.requests[0] <= now - self.window_size:
                self.requests.popleft()

            # Check if we can make another request
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                logger.debug(
                    "Sliding window request acquired",
                    requests_in_window=len(self.requests),
                    max_requests=self.max_requests,
                )
                return True

            logger.warning(
                "Sliding window rate limit exceeded",
                requests_in_window=len(self.requests),
                max_requests=self.max_requests,
                oldest_request_age=now - self.requests[0],
            )
            return False

    async def wait_for_slot(self) -> None:
        """Wait until a request slot is available"""
        while not await self.acquire():
            # Wait until the oldest request falls outside the window
            if self.requests:
                wait_time = self.window_size - (time.time() - self.requests[0])
                wait_time = max(0.01, wait_time)  # At least 10ms
                logger.info("Waiting for sliding window slot", wait_time=wait_time)
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(0.01)

    def get_status(self) -> dict:
        """Get current sliding window status"""
        now = time.time()
        # Clean up old requests
        while self.requests and self.requests[0] <= now - self.window_size:
            self.requests.popleft()

        return {
            "requests_in_window": len(self.requests),
            "max_requests": self.max_requests,
            "window_size": self.window_size,
            "utilization": len(self.requests) / self.max_requests,
        }
