from fastapi import APIRouter
from sqlalchemy import text

from eew_api.core.config import get_settings
from eew_api.models.schemas import HealthResponse
from eew_api.services.redis_client import redis_health

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    db_status = "configured"
    try:
        from eew_api.db.session import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "unavailable"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        version=settings.app_version,
        database=db_status,
        redis=await redis_health(),
    )
