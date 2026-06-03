from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core import get_settings, get_logger

logger = get_logger(__name__)

# Create a Base for model classes
Base = declarative_base()

# Get settings
settings = get_settings()

# Create engine with settings from config
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """Get a database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Initialize the database by creating all tables."""
    try:
        logger.info(f"Initializing database: {settings.DATABASE_URL}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialization completed")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise