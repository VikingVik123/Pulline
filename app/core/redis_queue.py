import json
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from app.core.redis_config import RedisService


class RedisQueue:
    """Simple Redis queue for background file processing"""
    
    def __init__(self, queue_name: str = "file_queue"):
        self.redis_service = RedisService()
        self.queue_name = queue_name
        self.queue_key = f"queue:{queue_name}"

    async def _get_redis(self):
        """Get Redis connection"""
        return await self.redis_service._get_redis()

    async def enqueue(self, job_data: Dict[str, Any]) -> str:
        """Add a job to the queue"""
        redis = await self._get_redis()
        if not redis:
            raise Exception("Redis connection unavailable")
        
        job_id = str(uuid.uuid4())
        job_data.update({
            "job_id": job_id,
            "enqueued_at": datetime.utcnow().isoformat()
        })
        
        # Store job data with expiry (7 days)
        job_key = f"{self.queue_key}:job:{job_id}"
        await redis.setex(job_key, 604800, json.dumps(job_data))
        
        # Push to queue
        await redis.rpush(self.queue_key, job_id)
        
        return job_id

    async def dequeue(self) -> Optional[Dict[str, Any]]:
        """Get a job from the queue (FIFO)"""
        redis = await self._get_redis()
        if not redis:
            return None
        
        # Pop from left (FIFO)
        job_id = await redis.lpop(self.queue_key)
        if not job_id:
            return None
        
        # Get job data
        job_key = f"{self.queue_key}:job:{job_id}"
        job_data_raw = await redis.get(job_key)
        if not job_data_raw:
            return None
        
        return json.loads(job_data_raw)

    async def get_queue_length(self) -> int:
        """Get number of jobs in queue"""
        redis = await self._get_redis()
        if not redis:
            return 0
        return await redis.llen(self.queue_key)

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job from queue"""
        redis = await self._get_redis()
        if not redis:
            return False
        
        job_key = f"{self.queue_key}:job:{job_id}"
        return await redis.delete(job_key) > 0