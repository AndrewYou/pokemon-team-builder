"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routers import health

app = FastAPI(title="Pokemon Team Builder API", version="0.1.0")

# allow_credentials is False, so the wildcard default is legal: the browser will
# not attach cookies or Authorization headers to these requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
