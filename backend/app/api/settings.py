from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, Db
from app.repositories import users

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    digest_enabled: bool


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest_enabled: bool


@router.get("", response_model=SettingsOut)
def get_settings_route(user: CurrentUser) -> SettingsOut:
    return SettingsOut(digest_enabled=user.digest_enabled)


@router.patch("", response_model=SettingsOut)
def patch_settings(body: SettingsPatch, user: CurrentUser, db: Db) -> SettingsOut:
    users.set_digest_enabled(db, user.id, body.digest_enabled)
    db.commit()
    return SettingsOut(digest_enabled=body.digest_enabled)
