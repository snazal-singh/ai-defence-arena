from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class SuccessResponse(BaseModel):
    success: bool
    message: str
