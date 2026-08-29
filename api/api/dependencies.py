"""Shared dependencies for the application routers.

Identity here is deliberately minimal. There is no login, no session, and no
password: a client presents an opaque UUID in a header and owns whatever it
created under that UUID.

A header rather than a cookie because the frontend and API are on different
origins, and cookies across origins mean credentialed CORS, which in turn means
giving up the wildcard. A header is trivially spoofable -- anyone can send
someone else's UUID -- and that is acceptable because nothing stored here is
private or valuable. It is stated as an assumption in the README rather than
left for a reviewer to discover.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, Response
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.models import AppUser

SessionDep = Annotated[AsyncSession, Depends(get_session)]

USER_HEADER_EXAMPLE = "11111111-1111-1111-1111-111111111111"

# Declared as an explicit Header parameter on every user-scoped route rather
# than read off the raw request. Reading it from the request would leave it out
# of the OpenAPI schema, so Swagger's "Try it out" would not send it and every
# call in the demo would fail validation.
UserIdHeader = Annotated[
    uuid.UUID | None,
    Header(
        alias="X-User-Id",
        description=(
            "Opaque client identifier. Omit it and the API mints one, returning it "
            "in the X-User-Id response header for the client to store and reuse."
        ),
        # `examples`, not the deprecated `example`: this is what puts a working
        # value in Swagger's Try-it-out box instead of an empty field.
        examples=[USER_HEADER_EXAMPLE],
    ),
]


async def get_current_user(
    response: Response,
    session: SessionDep,
    x_user_id: UserIdHeader = None,
) -> AppUser:
    """Resolve the caller, creating the account on first sight.

    A missing header mints a new identity rather than failing, so a first-time
    visitor can start building a team immediately. The resolved id is echoed in
    the response header so the client always learns which identity it is using.
    """
    user_id = x_user_id or uuid.uuid4()

    # ON CONFLICT DO NOTHING rather than a read-then-write: two concurrent first
    # requests from the same client would otherwise race on the insert.
    await session.execute(
        insert(AppUser).values(id=user_id).on_conflict_do_nothing(index_elements=["id"])
    )
    await session.commit()

    user = await session.get(AppUser, user_id)
    if user is None:  # pragma: no cover - only reachable if the row vanished
        user = AppUser(id=user_id)
        session.add(user)
        await session.commit()

    # Exposed to the browser via expose_headers in the CORS middleware; without
    # that, cross-origin JavaScript cannot read it and a minted id is lost.
    response.headers["X-User-Id"] = str(user_id)
    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]
