"""Tests for asyncpg URL normalization -- the part most likely to break a deploy."""

from api.config import Settings, normalize_asyncpg_url


def test_bare_postgres_scheme_gains_asyncpg_driver() -> None:
    url, tls = normalize_asyncpg_url("postgresql://u:p@host:5432/db")
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    assert tls is False


def test_heroku_style_postgres_scheme_is_upgraded() -> None:
    url, _ = normalize_asyncpg_url("postgres://u:p@host/db")
    assert url.startswith("postgresql+asyncpg://")


def test_sslmode_require_is_stripped_and_reported() -> None:
    url, tls = normalize_asyncpg_url("postgresql://u:p@host/db?sslmode=require")
    assert "sslmode" not in url
    assert tls is True


def test_non_tls_sslmode_does_not_request_tls() -> None:
    _, tls = normalize_asyncpg_url("postgresql://u:p@host/db?sslmode=disable")
    assert tls is False


def test_unrelated_query_params_survive() -> None:
    url, _ = normalize_asyncpg_url(
        "postgresql://u:p@host/db?sslmode=require&application_name=api&channel_binding=require"
    )
    assert "application_name=api" in url
    assert "channel_binding" not in url


def test_already_normalized_url_is_unchanged() -> None:
    url, tls = normalize_asyncpg_url("postgresql+asyncpg://u:p@host/db")
    assert url == "postgresql+asyncpg://u:p@host/db"
    assert tls is False


class TestAlembicUrl:
    """Alembic runs synchronously on psycopg while the app runs on asyncpg.

    Settings are constructed explicitly rather than read from the global, so
    these assertions do not depend on whatever .env happens to hold.
    """

    def test_explicit_value_wins(self) -> None:
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@host/db",
            alembic_database_url="postgresql+psycopg://other/db",
        )
        assert settings.alembic_url == "postgresql+psycopg://other/db"

    def test_derives_from_database_url_when_unset(self) -> None:
        """Railway configures DATABASE_URL only. Without this fallback the
        migration on container start would target the localhost default and
        the container would never come up."""
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@host/db", alembic_database_url=""
        )
        assert settings.alembic_url == "postgresql+psycopg://u:p@host/db"

    def test_derivation_never_leaves_an_async_driver(self) -> None:
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@host/db", alembic_database_url=""
        )
        assert "asyncpg" not in settings.alembic_url

    def test_derivation_keeps_sslmode(self) -> None:
        """psycopg reads sslmode natively, so it must survive the rewrite --
        unlike the asyncpg URL, where it is stripped."""
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@host/db?sslmode=require",
            alembic_database_url="",
        )
        assert "sslmode=require" in settings.alembic_url

    def test_bare_scheme_is_also_rewritten(self) -> None:
        settings = Settings(database_url="postgresql://u:p@host/db", alembic_database_url="")
        assert settings.alembic_url.startswith("postgresql+psycopg://")

    def test_the_two_urls_use_different_drivers(self) -> None:
        settings = Settings(
            database_url="postgresql+asyncpg://u:p@host/db?sslmode=require",
            alembic_database_url="",
        )
        assert "+asyncpg" in settings.async_database_url
        assert "+psycopg" in settings.alembic_url
        # sslmode is stripped for asyncpg but kept for psycopg.
        assert "sslmode" not in settings.async_database_url
        assert "sslmode" in settings.alembic_url
