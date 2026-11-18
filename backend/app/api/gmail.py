from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Db, Now, RevokerDep
from app.providers.google.revoke import RevokerNotConfigured
from app.services import account

router = APIRouter(prefix="/gmail", tags=["gmail"])


class DisconnectOut(BaseModel):
    revoked_at_google: bool | None


@router.post("/disconnect", response_model=DisconnectOut)
def disconnect(user: CurrentUser, db: Db, now: Now, revoker: RevokerDep) -> DisconnectOut:
    try:
        result = account.disconnect_gmail(db, user.id, revoker, now)
    except account.SyncInProgress:
        db.rollback()
        raise HTTPException(status_code=409, detail="sync_in_progress") from None
    except RevokerNotConfigured:
        db.rollback()
        raise HTTPException(status_code=503, detail="revocation_unavailable") from None
    db.commit()
    return DisconnectOut(revoked_at_google=result.revoked_at_google)
