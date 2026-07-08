from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.modules.auth.routers.auth_routes import router as auth_router
from app.modules.ingest.routers.ingest_route import router as ingestion_router
from app.modules.ifc_processing.routers.ifc_router import router as ifc_router
from app.db.database import engine, Base
from app.core.config import settings
from app.core.redis_config import RedisService

import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    This replaces the deprecated @app.on_event decorators.
    """
    # ============ STARTUP ============
    logger.info("Starting up application...")
    
    # Create upload directory if it doesn't exist
    upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Upload directory ready: {upload_dir}")
    
    # Create IFC output directory
    ifc_output_dir = Path("ifc_outputs")
    ifc_output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"IFC output directory ready: {ifc_output_dir}")
    
    # Create database tables (commented out - use Alembic migrations instead)
    # try:
    #     async with engine.begin() as conn:
    #         await conn.run_sync(Base.metadata.create_all)
    #     logger.info("Database tables created/verified")
    # except Exception as e:
    #     logger.error(f"Database initialization failed: {e}")
    #     raise
    
    # Test Redis connection
    try:
        redis_service = RedisService()
        if await redis_service.ping():
            logger.info("Redis connected successfully!")
            logger.info(f"Queue stats: {stats}")
        else:
            logger.warning("Redis connection failed - running without Redis cache")
    except Exception as e:
        logger.warning(f"Redis initialization warning: {e}")
    
    logger.info("Application startup complete!")
    
    # ============ YIELD ============
    yield
    
    # ============ SHUTDOWN ============
    logger.info("Shutting down application...")
    
    # Close Redis connection
    try:
        redis_service = RedisService()
        await redis_service.close()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.warning(f"Error closing Redis connection: {e}")
    
    # Close database connection
    try:
        await engine.dispose()
        logger.info("Database connection closed")
    except Exception as e:
        logger.warning(f"Error closing database connection: {e}")
    
    logger.info("Application shutdown complete!")


# Create FastAPI app with lifespan
app = FastAPI(
    title=settings.API_TITLE,
    version="1.0.0",
    description="Authentication API with Redis token management, file ingestion, and IFC processing",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# ============ STATIC FILES ============
# Serve uploaded files
upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
try:
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Upload directory ready: {upload_dir.absolute()}")
except Exception as e:
    logger.error(f"Failed to create upload directory: {e}")
    raise
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

# Serve IFC output files
ifc_output_dir = Path("ifc_outputs")
try:
    ifc_output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"IFC output directory ready: {ifc_output_dir.absolute()}")
except Exception as e:
    logger.error(f"Failed to create IFC output directory: {e}")
    raise
app.mount("/ifc-outputs", StaticFiles(directory=ifc_output_dir), name="ifc-output")
app.mount(
    "/ifc_outputs",
    StaticFiles(directory="ifc_outputs"),
    name="ifc_output",
)

# ============ CORS MIDDLEWARE ============
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if hasattr(settings, 'CORS_ORIGINS') else ["*"],
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS if hasattr(settings, 'CORS_ALLOW_CREDENTIALS') else True,
    allow_methods=settings.CORS_ALLOW_METHODS if hasattr(settings, 'CORS_ALLOW_METHODS') else ["*"],
    allow_headers=settings.CORS_ALLOW_HEADERS if hasattr(settings, 'CORS_ALLOW_HEADERS') else ["*"],
)

# ============ INCLUDE ROUTERS ============
app.include_router(auth_router)
app.include_router(ingestion_router)
app.include_router(ifc_router)

# ============ HEALTH CHECK ENDPOINTS ============

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to the API",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "auth": "/auth",
            "ingestion": "/ingestion",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    from datetime import datetime
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {}
    }
    
    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        health_status["services"]["database"] = "connected"
    except Exception as e:
        health_status["services"]["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        redis_service = RedisService()
        if await redis_service.ping():
            health_status["services"]["redis"] = "connected"
        else:
            health_status["services"]["redis"] = "disconnected"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["services"]["redis"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check upload directory
    try:
        upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
        health_status["services"]["uploads"] = "accessible" if upload_dir.exists() else "not_found"
    except Exception as e:
        health_status["services"]["uploads"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check IFC output directory
    try:
        ifc_output_dir = Path("ifc_outputs")
        health_status["services"]["ifc_outputs"] = "accessible" if ifc_output_dir.exists() else "not_found"
    except Exception as e:
        health_status["services"]["ifc_outputs"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status


@app.get("/ping")
async def ping():
    """Simple ping endpoint for basic health checks"""
    return {"ping": "pong"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )