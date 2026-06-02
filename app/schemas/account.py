from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class PaymentUpdateRequest(BaseModel):
    email: str
    paymentPlan: int


class LoginResponse(BaseModel):
    token: str
    email: str
    message: str


class PaymentStatusResponse(BaseModel):
    status: str
    remaining_days: int
    message: str


class PaymentUpdateResponse(BaseModel):
    message: str
