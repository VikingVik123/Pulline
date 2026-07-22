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
    EMAIL_QUEUE = "email:queue"
    EMAIL_FAILED_QUEUE = "email:failed"

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

    # ==========================================================
    # EMAIL QUEUE - NEW
    # ==========================================================

    async def enqueue_email(
        self,
        to_email: str,
        email_type: str,
        subject: str,
        html_content: str,
        priority: str = "normal",  # high, normal, low
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> str:
        """
        Add email to Redis queue for background processing.
        Returns the job ID.
        """

        job_id = f"email:{datetime.utcnow().timestamp()}:{to_email}"
        
        email_job = {
            "job_id": job_id,
            "to_email": to_email,
            "email_type": email_type,
            "subject": subject,
            "html_content": html_content,
            "priority": priority,
            "retry_count": retry_count,
            "max_retries": max_retries,
            "created_at": datetime.utcnow().isoformat(),
            "status": "queued"
        }

        # Store job data
        await self.set_json(
            f"email:job:{job_id}",
            email_job,
            expire=86400  # 24 hours
        )
        # Add to queue based on priority
        if priority == "high":
            await self.redis.lpush(self.EMAIL_QUEUE, job_id)
        else:
            await self.redis.rpush(self.EMAIL_QUEUE, job_id)
        
        # Track queue size
        await self.redis.incr("email:queue:count")
        
        return job_id

    async def dequeue_email(self, timeout: int = 0) -> Optional[dict]:
        """
        Get next email job from queue.
        """
        result = await self.redis.blpop(self.EMAIL_QUEUE, timeout=timeout)
        if result is None:
            return None
        
        _, job_id = result
        
        # Get job data
        job_data = await self.get_json(f"email:job:{job_id}")
        
        if job_data:
            job_data["status"] = "processing"
            await self.set_json(
                f"email:job:{job_id}",
                job_data,
                expire=86400
            )
            await self.redis.decr("email:queue:count")
        
        return job_data

    async def get_email_queue_size(self) -> int:
        """Get current email queue size."""
        return await self.redis.llen(self.EMAIL_QUEUE)

    async def get_email_queue_count(self) -> int:
        """Get total queued email count."""
        count = await self.redis.get("email:queue:count")
        return int(count) if count else 0

    async def mark_email_sent(self, job_id: str, success: bool, error: str = None):
        """Mark email job as sent or failed."""
        job_data = await self.get_json(f"email:job:{job_id}")
        if not job_data:
            return
        
        if success:
            job_data["status"] = "sent"
            job_data["sent_at"] = datetime.utcnow().isoformat()
            await self.set_json(
                f"email:job:{job_id}",
                job_data,
                expire=86400
            )
            # Track successful send
            await self.redis.hincrby("email:stats", "sent", 1)
        else:
            job_data["status"] = "failed"
            job_data["error"] = error
            job_data["retry_count"] = job_data.get("retry_count", 0) + 1
            
            # Check if we should retry
            if job_data["retry_count"] < job_data.get("max_retries", 3):
                # Re-queue with retry
                job_data["status"] = "queued"
                await self.set_json(
                    f"email:job:{job_id}",
                    job_data,
                    expire=86400
                )
                # Add back to queue with delay
                await self.redis.rpush(self.EMAIL_QUEUE, job_id)
                await self.redis.incr("email:queue:count")
            else:
                # Move to failed queue
                await self.redis.rpush(self.EMAIL_FAILED_QUEUE, job_id)
                await self.set_json(
                    f"email:job:{job_id}",
                    job_data,
                    expire=86400
                )
                await self.redis.hincrby("email:stats", "failed", 1)

    async def get_email_stats(self) -> dict:
        """Get email statistics."""
        stats = await self.redis.hgetall("email:stats")
        queue_size = await self.get_email_queue_size()
        failed_size = await self.redis.llen(self.EMAIL_FAILED_QUEUE)
        
        return {
            "sent": int(stats.get("sent", 0)),
            "failed": int(stats.get("failed", 0)),
            "queue_size": queue_size,
            "failed_queue_size": failed_size,
            "total_processed": int(stats.get("sent", 0)) + int(stats.get("failed", 0))
        }
    
    async def retry_failed_emails(self, max_retries: int = 3) -> int:
        """Retry failed emails."""
        retried = 0
        
        while True:
            result = await self.redis.lpop(self.EMAIL_FAILED_QUEUE)
            if not result:
                break
            
            job_id = result
            job_data = await self.get_json(f"email:job:{job_id}")
            
            if job_data and job_data.get("retry_count", 0) < max_retries:
                # Re-queue for retry
                job_data["status"] = "queued"
                await self.set_json(
                    f"email:job:{job_id}",
                    job_data,
                    expire=86400
                )
                await self.redis.rpush(self.EMAIL_QUEUE, job_id)
                await self.redis.incr("email:queue:count")
                retried += 1
        
        return retried