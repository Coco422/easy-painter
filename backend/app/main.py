from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from sqlalchemy.orm import Session

from app.api import admin_router, announcement_router, auth_router, inspiration_router, reference_router, router, user_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.init_db import init_db
from app.db.session import get_db
from app.services.health import collect_core_health
from app.services.redis_client import get_redis


configure_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(user_router, prefix=settings.api_v1_prefix)
app.include_router(admin_router, prefix=settings.api_v1_prefix)
app.include_router(announcement_router, prefix=settings.api_v1_prefix)
app.include_router(inspiration_router, prefix=settings.api_v1_prefix)
app.include_router(reference_router, prefix=settings.api_v1_prefix)


@app.get("/api/healthz")
def legacy_healthz(
    response: Response,
    db: Session = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    components = collect_core_health(db=db, redis_client=redis_client, settings=settings)
    if any(component.get("status") != "ok" for component in components.values()):
        response.status_code = 503
        return {"status": "degraded", "components": components}
    return {"status": "ok", "components": components}
