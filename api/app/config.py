"""Application settings, loaded from the environment."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Query params understood by psycopg2/libpq but not by asyncpg. Managed Postgres
# providers (Neon, Railway) append these to the URL they hand you; asyncpg raises
# TypeError on unexpected connect kwargs, so they are stripped and translated.
_LIBPQ_ONLY_PARAMS = frozenset({"sslmode", "channel_binding", "target_session_attrs"})

_SSLMODE_REQUIRING_TLS = frozenset({"require", "verify-ca", "verify-full"})


def normalize_database_url(url: str) -> tuple[str, bool]:
    """Coerce a provider-issued Postgres URL into one asyncpg can consume.

    Returns the rewritten URL and whether TLS should be requested. Providers hand
    out `postgresql://...?sslmode=require`; SQLAlchemy needs the `+asyncpg` driver
    marker and asyncpg needs `sslmode` expressed as a connect arg instead.
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
        description="Postgres connection string.",
    )
    # Wildcard is legal here only because allow_credentials is False: no cookies
    # or Authorization headers cross this boundary, so there is nothing to protect.
    cors_origins: str = Field(default="*", description="Comma-separated allowed origins.")

    @property
    def async_database_url(self) -> str:
        return normalize_database_url(self.database_url)[0]

    @property
    def database_requires_tls(self) -> bool:
        return normalize_database_url(self.database_url)[1]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
