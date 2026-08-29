"""Admin authentication for the /admin router.

This is presentation hygiene, not a security boundary. Every byte this API
serves is public Pokemon data, there is no user authentication anywhere else,
and the credentials default to a published value so a reviewer can get in. Its
only real job is to stop a stray click from launching a multi-minute crawl.

/docs, /redoc and /openapi.json are deliberately left open: the API should be
browsable without credentials, and only the admin operations prompt.
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from api.config import settings

basic_scheme = HTTPBasic(
    description="Defaults to admin / pokemon unless ADMIN_USERNAME and ADMIN_PASSWORD are set."
)


def verify_admin(credentials: Annotated[HTTPBasicCredentials, Depends(basic_scheme)]) -> str:
    """Check HTTP Basic credentials against the configured admin user."""
    # Both comparisons run unconditionally: short-circuiting on the username
    # would leak which half was wrong through response timing.
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), settings.admin_username.encode("utf-8")
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), settings.admin_password.encode("utf-8")
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            # Without this header the browser never shows a login prompt.
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
