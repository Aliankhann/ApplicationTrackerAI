from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.deps import (
    ClassifierDep,
    ClientFactoryDep,
    Clock,
    Config,
    Db,
    EmailDep,
    require_cron_secret,
)
from app.jobs.tick import run_tick

router = APIRouter(prefix="/internal/cron", include_in_schema=False)


@router.get("/tick", dependencies=[Depends(require_cron_secret)])
def tick(
    db: Db,
    settings: Config,
    clock: Clock,
    client_factory: ClientFactoryDep,
    classifier: ClassifierDep,
    sender: EmailDep,
) -> dict[str, int | bool]:
    """The daily scheduled job (Vercel Cron). Returns counts only."""
    return asdict(run_tick(db, settings, clock, client_factory, classifier, sender))
