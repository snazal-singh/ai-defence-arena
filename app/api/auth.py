import logging

from fastapi import APIRouter

from app.schemas.common import MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=MessageResponse)
def healthcheck():
    return {"message": "app is up and running"}
