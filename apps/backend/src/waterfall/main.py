from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from waterfall.api.router import api_router
from waterfall.core.config import get_settings
from waterfall.core.logging import configure_logging
from waterfall.core.observability import request_metrics_middleware
from waterfall.db.schema_revision import assert_database_schema_current
from waterfall.db.session import get_engine


async def _generic_http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Rewrite any raw, untranslated ``HTTPException.detail`` into a generic,
    translatable error code before it reaches the client.

    Untranslated English messages passed to ``HTTPException(detail="...")``
    used to leak straight into the API response and get rendered as-is in
    the UI. This also covers a ``detail`` that is a ``list`` -- e.g.
    ``_PlanningTaskBodyValidationRoute`` (``api/routes/planning_support.py``)
    converts a request-body ``RequestValidationError`` into
    ``HTTPException(400, detail=exc.errors())``, a list of raw Pydantic
    error dicts (``"Field required"``, etc.), the same class of leak as a
    bare string. Endpoints that already raise a structured ``detail`` (a
    dict, e.g. ``{"code": "..."}``) carry a machine-readable error code the
    frontend can translate, so those pass through unchanged.
    """
    raw_detail = cast(object, exc.detail)
    detail = {"code": "GENERIC_ERROR"} if isinstance(raw_detail, str | list) else raw_detail
    return JSONResponse(
        status_code=exc.status_code, content={"detail": detail}, headers=exc.headers
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_log_level)
    if settings.app_env == "test":
        from waterfall.db.base import Base
        from waterfall.models import User

        _ = User.__tablename__
        Base.metadata.create_all(bind=get_engine())
    else:
        assert_database_schema_current(get_engine())
    if settings.app_env == "dev":
        from waterfall.scripts.seed_admin import main as seed_admin

        seed_admin()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    cors_allow_origins = settings.get_cors_allow_origins()
    if cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.middleware("http")(request_metrics_middleware)
    app.exception_handler(HTTPException)(_generic_http_exception_handler)
    app.include_router(api_router)
    return app


app = create_app()
