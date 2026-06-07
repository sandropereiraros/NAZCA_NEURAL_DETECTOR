import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from eew_api.core.physics import calculate_wave_arrival, estimate_pga_g, recommended_action
from eew_api.db.models import AlertLog, Client, ClientLocation, SeismicEvent, make_point
from eew_api.models.schemas import (
    EEWAlertPayload,
    EEWTriggerRequest,
    EstimatedWaveArrival,
    TargetClientAlert,
)
from eew_api.services.redis_client import enqueue_alert

logger = logging.getLogger(__name__)


async def _get_lat_lon_from_location(loc: ClientLocation) -> tuple[float, float]:
    wkt = str(loc.coordinates)
    if "POINT" in wkt:
        coords = wkt.replace("POINT(", "").replace(")", "").strip().split()
        lon, lat = float(coords[0]), float(coords[1])
        return lat, lon
    return -33.0, -71.5


async def process_eew_trigger(db, request: EEWTriggerRequest) -> list[EEWAlertPayload]:
    epic = request.epicenter
    alerts: list[EEWAlertPayload] = []

    result = await db.execute(select(SeismicEvent).where(SeismicEvent.event_id == request.event_id))
    event_row = result.scalar_one_or_none()
    if not event_row:
        event_row = SeismicEvent(
            event_id=request.event_id,
            timestamp_utc=request.timestamp_utc,
            epicenter=make_point(epic.latitude, epic.longitude),
            magnitude=request.magnitude_mw,
            depth_km=epic.depth_km,
            source=request.source,
        )
        db.add(event_row)
        await db.flush()

    query = select(Client).options(selectinload(Client.locations))
    if request.client_ids:
        query = query.where(Client.client_id.in_(request.client_ids))
    clients = (await db.execute(query)).scalars().all()

    for client in clients:
        for loc in client.locations:
            lat_t, lon_t = await _get_lat_lon_from_location(loc)
            arrival = calculate_wave_arrival(
                epic.latitude, epic.longitude, lat_t, lon_t
            )
            pga = estimate_pga_g(request.magnitude_mw, arrival.distance_km, epic.depth_km)
            action = recommended_action(pga, arrival.useful_alert_window_seconds, request.magnitude_mw)

            payload = EEWAlertPayload(
                event_id=request.event_id,
                timestamp_utc=request.timestamp_utc,
                epicenter=epic,
                magnitude_mw=request.magnitude_mw,
                target_client=TargetClientAlert(
                    client_id=client.client_id,
                    distance_to_epicenter_km=arrival.distance_km,
                    estimated_wave_arrival=EstimatedWaveArrival(
                        onda_p_eta_seconds=arrival.eta_p_seconds,
                        onda_s_eta_seconds=arrival.eta_s_seconds,
                        useful_alert_window_seconds=arrival.useful_alert_window_seconds,
                    ),
                    pga_estimated_g=pga,
                    action_triggered=action,
                ),
            )
            alerts.append(payload)

            log = AlertLog(
                event_id=event_row.id,
                client_id=client.id,
                calculated_eta_s_wave=arrival.eta_s_seconds,
                delivery_status="queued",
                payload_json=payload.model_dump_json(),
            )
            db.add(log)
            await enqueue_alert(payload.model_dump(mode="json"))

            if loc.webhook_url:
                await _dispatch_webhook(loc.webhook_url, payload)

    await db.commit()
    logger.info("EEW trigger %s: %d alertas generadas", request.event_id, len(alerts))
    return alerts


async def _dispatch_webhook(url: str, payload: EEWAlertPayload) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(url, json=json.loads(payload.model_dump_json()))
            res.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Webhook falló %s: %s", url, exc)
