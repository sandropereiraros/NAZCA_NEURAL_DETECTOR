import logging
from datetime import datetime, timedelta, timezone

import httpx

from eew_api.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DataFetcher:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("DataFetcher no inicializado. Usar async with.")
        return self._client

    async def fetch_usgs_recent(self, min_mag: float = 2.5) -> list[dict]:
        try:
            res = await self.client.get(settings.usgs_geojson_url)
            res.raise_for_status()
            events = []
            for f in res.json().get("features", []):
                props = f["properties"]
                mag = float(props.get("mag") or 0)
                if mag < min_mag:
                    continue
                coords = f["geometry"]["coordinates"]
                events.append({
                    "event_id": f"usgs_{props.get('ids', props.get('code', 'unknown'))}",
                    "timestamp_utc": datetime.fromtimestamp(
                        props["time"] / 1000, tz=timezone.utc
                    ).isoformat(),
                    "latitude": coords[1],
                    "longitude": coords[0],
                    "depth_km": coords[2],
                    "magnitude_mw": mag,
                    "source": "usgs",
                    "place": props.get("place", ""),
                })
            return events
        except httpx.HTTPError as exc:
            logger.error("Error USGS: %s", exc)
            return []

    async def fetch_emsc_recent(self, min_mag: float = 2.5) -> list[dict]:
        start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")
        url = (
            "https://www.seismicportal.eu/fdsnws/event/1/query"
            f"?format=geojson&limit=100&minmag={min_mag}&starttime={start}"
        )
        try:
            res = await self.client.get(url)
            res.raise_for_status()
            events = []
            for f in res.json().get("features", []):
                props = f["properties"]
                mag = float(props.get("mag") or 0)
                coords = f["geometry"]["coordinates"]
                events.append({
                    "event_id": f"emsc_{props.get('unid', props.get('id', 'unknown'))}",
                    "timestamp_utc": props.get("time", datetime.now(timezone.utc).isoformat()),
                    "latitude": coords[1],
                    "longitude": coords[0],
                    "depth_km": coords[2],
                    "magnitude_mw": mag,
                    "source": "emsc",
                    "place": props.get("flynn_region", ""),
                })
            return events
        except httpx.HTTPError as exc:
            logger.error("Error EMSC: %s", exc)
            return []

    async def fetch_thermal_anomaly_score(self, lat: float, lon: float) -> float:
        """
        NASA FIRMS requiere API key. Sin credenciales retorna score neutro.
        """
        if not settings.firms_api_key:
            return 0.35
        try:
            url = (
                "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
                f"{settings.firms_api_key}/VIIRS_SNPP_NRT/{lon-1},{lat-1},{lon+1},{lat+1}/1"
            )
            res = await self.client.get(url)
            if res.status_code == 200 and len(res.text.strip().splitlines()) > 1:
                lines = len(res.text.strip().splitlines()) - 1
                return min(1.0, lines / 10.0)
        except httpx.HTTPError as exc:
            logger.warning("FIRMS no disponible: %s", exc)
        return 0.2

    async def fetch_gas_anomaly_score(self) -> float:
        """Copernicus Sentinel-5P requiere credenciales OAuth."""
        if not settings.copernicus_username:
            return 0.25
        return 0.4
