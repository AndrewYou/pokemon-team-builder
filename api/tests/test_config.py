"""Tests for provider-URL normalization -- the part most likely to break a deploy."""

from app.config import normalize_database_url


def test_bare_postgres_scheme_gains_asyncpg_driver() -> None:
    url, tls = normalize_database_url("postgresql://u:p@host:5432/db")
    assert url == "postgresql+asyncpg://u:p@host:5432/db"
    assert tls is False


def test_heroku_style_postgres_scheme_is_upgraded() -> None:
    url, _ = normalize_database_url("postgres://u:p@host/db")
    assert url.startswith("postgresql+asyncpg://")


def test_sslmode_require_is_stripped_and_reported() -> None:
    url, tls = normalize_database_url("postgresql://u:p@host/db?sslmode=require")
    assert "sslmode" not in url
    assert tls is True


def test_non_tls_sslmode_does_not_request_tls() -> None:
    _, tls = normalize_database_url("postgresql://u:p@host/db?sslmode=disable")
    assert tls is False


def test_unrelated_query_params_survive() -> None:
    url, _ = normalize_database_url(
        "postgresql://u:p@host/db?sslmode=require&application_name=api&channel_binding=require"
    )
    assert "application_name=api" in url
    assert "channel_binding" not in url


def test_already_normalized_url_is_unchanged() -> None:
    url, tls = normalize_database_url("postgresql+asyncpg://u:p@host/db")
    assert url == "postgresql+asyncpg://u:p@host/db"
    assert tls is False
