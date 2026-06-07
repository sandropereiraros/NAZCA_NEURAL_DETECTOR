import logging
from datetime import datetime, timezone

from eew_api.models.schemas import PredictiveAnalyticsResponse
from eew_api.services.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)


async def compute_predictive_analytics(
    lat: float = -33.0,
    lon: float = -71.5,
    region: str = "Chile Central",
    window_days: int = 7,
) -> PredictiveAnalyticsResponse:
    sources = []
    async with DataFetcher() as fetcher:
        usgs = await fetcher.fetch_usgs_recent(min_mag=3.0)
        sources.append("USGS")
        emsc = await fetcher.fetch_emsc_recent(min_mag=3.0)
        if emsc:
            sources.append("EMSC")
        thermal = await fetcher.fetch_thermal_anomaly_score(lat, lon)
        sources.append("NASA_FIRMS" if thermal > 0.3 else "NASA_FIRMS_STUB")
        gas = await fetcher.fetch_gas_anomaly_score()
        sources.append("COPERNICUS_S5P_STUB")

    regional = [
        e for e in usgs + emsc
        if abs(e["latitude"] - lat) < 8 and abs(e["longitude"] - lon) < 8
    ]
    seismic_score = min(1.0, len(regional) / 15.0)
    if regional:
        max_mag = max(e["magnitude_mw"] for e in regional)
        seismic_score = min(1.0, seismic_score + max_mag / 20.0)

    risk_index = round(
        0.35 * seismic_score + 0.30 * thermal + 0.20 * gas + 0.15 * min(1.0, len(regional) / 10),
        4,
    )
    risk_index = min(1.0, max(0.0, risk_index))

    return PredictiveAnalyticsResponse(
        risk_index=risk_index,
        thermal_anomaly_score=round(thermal, 4),
        gas_anomaly_score=round(gas, 4),
        seismic_activity_score=round(seismic_score, 4),
        region=region,
        window_days=window_days,
        sources_used=sources,
        generated_at=datetime.now(timezone.utc),
    )
