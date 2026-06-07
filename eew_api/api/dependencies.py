from fastapi import Header, HTTPException, status
from sqlalchemy import select

from eew_api.core.config import get_settings
from eew_api.core.security import verify_api_key
from eew_api.db.models import Client
from eew_api.db.session import AsyncSessionLocal

settings = get_settings()


async def verify_api_key_header(x_api_key: str = Header(..., alias="X-API-Key")) -> Client | None:
    if x_api_key == settings.api_master_key:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Client))
        clients = result.scalars().all()
        for client in clients:
            if verify_api_key(x_api_key, client.api_key_hash):
                return client

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API Key inválida o no autorizada",
    )
