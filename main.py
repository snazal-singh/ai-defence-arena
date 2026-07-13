import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter
from app.models.mongo import Fingerprint, UserSession, User
from app.api.auth import router as auth_router
from app.api.accounts import router as accounts_router
from app.api.queries import router as queries_router
from app.api.documents import router as documents_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def init_db() -> None:
    client = AsyncIOMotorClient(settings.MONGO_URL)
    await init_beanie(database=client.test, document_models=[Fingerprint, UserSession, User])
    logger.info("MongoDB and Beanie initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="sachet-backend",
    description="icarKno document intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Validation error handler — sanitise binary blobs so the response is
# always JSON-serialisable (prevents UnicodeDecodeError on file uploads).
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    def _sanitise(obj):
        if isinstance(obj, bytes):
            return f"<binary {len(obj)} bytes>"
        if isinstance(obj, dict):
            return {k: _sanitise(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitise(v) for v in obj]
        return obj

    safe_errors = _sanitise(exc.errors())
    
    # Debug logging
    try:
        body = await request.body()
        logger.error(f"❌ VALIDATION ERROR! Errors: {safe_errors} | Request body: {body.decode('utf-8', errors='ignore')}")
    except Exception as e:
        logger.error(f"❌ VALIDATION ERROR! Errors: {safe_errors} | Could not read request body: {e}")
        
    return JSONResponse(status_code=422, content={"detail": safe_errors})


# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url}: {exc}")
    return JSONResponse(status_code=500, content={"message": "Internal server error"})


# Routers — all under /api/v1
PREFIX = "/api/v1"
app.include_router(auth_router, prefix=PREFIX)
app.include_router(accounts_router, prefix=PREFIX)
app.include_router(documents_router, prefix=PREFIX)
app.include_router(queries_router, prefix=PREFIX)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
