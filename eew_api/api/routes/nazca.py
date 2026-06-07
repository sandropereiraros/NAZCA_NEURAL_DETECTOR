from fastapi import APIRouter, Depends, HTTPException, Query, status

from eew_api.api.dependencies import verify_api_key_header
from eew_api.models.schemas import NazcaMonitorResponse
from eew_api.services.nazca_monitor import calcular_estado_nazca, listar_estaciones

router = APIRouter(prefix="/nazca", tags=["NAZCA Monitor"])


@router.get("/stations")
async def get_nazca_stations(_auth=Depends(verify_api_key_header)) -> dict:
    return {"stations": listar_estaciones()}


@router.get("/monitor", response_model=NazcaMonitorResponse)
async def get_nazca_monitor(
    estacion: str = Query("Valparaíso / San Antonio (85574)"),
    _auth=Depends(verify_api_key_header),
) -> NazcaMonitorResponse:
    try:
        estado = await calcular_estado_nazca(estacion)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return NazcaMonitorResponse(**estado)
