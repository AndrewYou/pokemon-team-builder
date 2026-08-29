"""Application settings, loaded from the environment.

Two database URLs, deliberately. The app runs on asyncpg; Alembic runs
synchronously on psycopg. Trying to serve both from one URL is the source of
three separate and confusing failures, so they are kept apart:

  DATABASE_URL         postgresql+asyncpg://...   the FastAPI app
  ALEMBIC_DATABASE_URL postgresql+psycopg://...   migrations

Without the `+asyncpg` marker SQLAlchemy falls back to psycopg2 and dies on
import; asyncpg does not understand libpq's `?sslmode=`, so that parameter is
stripped here and re-expressed as a connect arg in db.py. psycopg is libpq-based
and reads `sslmode` natively, so the Alembic URL is passed through untouched.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Understood by libpq (psycopg) but rejected by asyncpg, which raises TypeError
# on unexpected connect kwargs. Managed providers append these to the URL they
# hand you, so they are stripped from the async URL rather than trusted.
_LIBPQ_ONLY_PARAMS = frozenset({"sslmode", "channel_binding", "target_session_attrs"})

_SSLMODE_REQUIRING_TLS = frozenset({"require", "verify-ca", "verify-full"})


def normalize_asyncpg_url(url: str) -> tuple[str, bool]:
    """Make a Postgres URL safe for asyncpg.

    Returns the rewritten URL and whether TLS should be requested. A bare
    `postgresql://` scheme is upgraded to `postgresql+asyncpg://` so a
    provider-issued URL pasted straight into the environment still works.
    """
    parts = urlsplit(url)

    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    kept: list[tuple[str, str]] = []
    require_tls = False
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in _LIBPQ_ONLY_PARAMS:
            if key == "sslmode" and value in _SSLMODE_REQUIRING_TLS:
                require_tls = True
            continue
        kept.append((key, value))

    rewritten = urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    return rewritten, require_tls


class Settings(BaseSettings):
    """Runtime configuration. Every value is overridable by an env var."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/pokemon",
        description="Async connection string used by the application.",
    )
    alembic_database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/pokemon",
        description="Sync connection string used by Alembic migrations.",
    )
    # The wildcard is legal only because allow_credentials is False: no cookies
    # or Authorization headers cross this boundary, so there is nothing to protect.
    cors_origins: str = Field(default="*", description="Comma-separated allowed origins.")

    @property
    def async_database_url(self) -> str:
        return normalize_asyncpg_url(self.database_url)[0]

    @property
    def database_requires_tls(self) -> bool:
        return normalize_asyncpg_url(self.database_url)[1]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
