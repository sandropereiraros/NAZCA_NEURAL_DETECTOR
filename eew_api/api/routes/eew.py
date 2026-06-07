from fastapi import APIRouter, Depends, status

from eew_api.api.dependencies import verify_api_key_header
from eew_api.db.session import get_db
from eew_api.models.schemas import EEWAlertPayload, EEWTriggerRequest
from eew_api.services.eew_processor import process_eew_trigger

router = APIRouter(prefix="/eew", tags=["Early Earthquake Warning"])


@router.post("/trigger", response_model=list[EEWAlertPayload], status_code=status.HTTP_202_ACCEPTED)
async def trigger_eew(
    request: EEWTriggerRequest,
    db=Depends(get_db),
    _auth=Depends(verify_api_key_header),
) -> list[EEWAlertPayload]:
    return await process_eew_trigger(db, request)
