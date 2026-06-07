"""
Carga datos demo: cliente industrial con geocerca en Valparaíso.
Ejecutar: python scripts/seed_demo.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from eew_api.core.security import generate_api_key, hash_api_key
from eew_api.db.models import Client, ClientLocation, make_point
from eew_api.db.session import AsyncSessionLocal


async def seed():
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(Client).where(Client.client_id == "industrial_plant_01")
        )
        if existing.scalar_one_or_none():
            print("Demo ya existe (industrial_plant_01).")
            return

        api_key = generate_api_key()
        client = Client(
            company_name="Planta Industrial Demo",
            client_id="industrial_plant_01",
            api_key_hash=hash_api_key(api_key),
            auth_tier="critical",
        )
        db.add(client)
        await db.flush()

        loc = ClientLocation(
            client_id=client.id,
            name="Planta Valparaíso",
            coordinates=make_point(-33.0472, -71.6127),
            radius_km=120.0,
            webhook_url=None,
        )
        db.add(loc)
        await db.commit()

        print("Cliente demo creado:")
        print(f"  client_id: industrial_plant_01")
        print(f"  api_key:   {api_key}")
        print("  Ubicación: Valparaíso (-33.0472, -71.6127)")


if __name__ == "__main__":
    asyncio.run(seed())
