from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.modules.auth.routers.auth_routes import router as auth_router
from app.db.database import engine, Base
from app.core.config import settings
from app.core.redis_config import RedisService
import logging

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
    
    # Create database tables
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    
    # Test Redis connection
    try:
        redis_service = RedisService()
        if await redis_service.ping():
            logger.info("Redis connected successfully!")
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
    description="Authentication API with Redis token management",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Include routers
app.include_router(auth_router)


# ============ HEALTH CHECK ENDPOINTS ============

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to the API",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
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
    
    return health_status


@app.get("/ping")
async def ping():
    """Simple ping endpoint for basic health checks"""
    return {"ping": "pong"}


# ============ OPTIONAL: CORS MIDDLEWARE ============
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Adjust for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ============ ERROR HANDLERS ============

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "status_code": exc.status_code,
            "path": request.url.path
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Custom validation exception handler"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "body": exc.body,
            "path": request.url.path
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler for unhandled exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred",
            "path": request.url.path
        },
    )


# ============ ADD REQUIRED IMPORTS ============

from datetime import datetime
from fastapi import status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )