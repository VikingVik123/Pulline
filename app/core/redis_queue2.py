import json
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio
from app.core.redis_config import RedisService
import logging

logger = logging.getLogger(__name__)


class RedisQueue:
    """Redis-based queue for background processing"""
    
    def __init__(self, queue_name: str = "ifc_processing_queue"):
        self.redis_service = RedisService()
        self.queue_name = queue_name
        self.queue_key = f"queue:{queue_name}"
        self.processing_key = f"{self.queue_key}:processing"
        self.failed_key = f"{self.queue_key}:failed"
        self.completed_key = f"{self.queue_key}:completed"
        self.job_prefix = f"{self.queue_key}:job:"

    async def _get_redis(self):
        """Get Redis connection"""
        return await self.redis_service._get_redis()

    async def enqueue(self, job_data: Dict[str, Any], priority: int = 5) -> str:
        """Add a job to the queue with priority"""
        redis = await self._get_redis()
        if not redis:
            raise Exception("Redis connection unavailable")
        
        job_id = str(uuid.uuid4())
        job_data.update({
            "job_id": job_id,
            "enqueued_at": datetime.utcnow().isoformat(),
            "priority": priority,
            "status": "queued",
            "retry_count": 0,
            "max_retries": 3
        })
        
        # Store job data with expiry (7 days)
        job_key = f"{self.job_prefix}{job_id}"
        await redis.setex(job_key, 604800, json.dumps(job_data))
        
        # Add to priority queue (using sorted set)
        queue_key = f"{self.queue_key}:pending"
        await redis.zadd(queue_key, {job_id: priority})
        
        logger.info(f"Job {job_id} enqueued with priority {priority}")
        return job_id

    async def dequeue(self) -> Optional[Dict[str, Any]]:
        """Get the highest priority job from the queue"""
        redis = await self._get_redis()
        if not redis:
            return None
        
        queue_key = f"{self.queue_key}:pending"
        
        # Get job with highest priority (lowest score)
        result = await redis.zpopmin(queue_key, 1)
        if not result:
            return None
        
        job_id = result[0][0]
        
        # Get job data
        job_key = f"{self.job_prefix}{job_id}"
        job_data_raw = await redis.get(job_key)
        if not job_data_raw:
            return None
        
        job_data = json.loads(job_data_raw)
        
        # Move to processing set
        await redis.sadd(self.processing_key, job_id)
        await redis.expire(self.processing_key, 3600)
        
        job_data["status"] = "processing"
        job_data["dequeued_at"] = datetime.utcnow().isoformat()
        await redis.setex(job_key, 604800, json.dumps(job_data))
        
        logger.info(f"Job {job_id} dequeued for processing")
        return job_data

    async def complete_job(self, job_id: str, result: Dict[str, Any]) -> bool:
        """Mark a job as completed"""
        redis = await self._get_redis()
        if not redis:
            return False
        
        # Remove from processing
        await redis.srem(self.processing_key, job_id)
        
        # Add to completed set
        await redis.sadd(self.completed_key, job_id)
        await redis.expire(self.completed_key, 86400)
        
        # Update job data
        job_key = f"{self.job_prefix}{job_id}"
        job_data_raw = await redis.get(job_key)
        if job_data_raw:
            job_data = json.loads(job_data_raw)
            job_data["status"] = "completed"
            job_data["completed_at"] = datetime.utcnow().isoformat()
            job_data["result"] = result
            await redis.setex(job_key, 604800, json.dumps(job_data))
        
        logger.info(f"Job {job_id} completed")
        return True

    async def fail_job(self, job_id: str, error: str, retry: bool = True) -> bool:
        """Mark a job as failed or retry"""
        redis = await self._get_redis()
        if not redis:
            return False
        
        # Remove from processing
        await redis.srem(self.processing_key, job_id)
        
        # Get job data
        job_key = f"{self.job_prefix}{job_id}"
        job_data_raw = await redis.get(job_key)
        if not job_data_raw:
            return False
        
        job_data = json.loads(job_data_raw)
        job_data["status"] = "failed"
        job_data["failed_at"] = datetime.utcnow().isoformat()
        job_data["error"] = error
        job_data["retry_count"] = job_data.get("retry_count", 0) + 1
        
        # Check if should retry
        max_retries = job_data.get("max_retries", 3)
        if retry and job_data["retry_count"] < max_retries:
            # Re-queue with updated priority (lower priority after failure)
            queue_key = f"{self.queue_key}:pending"
            await redis.zadd(queue_key, {job_id: job_data.get("priority", 5) + 1})
            job_data["status"] = "queued"
            await redis.setex(job_key, 604800, json.dumps(job_data))
            logger.warning(f"Job {job_id} failed, retry {job_data['retry_count']}/{max_retries}")
            return True
        else:
            # Add to failed set
            await redis.sadd(self.failed_key, job_id)
            await redis.expire(self.failed_key, 86400)
            await redis.setex(job_key, 604800, json.dumps(job_data))
            logger.error(f"Job {job_id} failed permanently: {error}")
            return False

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a job"""
        redis = await self._get_redis()
        if not redis:
            return None
        
        job_key = f"{self.job_prefix}{job_id}"
        job_data_raw = await redis.get(job_key)
        if not job_data_raw:
            return None
        
        job_data = json.loads(job_data_raw)
        
        # Check current state
        is_processing = await redis.sismember(self.processing_key, job_id)
        is_completed = await redis.sismember(self.completed_key, job_id)
        is_failed = await redis.sismember(self.failed_key, job_id)
        
        if is_processing:
            job_data["current_status"] = "processing"
        elif is_completed:
            job_data["current_status"] = "completed"
        elif is_failed:
            job_data["current_status"] = "failed"
        else:
            job_data["current_status"] = "queued"
        
        return job_data

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        redis = await self._get_redis()
        if not redis:
            return {"queue_name": self.queue_name, "pending": 0, "processing": 0, "completed": 0, "failed": 0}
        
        queue_key = f"{self.queue_key}:pending"
        
        pending_count = await redis.zcard(queue_key)
        processing_count = await redis.scard(self.processing_key)
        completed_count = await redis.scard(self.completed_key)
        failed_count = await redis.scard(self.failed_key)
        
        return {
            "queue_name": self.queue_name,
            "pending": pending_count,
            "processing": processing_count,
            "completed": completed_count,
            "failed": failed_count,
            "total": pending_count + processing_count + completed_count + failed_count
        }

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued or processing job"""
        redis = await self._get_redis()
        if not redis:
            return False
        
        # Remove from pending queue
        queue_key = f"{self.queue_key}:pending"
        await redis.zrem(queue_key, job_id)
        
        # Remove from processing
        await redis.srem(self.processing_key, job_id)
        
        # Update job data
        job_key = f"{self.job_prefix}{job_id}"
        job_data_raw = await redis.get(job_key)
        if job_data_raw:
            job_data = json.loads(job_data_raw)
            job_data["status"] = "cancelled"
            job_data["cancelled_at"] = datetime.utcnow().isoformat()
            await redis.setex(job_key, 604800, json.dumps(job_data))
        
        logger.info(f"Job {job_id} cancelled")
        return True

    async def get_job_position(self, job_id: str) -> Optional[int]:
        """Get the position of a job in the queue"""
        redis = await self._get_redis()
        if not redis:
            return None
        
        queue_key = f"{self.queue_key}:pending"
        jobs = await redis.zrange(queue_key, 0, -1, withscores=True)
        
        for idx, (jid, _) in enumerate(jobs):
            if jid == job_id:
                return idx + 1
        
        return None
    
    async def get_pending_jobs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get list of pending jobs"""
        redis = await self._get_redis()
        if not redis:
            return []
        
        queue_key = f"{self.queue_key}:pending"
        job_ids = await redis.zrange(queue_key, 0, limit - 1)
        
        jobs = []
        for job_id in job_ids:
            job_key = f"{self.job_prefix}{job_id}"
            job_data_raw = await redis.get(job_key)
            if job_data_raw:
                job_data = json.loads(job_data_raw)
                jobs.append(job_data)
        
        return jobs