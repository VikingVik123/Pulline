import asyncio
from uuid import UUID

# Force SQLAlchemy to register all models
from app.modules.auth.models.auth_model import (
    User,
    RefreshToken,
    PasswordResetToken,
)
from app.modules.ingest.models.model import Ingest
from app.modules.ifc_processing.models.ifc_model import IFCProject

from app.core.redis_config import RedisService
from app.db.database import AsyncSessionLocal
from app.modules.ifc_processing.services.services import IFCProcessingService


async def worker():

    redis = RedisService()

    while True:

        job = await redis.dequeue_project()

        if job is None:
            continue

        project_id = UUID(job["project_id"])

        async with AsyncSessionLocal() as db:

            service = IFCProcessingService(db)

            try:
                await service.process_project(project_id)

            except Exception as e:
                print(e)


if __name__ == "__main__":
    asyncio.run(worker())