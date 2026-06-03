from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.modules.ingest.routers.ingest_routers import router as ingest_router
from app.db.database import init_db
from app.core import get_settings, get_logger, setup_logging
from app.core.exceptions import PullineException
import os

# Setup logging on module load
setup_logging()
logger = get_logger(__name__)
settings = get_settings()

# Create upload directory at startup (before app initialization)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    logger.info(f"Starting Pulline API in {settings.ENV} environment")
    await init_db()
    logger.info("Database and file storage initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Pulline API")


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    lifespan=lifespan,
    debug=settings.DEBUG,
)


@app.exception_handler(PullineException)
async def pulline_exception_handler(request, exc: PullineException):
    """Handle custom Pulline exceptions."""
    logger.warning(f"Pulline exception: {exc.error_code} - {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

app.include_router(ingest_router, prefix="/ingest", tags=["Ingest"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "environment": settings.ENV}


app.mount("/static", StaticFiles(directory=settings.UPLOAD_DIR))