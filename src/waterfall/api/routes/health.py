from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(prefix="/health")


@router.get("")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness() -> dict[str, str]:
    return {"status": "ready", "timestamp": datetime.now(UTC).isoformat()}
