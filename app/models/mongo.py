from typing import List, Optional
from pydantic import BaseModel
from beanie import Document, Indexed


class Fingerprint(Document):
    fingerprint: Indexed(str, unique=True)
    freeTrial: Optional[str] = None
    message: int = 0

    class Settings:
        name = "fingerprint"


class SessionData(BaseModel):
    session_id: str
    file_names: List[str] = []
    name: str
    timestamp: str


class UserSession(Document):
    user_email: Indexed(str)
    sessions: List[SessionData] = []

    class Settings:
        name = "sessions"


class User(Document):
    email: Indexed(str, unique=True)
    password: str
    paid: int = 0
    queries: int = 0
    expiry_date: int = 0

    class Settings:
        name = "users"
