import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from models.schemas import HealthResponse
from routers.faults import router as faults_router
from routers.generate import router as generate_router
from routers.ladder import router as ladder_router
from routers.parse import router as parse_router
from routers.trace import router as trace_router
from services.session_service import session_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("LogicLens API starting up…")
    # Pre-warm services (singletons are already initialised on import)
    yield
    logger.info("LogicLens API shutting down.")


app = FastAPI(
    title="LogicLens API",
    description="AI-Powered PLC Ladder Logic Analyzer & Debugger",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(parse_router)
app.include_router(trace_router)
app.include_router(faults_router)
app.include_router(generate_router, prefix="/api/generate")
app.include_router(ladder_router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"name": "LogicLens", "version": "1.0.0", "status": "running"}


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        active_sessions=session_service.count_sessions(),
        version="1.0.0",
    )
