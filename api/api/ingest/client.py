"""Rate-limited async HTTP client for PokeAPI.

PokeAPI is free and asks to be treated gently. Three mechanisms cooperate here:
a semaphore caps how many requests are ever in flight, a delay separates
batches so a long seed does not arrive as one continuous burst, and tenacity
retries the failures that are worth retrying with exponential backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm import tqdm

# 429 is rate limiting; the 5xx set is transient server trouble. A 404 is a real
# answer about a real resource and must never be retried.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"


class RetryableStatusError(Exception):
    """A response whose status code justifies another attempt."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"{status_code} from {url}")
        self.status_code = status_code
        self.url = url


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """One URL that could not be retrieved, kept rather than discarded.

    Silently dropping these is the failure mode the seed is built to avoid: a
    run missing a third of its movepools otherwise looks exactly like a good one.
    """

    url: str
    error: str


class RateLimitedClient:
    """An httpx.AsyncClient wrapped in concurrency limits and retries."""

    def __init__(
        self,
        base_url: str = POKEAPI_BASE_URL,
        *,
        concurrency: int = 5,
        batch_size: int = 25,
        batch_delay: float = 0.5,
        timeout: float = 30.0,
        max_attempts: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(concurrency)
        self._batch_size = batch_size
        self._batch_delay = batch_delay
        self._max_attempts = max_attempts
        # `transport` is an injection point for tests: the retry and backoff
        # behaviour must be verifiable without sending anything to pokeapi.co.
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "pokemon-team-builder/0.1 (seed script)"},
            follow_redirects=True,
            transport=transport,
        )

    async def __aenter__(self) -> RateLimitedClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    def url_for(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    async def _get_once(self, url: str) -> dict[str, Any]:
        async with self._semaphore:
            response = await self._client.get(url)

        if response.status_code in RETRYABLE_STATUS:
            # Honour Retry-After when the server sends one. tenacity's backoff
            # does not read headers, so waiting here is what actually makes the
            # next attempt polite rather than merely delayed.
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                # A malformed Retry-After is not worth failing over; the
                # exponential backoff below still applies.
                with contextlib.suppress(ValueError):
                    await asyncio.sleep(min(float(retry_after), 60.0))
            raise RetryableStatusError(response.status_code, url)

        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    async def get_json(self, path: str) -> dict[str, Any]:
        """Fetch one resource, retrying transient failures."""
        url = self.url_for(path)
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type((RetryableStatusError, httpx.TransportError)),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            stop=stop_after_attempt(self._max_attempts),
            reraise=True,
        ):
            with attempt:
                return await self._get_once(url)
        raise RuntimeError(f"retry loop exited without a result for {url}")

    async def get_many(
        self, paths: list[str], *, desc: str
    ) -> tuple[list[dict[str, Any]], list[FetchFailure]]:
        """Fetch many resources, returning successes and failures separately.

        Exceptions are collected rather than raised so that one bad resource
        does not discard a long run's work -- but they are never discarded, and
        the caller is expected to fail the process if the list is non-empty.
        """
        results: list[dict[str, Any]] = []
        failures: list[FetchFailure] = []

        with tqdm(total=len(paths), desc=desc, unit="req") as progress:
            for start in range(0, len(paths), self._batch_size):
                batch = paths[start : start + self._batch_size]
                outcomes = await asyncio.gather(
                    *(self.get_json(path) for path in batch), return_exceptions=True
                )
                for path, outcome in zip(batch, outcomes, strict=True):
                    if isinstance(outcome, BaseException):
                        failures.append(
                            FetchFailure(
                                url=self.url_for(path),
                                error=f"{type(outcome).__name__}: {outcome}",
                            )
                        )
                    else:
                        results.append(outcome)
                progress.update(len(batch))

                if start + self._batch_size < len(paths):
                    await asyncio.sleep(self._batch_delay)

        return results, failures
