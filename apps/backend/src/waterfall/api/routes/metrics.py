from fastapi import APIRouter
from starlette.responses import PlainTextResponse
from waterfall.core.observability import metrics_response

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics() -> PlainTextResponse:
    return metrics_response()
