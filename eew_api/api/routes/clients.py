import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from eew_api.api.dependencies import verify_api_key_header
from eew_api.core.security import generate_api_key, hash_api_key
from eew_api.db.models import Client, ClientLocation, make_point
from eew_api.db.session import get_db
from eew_api.models.schemas import (
    ClientCreateRequest,
    ClientLocationOut,
    ClientSubscriptionOut,
    LocationCreateRequest,
)

router = APIRouter(prefix="/clients", tags=["Client Subscriptions"])


@router.get("/subscriptions", response_model=list[ClientSubscriptionOut])
async def list_subscriptions(
    db=Depends(get_db),
    _auth=Depends(verify_api_key_header),
) -> list[ClientSubscriptionOut]:
    result = await db.execute(
        select(Client).options(selectinload(Client.locations))
    )
    clients = result.scalars().all()
    out = []
    for c in clients:
        locations = []
        for loc in c.locations:
            wkt = str(loc.coordinates)
            lon, lat = -71.6, -33.0
            if "POINT" in wkt:
                parts = wkt.replace("POINT(", "").replace(")", "").split()
                lon, lat = float(parts[0]), float(parts[1])
            locations.append(ClientLocationOut(
                id=loc.id,
                client_id=c.client_id,
                name=loc.name,
                latitude=lat,
                longitude=lon,
                radius_km=loc.radius_km,
                webhook_url=loc.webhook_url,
            ))
        out.append(ClientSubscriptionOut(
            client_id=c.client_id,
            company_name=c.company_name,
            auth_tier=c.auth_tier,
            locations=locations,
        ))
    return out


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_client(
    body: ClientCreateRequest,
    db=Depends(get_db),
    _auth=Depends(verify_api_key_header),
):
    api_key = body.api_key or generate_api_key()
    client = Client(
        company_name=body.company_name,
        client_id=f"client_{uuid.uuid4().hex[:12]}",
        api_key_hash=hash_api_key(api_key),
        auth_tier=body.auth_tier,
    )
    db.add(client)
    await db.commit()
    return {
        "client_id": client.client_id,
        "api_key": api_key,
        "message": "Guarde la API key, no se mostrará de nuevo.",
    }


@router.post("/{client_id}/locations", status_code=status.HTTP_201_CREATED)
async def add_location(
    client_id: str,
    body: LocationCreateRequest,
    db=Depends(get_db),
    _auth=Depends(verify_api_key_header),
):
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    loc = ClientLocation(
        client_id=client.id,
        name=body.name,
        coordinates=make_point(body.latitude, body.longitude),
        radius_km=body.radius_km,
        webhook_url=body.webhook_url,
    )
    db.add(loc)
    await db.commit()
    return {"location_id": loc.id, "name": loc.name}
