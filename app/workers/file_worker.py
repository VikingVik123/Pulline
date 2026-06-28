import asyncio
import logging
from app.core.redis_queue import RedisQueue
from app.modules.ingestion.services import IngestionService
from app.db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def process_file_job():
    """Worker to process file jobs from Redis queue in background"""
    
    queue = RedisQueue("file_queue")
    
    while True:
        try:
            # Get job from queue
            job_data = await queue.dequeue()
            
            if not job_data:
                await asyncio.sleep(1)
                continue
            
            logger.info(f"Processing job: {job_data.get('job_id')}")
            
            # Process the job - just marks as completed
            async with AsyncSessionLocal() as db:
                service = IngestionService(db)
                result = await service.process_file_job(job_data)
            
            logger.info(f"Job completed: {result.get('status')}")
            
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    logger.info("Starting file worker...")
    asyncio.run(process_file_job())