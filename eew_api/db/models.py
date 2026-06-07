from datetime import datetime

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from eew_api.core.config import get_settings

settings = get_settings()
POINT_TYPE = Text if settings.database_url.startswith("sqlite") else Geometry(geometry_type="POINT", srid=4326)


def make_point(lat: float, lon: float) -> str | WKTElement:
    wkt = f"POINT({lon} {lat})"
    if settings.database_url.startswith("sqlite"):
        return wkt
    return WKTElement(wkt, srid=4326)


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_tier: Mapped[str] = mapped_column(String(32), default="institutional")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    locations: Mapped[list["ClientLocation"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    alert_logs: Mapped[list["AlertLog"]] = relationship(back_populates="client")


class ClientLocation(Base):
    __tablename__ = "client_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    coordinates: Mapped[str] = mapped_column(POINT_TYPE)
    radius_km: Mapped[float] = mapped_column(Float, default=50.0)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="locations")


class SeismicEvent(Base):
    __tablename__ = "seismic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    epicenter: Mapped[str] = mapped_column(POINT_TYPE)
    magnitude: Mapped[float] = mapped_column(Float)
    depth_km: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="usgs")

    alert_logs: Mapped[list["AlertLog"]] = relationship(back_populates="event")


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("seismic_events.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    dispatched_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    calculated_eta_s_wave: Mapped[float] = mapped_column(Float)
    delivery_status: Mapped[str] = mapped_column(String(32), default="queued")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped["SeismicEvent"] = relationship(back_populates="alert_logs")
    client: Mapped["Client"] = relationship(back_populates="alert_logs")
