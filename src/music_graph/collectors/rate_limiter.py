"""Token bucket rate limiter with 429 retry support."""

import time

from loguru import logger


class RateLimiter:
    """Token bucket rate limiter.

    Args:
        rate: Tokens added per second.
        burst: Maximum token capacity.
        retry_after_default: Default wait time for 429 responses.
    """

    def __init__(
        self,
        rate: float = 5.0,
        burst: int = 10,
        retry_after_default: float = 5.0,
    ):
        self.rate = rate
        self.burst = burst
        self.retry_after_default = retry_after_default
        self._tokens = float(burst)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        self._refill()
        while self._tokens < 1.0:
            deficit = 1.0 - self._tokens
            wait_time = deficit / self.rate
            logger.debug("Rate limiter waiting {:.2f}s for token", wait_time)
            time.sleep(wait_time)
            self._refill()
        self._tokens -= 1.0

    def handle_retry_after(self, retry_after: float | None = None) -> None:
        """Handle a 429 response by sleeping for the specified duration."""
        wait = retry_after if retry_after is not None else self.retry_after_default
        logger.warning("Rate limited, waiting {:.1f}s", wait)
        time.sleep(wait)
        # Drain tokens to prevent immediate burst after waiting
        self._tokens = 0.0
        self._last_refill = time.monotonic()
