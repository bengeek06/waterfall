from fastapi import APIRouter

from waterfall.api.routes.auth import router as auth_router
from waterfall.api.routes.health import router as health_router
from waterfall.api.routes.imports import router as imports_router
from waterfall.api.routes.metrics import router as metrics_router
from waterfall.api.routes.project_export import router as project_export_router
from waterfall.api.routes.projects import router as projects_router
from waterfall.api.routes.resources import router as resources_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
api_router.include_router(imports_router)
api_router.include_router(projects_router)
api_router.include_router(project_export_router)
api_router.include_router(resources_router)
api_router.include_router(metrics_router)
