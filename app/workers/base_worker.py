import asyncio
import signal
import sys
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging
from app.core.redis_queue import RedisQueue
from app.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Base class for all workers"""
    
    def __init__(self, queue_name: str, worker_name: str = None):
        self.queue_name = queue_name
        self.worker_name = worker_name or f"{queue_name}_worker"
        self.queue = RedisQueue(queue_name)
        self.is_running = True
        self._setup_signal_handlers()
        
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.is_running = False
    
    @abstractmethod
    async def process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a job - must be implemented by subclass"""
        pass
    
    async def run(self, concurrency: int = 1, poll_interval: float = 1.0):
        """Run the worker with specified concurrency"""
        logger.info(f"Starting {self.worker_name} with concurrency {concurrency}")
        
        # Create tasks for each concurrent worker
        tasks = []
        for i in range(concurrency):
            tasks.append(self._worker_loop(f"worker-{i+1}", poll_interval))
        
        # Wait for all tasks
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            logger.info(f"{self.worker_name} stopped")
    
    async def _worker_loop(self, worker_id: str, poll_interval: float):
        """Main worker loop"""
        logger.info(f"{worker_id} started")
        
        while self.is_running:
            try:
                # Dequeue a job
                job_data = await self.queue.dequeue()
                
                if job_data:
                    job_id = job_data.get('job_id')
                    logger.info(f"{worker_id} processing job {job_id}")
                    
                    try:
                        # Process the job
                        result = await self.process_job(job_data)
                        
                        # Mark as completed
                        await self.queue.complete_job(job_id, result)
                        logger.info(f"{worker_id} completed job {job_id}")
                        
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"{worker_id} failed job {job_id}: {error_msg}")
                        
                        # Mark as failed (will retry if possible)
                        await self.queue.fail_job(job_id, error_msg, retry=True)
                else:
                    # No jobs, wait a bit
                    await asyncio.sleep(poll_interval)
                    
            except Exception as e:
                logger.error(f"{worker_id} error: {e}")
                await asyncio.sleep(poll_interval * 2)
        
        logger.info(f"{worker_id} stopped")
    
    async def shutdown(self):
        """Gracefully shutdown the worker"""
        self.is_running = False
        logger.info(f"{self.worker_name} shutting down")