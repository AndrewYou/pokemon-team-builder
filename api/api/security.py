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

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from api.config import settings

# auto_error=False so this dependency answers both the missing-credential and
# the wrong-credential case. Left on, FastAPI rejects a credential-less request
# first with its own "Not authenticated" body, so the same 401 would have two
# different shapes depending on which layer refused it.
basic_scheme = HTTPBasic(
    auto_error=False,
    description="Defaults to admin / pokemon unless ADMIN_USERNAME and ADMIN_PASSWORD are set.",
)

ADMIN_UNAUTHORIZED_DETAIL = "Invalid or missing admin credentials"


def verify_admin(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_scheme)] = None,
) -> str:
    """Check HTTP Basic credentials against the configured admin user."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ADMIN_UNAUTHORIZED_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )
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
            detail=ADMIN_UNAUTHORIZED_DETAIL,
            # Without this header the browser never shows a login prompt.
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# auto_error=False so a request carrying only the cron secret is not rejected
# before the alternative credential is even considered.
optional_basic_scheme = HTTPBasic(
    auto_error=False,
    description="Either these credentials or an X-Cron-Secret header will do.",
)

CronSecretHeader = Annotated[
    str | None,
    Header(
        alias="X-Cron-Secret",
        description="Shared secret for scheduled callers. An alternative to HTTP Basic.",
    ),
]


def verify_admin_or_cron(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(optional_basic_scheme)] = None,
    x_cron_secret: CronSecretHeader = None,
) -> str:
    """Accept either a human in Swagger or an automated caller.

    One dependency taking either credential, rather than two endpoints or a
    hand-rolled branch inside the handler. A scheduled job cannot type a
    password into a browser prompt, and a reviewer should not need to know a
    secret to press a button.
    """
    # An unset CRON_SECRET disables the header entirely; without that guard an
    # empty configured secret would match an empty supplied one.
    if (
        x_cron_secret is not None
        and settings.cron_secret
        and secrets.compare_digest(
            x_cron_secret.encode("utf-8"), settings.cron_secret.encode("utf-8")
        )
    ):
        return "cron"

    if credentials is not None:
        username_ok = secrets.compare_digest(
            credentials.username.encode("utf-8"), settings.admin_username.encode("utf-8")
        )
        password_ok = secrets.compare_digest(
            credentials.password.encode("utf-8"), settings.admin_password.encode("utf-8")
        )
        if username_ok and password_ok:
            return credentials.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide admin credentials or a valid X-Cron-Secret header",
        headers={"WWW-Authenticate": "Basic"},
    )
