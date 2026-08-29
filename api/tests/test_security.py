"""Tests for the admin gate.

Low stakes by design -- the data is public and the credentials are published --
but the gate must actually reject wrong credentials and must prompt a browser.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from api.config import settings
from api.security import ADMIN_UNAUTHORIZED_DETAIL, verify_admin


def _creds(username: str, password: str) -> HTTPBasicCredentials:
    return HTTPBasicCredentials(username=username, password=password)


def test_accepts_the_configured_credentials() -> None:
    assert verify_admin(_creds(settings.admin_username, settings.admin_password)) == (
        settings.admin_username
    )


def test_defaults_are_the_published_ones() -> None:
    """A reviewer has to be able to log in without being told a secret."""
    assert verify_admin(_creds("admin", "pokemon")) == "admin"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "wrong"),
        ("wrong", "pokemon"),
        ("", ""),
        ("admin", "pokemon "),
    ],
)
def test_rejects_bad_credentials(username: str, password: str) -> None:
    with pytest.raises(HTTPException) as exc:
        verify_admin(_creds(username, password))
    assert exc.value.status_code == 401


def test_missing_and_wrong_credentials_give_the_same_body() -> None:
    """One 401 shape either way. Left to FastAPI's own auto_error, a request
    with no credentials would be refused earlier with a different body, so the
    documented example would only ever match one of the two cases."""
    with pytest.raises(HTTPException) as absent:
        verify_admin(None)
    with pytest.raises(HTTPException) as wrong:
        verify_admin(_creds("admin", "nope"))

    assert absent.value.status_code == wrong.value.status_code == 401
    assert absent.value.detail == wrong.value.detail == ADMIN_UNAUTHORIZED_DETAIL


def test_the_documented_example_is_the_string_actually_raised() -> None:
    """The Swagger example is taken from this constant rather than retyped."""
    with pytest.raises(HTTPException) as exc:
        verify_admin(None)
    assert exc.value.detail == ADMIN_UNAUTHORIZED_DETAIL


def test_challenge_header_is_present() -> None:
    """Without WWW-Authenticate the browser never shows a login prompt."""
    with pytest.raises(HTTPException) as exc:
        verify_admin(_creds("admin", "wrong"))
    assert exc.value.headers is not None
    assert exc.value.headers["WWW-Authenticate"] == "Basic"
