from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NAZCA EEW API"
    app_version: str = "1.0.0"
    debug: bool = False
    api_master_key: str = "dev-master-key-change-me"

    database_url: str = "postgresql+asyncpg://eew:eew@localhost:5432/eew_db"
    database_ssl: bool = True
    redis_url: str = "redis://localhost:6379/0"
    redis_ssl: bool = False

    usgs_geojson_url: str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    emsc_geojson_url: str = "https://www.seismicportal.eu/fdsnws/event/1/query?format=geojson&limit=50&orderby=time"
    firms_api_key: str = ""
    copernicus_username: str = ""
    copernicus_password: str = ""

    cache_ttl_predictive_sec: int = 600
    eew_queue_name: str = "eew:alerts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
