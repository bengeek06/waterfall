from contextlib import asynccontextmanager

from fastapi import FastAPI

from waterfall.api.router import api_router
from waterfall.core.config import get_settings
from waterfall.core.logging import configure_logging
from waterfall.core.observability import request_metrics_middleware
from waterfall.db.base import Base
from waterfall.db.session import get_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_log_level)
    if settings.app_env in {"dev", "test"}:
        from waterfall.models import User

        _ = User.__tablename__
        Base.metadata.create_all(bind=get_engine())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.middleware("http")(request_metrics_middleware)
    app.include_router(api_router)
    return app


app = create_app()
