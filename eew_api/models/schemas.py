from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Epicenter(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    depth_km: float = Field(..., ge=0, le=700)


class EstimatedWaveArrival(BaseModel):
    onda_p_eta_seconds: float
    onda_s_eta_seconds: float
    useful_alert_window_seconds: float


class TargetClientAlert(BaseModel):
    client_id: str
    distance_to_epicenter_km: float
    estimated_wave_arrival: EstimatedWaveArrival
    pga_estimated_g: float | None = None
    action_triggered: str


class EEWAlertPayload(BaseModel):
    event_id: str
    timestamp_utc: datetime
    epicenter: Epicenter
    magnitude_mw: float
    target_client: TargetClientAlert


class EEWTriggerRequest(BaseModel):
    event_id: str
    timestamp_utc: datetime
    epicenter: Epicenter
    magnitude_mw: float = Field(..., ge=0, le=10)
    source: Literal["usgs", "emsc", "manual", "webhook"] = "manual"
    client_ids: list[str] | None = None

    @field_validator("timestamp_utc", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class PredictiveAnalyticsResponse(BaseModel):
    risk_index: float = Field(..., ge=0, le=1)
    thermal_anomaly_score: float
    gas_anomaly_score: float
    seismic_activity_score: float
    region: str
    window_days: int = 7
    sources_used: list[str]
    generated_at: datetime


class NazcaLocation(BaseModel):
    lat: float
    lon: float


class NazcaEstadoOperativo(BaseModel):
    estado: str
    color: str
    indice_actual_pct: float
    descripcion: str


class NazcaNivelVigilancia(BaseModel):
    nivel: str
    color: str
    ventana: str
    sirena: bool
    similitud_historica_m7_pct: float
    patron_m7_referencia: str
    descripcion: str


class NazcaMetricas(BaseModel):
    sismos_chile_14d: int
    sismos_locales_14d: int
    b_value: float
    kp_noaa: int
    insar_pct: float
    conductividad_ms_m: float
    shoa_cm: float
    presion_hpa: float
    termico: float
    origen: str


class NazcaTrazabilidad(BaseModel):
    fuentes: list[str]
    radio_local_km: int
    log_modelo: str
    generado_utc: datetime
    aviso: str


class NazcaMonitorResponse(BaseModel):
    estacion: str
    ubicacion: NazcaLocation
    estado_operativo: NazcaEstadoOperativo
    nivel_vigilancia: NazcaNivelVigilancia
    metricas: NazcaMetricas
    trazabilidad: NazcaTrazabilidad


class ClientLocationOut(BaseModel):
    id: int
    client_id: str
    name: str
    latitude: float
    longitude: float
    radius_km: float
    webhook_url: str | None = None


class ClientSubscriptionOut(BaseModel):
    client_id: str
    company_name: str
    auth_tier: str
    locations: list[ClientLocationOut]


class ClientCreateRequest(BaseModel):
    company_name: str
    auth_tier: Literal["basic", "institutional", "critical"] = "institutional"
    api_key: str | None = None


class LocationCreateRequest(BaseModel):
    name: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(50.0, gt=0, le=500)
    webhook_url: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    redis: str
