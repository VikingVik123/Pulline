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
from app.workers.email_worker import email_worker
import asyncio
import logging
from pathlib import Path
from uuid import UUID

# Force SQLAlchemy to register all models
from app.modules.auth.models.auth_model import User, RefreshToken, PasswordResetToken
from app.modules.ingest.models.model import Ingest
from app.modules.ifc_processing.models.ifc_model import IFCProject
from app.db.database import AsyncSessionLocal
from app.modules.ifc_processing.services.services import IFCProcessingService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def ifc_worker():
    """Background worker for IFC project processing."""
    redis = RedisService()
    logger.info("🏗️ IFC worker started")
    
    while True:
        try:
            job = await redis.dequeue_project()
            
            if job is None:
                await asyncio.sleep(2)  # Wait before checking again
                continue
            
            project_id = UUID(job["project_id"])
            logger.info(f"Processing IFC project: {project_id}")
            
            async with AsyncSessionLocal() as db:
                service = IFCProcessingService(db)
                try:
                    await service.process_project(project_id)
                    logger.info(f"✅ IFC project processed: {project_id}")
                except Exception as e:
                    logger.error(f"❌ IFC project failed: {project_id} - {e}")
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"IFC worker error: {e}")
            await asyncio.sleep(5)
    
    await redis.close()
    logger.info("🏗️ IFC worker stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
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
    
    # Test Redis connection
    try:
        redis_service = RedisService()
        if await redis_service.ping():
            logger.info("Redis connected successfully!")
        else:
            logger.warning("Redis connection failed - running without Redis cache")
    except Exception as e:
        logger.warning(f"Redis initialization warning: {e}")
    
    # Start background workers
    #email_task = asyncio.create_task(email_worker.run())
    #ifc_task = asyncio.create_task(ifc_worker())
    #logger.info("📧 Email worker started")
    #logger.info("🏗️ IFC worker started")
    
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
upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
try:
    upload_dir.mkdir(parents=True, exist_ok=True)
except Exception as e:
    logger.error(f"Failed to create upload directory: {e}")
    raise
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

ifc_output_dir = Path("ifc_outputs")
try:
    ifc_output_dir.mkdir(parents=True, exist_ok=True)
except Exception as e:
    logger.error(f"Failed to create IFC output directory: {e}")
    raise
app.mount("/ifc-outputs", StaticFiles(directory=ifc_output_dir), name="ifc-output")
app.mount("/ifc_outputs", StaticFiles(directory="ifc_outputs"), name="ifc_output")

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
    
    # Check workers
    try:
        redis_service = RedisService()
        email_queue = await redis_service.get_email_queue_size()
        ifc_queue = await redis_service.get_queue_size("ifc_project_queue")  # Adjust key name if needed
        health_status["services"]["workers"] = {
            "email": f"running (queue: {email_queue})",
            "ifc": f"running (queue: {ifc_queue})"
        }
    except Exception as e:
        health_status["services"]["workers"] = f"error: {str(e)}"
    
    # Check directories
    try:
        upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
        health_status["services"]["uploads"] = "accessible" if upload_dir.exists() else "not_found"
    except Exception as e:
        health_status["services"]["uploads"] = f"error: {str(e)}"
    
    try:
        ifc_output_dir = Path("ifc_outputs")
        health_status["services"]["ifc_outputs"] = "accessible" if ifc_output_dir.exists() else "not_found"
    except Exception as e:
        health_status["services"]["ifc_outputs"] = f"error: {str(e)}"
    
    return health_status


@app.get("/ping")
async def ping():
    return {"ping": "pong"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )