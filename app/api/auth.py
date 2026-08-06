import logging

from fastapi import APIRouter

from app.schemas.common import MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=MessageResponse)
def healthcheck():
    return {"message": "app is up and running"}


# Alias for /health -- qdoc-app's Login.js calls /healthcheck before allowing
# login (a pre-existing route-naming mismatch between that frontend and this
# backend); kept as a permanent alias rather than requiring every consumer
# of this API to agree on one name.
@router.get("/healthcheck", response_model=MessageResponse)
def healthcheck_alias():
    return {"message": "app is up and running"}
