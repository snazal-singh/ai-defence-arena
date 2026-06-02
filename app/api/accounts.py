import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.schemas.account import LoginRequest, PaymentUpdateRequest
from app.services.account_service import get_account_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Accounts"])

account_service = get_account_service()


@router.post("/login")
def login(body: LoginRequest):
    """Authenticate a user and return a JWT token."""
    response, status_code = account_service.login(body.email, body.password)
    return JSONResponse(content=response, status_code=status_code)


@router.post("/payment")
def update_payment(body: PaymentUpdateRequest):
    """Update a user's subscription plan (30 / 90 / 365-day plans)."""
    response, status_code = account_service.update_payment_plan(body.email, body.paymentPlan)
    return JSONResponse(content=response, status_code=status_code)


@router.get("/payment-status")
def check_payment_status(email: str = Query(..., description="User email address")):
    """Return the user's current subscription status and remaining days."""
    response, status_code = account_service.get_payment_status(email)
    return JSONResponse(content=response, status_code=status_code)
