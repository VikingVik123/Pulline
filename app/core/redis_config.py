from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.config import settings


class RedisService:
    """
    Central Redis service.

    Responsibilities
    ----------------
    • JWT token storage
    • JWT blacklisting
    • User session revocation
    • IFC processing queue
    • Generic Redis helpers
    """

    IFC_QUEUE = "ifc:processing"

    def __init__(self) -> None:

        self.redis: Redis = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=5,
            socket_timeout=None,
            health_check_interval=30,
            retry_on_timeout=True,
            max_connections=20,
        )

    # ==========================================================
    # Connection
    # ==========================================================

    async def ping(self) -> bool:
        return await self.redis.ping()

    async def close(self):
        await self.redis.aclose()

    # ==========================================================
    # Generic Helpers
    # ==========================================================

    async def set_json(
        self,
        key: str,
        value: dict,
        expire: int | None = None,
    ):

        payload = json.dumps(value)

        if expire is None:
            await self.redis.set(key, payload)
        else:
            await self.redis.setex(key, expire, payload)

    async def get_json(
        self,
        key: str,
    ) -> dict[str, Any] | None:

        value = await self.redis.get(key)

        if value is None:
            return None

        return json.loads(value)

    async def delete(
        self,
        key: str,
    ):

        await self.redis.delete(key)

    async def exists(
        self,
        key: str,
    ) -> bool:

        return await self.redis.exists(key) > 0

    # ==========================================================
    # IFC Queue
    # ==========================================================

    async def enqueue_project(
        self,
        project_id: UUID,
    ):

        await self.redis.rpush(
            self.IFC_QUEUE,
            json.dumps(
                {
                    "project_id": str(project_id),
                }
            ),
        )

    async def dequeue_project(self):

        result = await self.redis.blpop(
            self.IFC_QUEUE,
            timeout=0,
        )

        if result is None:
            return None

        _, payload = result

        return json.loads(payload)

    async def queue_size(self) -> int:

        return await self.redis.llen(self.IFC_QUEUE)

    async def queue_position(
        self,
        project_id: UUID,
    ) -> int | None:

        jobs = await self.redis.lrange(
            self.IFC_QUEUE,
            0,
            -1,
        )

        pid = str(project_id)

        for index, raw in enumerate(jobs):

            job = json.loads(raw)

            if job["project_id"] == pid:
                return index + 1

        return None

    async def queued_projects(self):

        jobs = await self.redis.lrange(
            self.IFC_QUEUE,
            0,
            -1,
        )

        return [json.loads(job) for job in jobs]

    # ==========================================================
    # Token Storage
    # ==========================================================

    async def store_token(
        self,
        token: str,
        user_id: UUID,
        token_type: str = "access",
        expires: int = 1800,
    ) -> None:

        token_key = f"{settings.REDIS_TOKEN_PREFIX}{token}"
        user_key = f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"

        await self.set_json(
            token_key,
            {
                "user_id": str(user_id),
                "type": token_type,
                "created_at": datetime.utcnow().isoformat(),
            },
            expire=expires,
        )

        await self.redis.sadd(
            user_key,
            token,
        )

        await self.redis.expire(
            user_key,
            expires + 3600,
        )

    async def store_refresh_token(
        self,
        token: str,
        user_id: UUID,
        expires: int,
    ):

        await self.store_token(
            token=token,
            user_id=user_id,
            token_type="refresh",
            expires=expires,
        )

    async def get_token(
        self,
        token: str,
    ) -> dict[str, Any] | None:

        return await self.get_json(
            f"{settings.REDIS_TOKEN_PREFIX}{token}"
        )

    async def get_token_data(
        self,
        token: str,
    ) -> dict[str, Any] | None:

        return await self.get_token(token)

    async def delete_token(
        self,
        token: str,
    ):

        token_data = await self.get_token(token)

        if token_data:

            user_key = (
                f"{settings.REDIS_USER_TOKENS_PREFIX}"
                f"{token_data['user_id']}"
            )

            await self.redis.srem(
                user_key,
                token,
            )

        await self.delete(
            f"{settings.REDIS_TOKEN_PREFIX}{token}"
        )

    async def get_user_active_tokens(
        self,
        user_id: UUID,
    ) -> list[str]:

        return await self.redis.smembers(
            f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"
        )

    # ==========================================================
    # Blacklist
    # ==========================================================

    async def blacklist_token(
        self,
        token: str,
        expires: int,
    ):

        await self.redis.setex(
            f"{settings.REDIS_BLACKLIST_PREFIX}{token}",
            expires,
            datetime.utcnow().isoformat(),
        )

    async def is_blacklisted(
        self,
        token: str,
    ) -> bool:

        return await self.exists(
            f"{settings.REDIS_BLACKLIST_PREFIX}{token}"
        )

    async def is_token_blacklisted(
        self,
        token: str,
    ) -> bool:

        return await self.is_blacklisted(token)

    # ==========================================================
    # User-wide Revocation
    # ==========================================================

    async def revoke_all_user_tokens(
        self,
        user_id: UUID,
    ) -> int:

        user_key = (
            f"{settings.REDIS_USER_TOKENS_PREFIX}{user_id}"
        )

        tokens = await self.redis.smembers(user_key)

        revoked = 0

        for token in tokens:

            await self.blacklist_token(
                token,
                60 * 60 * 24 * 7,
            )

            await self.delete_token(token)

            revoked += 1

        await self.redis.delete(user_key)

        await self.redis.setex(
            f"{settings.REDIS_BLACKLIST_PREFIX}user:{user_id}",
            60 * 60 * 24 * 7,
            datetime.utcnow().isoformat(),
        )

        return revoked

    async def is_token_revoked_for_user(
        self,
        token: str,
        user_id: UUID,
    ) -> bool:

        revoked_at = await self.redis.get(
            f"{settings.REDIS_BLACKLIST_PREFIX}user:{user_id}"
        )

        if revoked_at is None:
            return False

        token_data = await self.get_token(token)

        if token_data is None:
            return False

        created_at = token_data.get("created_at")

        if created_at is None:
            return False

        return (
            datetime.fromisoformat(created_at)
            < datetime.fromisoformat(revoked_at)
        )

    # ==========================================================
    # Statistics
    # ==========================================================

    async def stats(self):

        info = await self.redis.info()

        return {
            "version": info["redis_version"],
            "clients": info["connected_clients"],
            "memory": info["used_memory_human"],
            "uptime": info["uptime_in_seconds"],
        }