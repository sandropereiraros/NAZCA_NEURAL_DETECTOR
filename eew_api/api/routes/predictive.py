from fastapi import APIRouter, Depends, Query

from eew_api.api.dependencies import verify_api_key_header
from eew_api.models.schemas import PredictiveAnalyticsResponse
from eew_api.services.predictive import compute_predictive_analytics

router = APIRouter(prefix="/predictive", tags=["Predictive Analytics"])


@router.get("/analytics", response_model=PredictiveAnalyticsResponse)
async def get_predictive_analytics(
    lat: float = Query(-33.0472, ge=-90, le=90),
    lon: float = Query(-71.6127, ge=-180, le=180),
    region: str = Query("Chile Central"),
    window_days: int = Query(7, ge=1, le=30),
    _auth=Depends(verify_api_key_header),
) -> PredictiveAnalyticsResponse:
    return await compute_predictive_analytics(lat=lat, lon=lon, region=region, window_days=window_days)
