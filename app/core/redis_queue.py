import json
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import settings


class RedisQueue:

    def __init__(self):
        self.redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )

        self.queue = "ifc_processing"

    async def enqueue(
        self,
        project_id: UUID,
    ):

        await self.redis.rpush(
            self.queue,
            json.dumps(
                {
                    "project_id": str(project_id),
                }
            ),
        )

    async def dequeue(self):

        result = await self.redis.blpop(
            self.queue,
            timeout=0,
        )

        if result is None:
            return None

        _, payload = result

        return json.loads(payload)