"""Module-level singleton holding the derived cache.

WORKER CAVEAT: this lives in process memory. Under multiple uvicorn workers
each process holds its own copy and invalidate() only affects the one that
served the request, so a rebuild would silently leave the other workers stale.
The deployment runs a single worker. Scaling out would mean checking a version
stamp in Postgres on a cheap interval instead. See the README.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from api.derived.cache import DerivedCache, build_cache

__all__ = [
    "CACHE_UNAVAILABLE_DETAIL",
    "DerivedCache",
    "DerivedCacheUnavailable",
    "ensure_built",
    "get_cache",
    "invalidate",
    "peek",
    "rebuild",
]

logger = logging.getLogger(__name__)

_cache: DerivedCache | None = None
# Serialises concurrent rebuilds so two requests cannot both crawl the database.
_lock = asyncio.Lock()


# Exported so the routers can document the exact string they will return,
# rather than a paraphrase that drifts from it.
CACHE_UNAVAILABLE_DETAIL = (
    "Derived cache is not built. Seed the database (POST /admin/seed), "
    "then rebuild with POST /admin/cache/rebuild."
)


class DerivedCacheUnavailable(RuntimeError):
    """The cache has not been built, usually because the tables are empty."""


def get_cache() -> DerivedCache:
    """Return the current cache, or explain why there isn't one."""
    if _cache is None:
        raise DerivedCacheUnavailable(CACHE_UNAVAILABLE_DETAIL)
    return _cache


def peek() -> DerivedCache | None:
    """The cache if built, without raising. For status reporting."""
    return _cache


def invalidate() -> None:
    """Drop the cache. The sync job calls this after changing reference data."""
    global _cache
    _cache = None
    logger.info("Derived cache invalidated")


async def rebuild(session: AsyncSession) -> DerivedCache:
    """Rebuild and install the cache."""
    global _cache
    async with _lock:
        cache = await build_cache(session)
        _cache = cache
    logger.info("Derived cache built: %d pokemon in %.1f ms", cache.pokemon_count, cache.build_ms)
    return cache


async def ensure_built(session: AsyncSession) -> DerivedCache | None:
    """Build at startup, tolerating an empty or unreachable database.

    A fresh deployment has no data yet. Refusing to start would make the API
    unbrowsable exactly when someone is trying to seed it, so a failure here is
    logged and the cache is left unbuilt.
    """
    try:
        return await rebuild(session)
    except Exception:
        logger.exception("Derived cache could not be built at startup")
        return None
