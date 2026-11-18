from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Uptime monitors often probe with HEAD; kept out of the schema so the
# generated client has a single operation for /health.
@router.head("/health", include_in_schema=False)
def health_head() -> None:
    return None
