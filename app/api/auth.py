import logging

from fastapi import APIRouter

from app.schemas.common import MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=MessageResponse)
@router.get(
    "/healthcheck",
    response_model=MessageResponse,
    include_in_schema=False,
    description="Legacy alias for /health used by frontend Login client",
)
def healthcheck():
    """Application health and liveness check."""
    return {"message": "app is up and running"}
