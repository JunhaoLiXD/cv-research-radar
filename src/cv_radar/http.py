"""Shared resilient HTTP client for all non-LLM upstream APIs."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ResilientHttpClient:
    """Synchronous client with explicit timeout, retries, and polite pacing."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        min_interval_seconds: float = 1.0,
        user_agent: str = "cv-research-radar/0.1 (+https://github.com/)",
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self._sleep = sleeper
        self._clock = clock
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json, application/atom+xml, application/rss+xml, */*"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ResilientHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._pace()
            try:
                response = self._client.get(url, timeout=self.timeout, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = isinstance(exc, httpx.RequestError)
                if isinstance(exc, httpx.HTTPStatusError):
                    retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not retryable or attempt >= self.max_retries:
                    logger.error("HTTP GET failed after %s attempt(s): %s (%s)", attempt + 1, url, exc)
                    raise
                delay = self.backoff_seconds * (2**attempt)
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            pass
                logger.warning("HTTP GET retry %s/%s for %s: %s", attempt + 1, self.max_retries, url, exc)
                self._sleep(delay)
        raise RuntimeError("unreachable retry state") from last_error

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()
