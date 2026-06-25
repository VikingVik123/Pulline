from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from app.core.config import settings


class Base(DeclarativeBase):
    pass


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
    """Initialize the database and create tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)