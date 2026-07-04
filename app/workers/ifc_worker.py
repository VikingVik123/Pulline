import asyncio
import sys
from pathlib import Path
from typing import Dict, Any
from uuid import UUID
import logging
from sqlalchemy.ext.asyncio import AsyncSession

# ✅ Fix imports to use absolute paths
from app.workers.base_worker import BaseWorker
from app.modules.ifc_processing.services.services import IFCProcessingService
from app.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class IFCWorker(BaseWorker):
    """Worker for processing IFC files"""
    
    def __init__(self):
        super().__init__(queue_name="ifc_processing_queue", worker_name="IFCWorker")
    
    async def process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process an IFC job"""
        project_id = job_data.get('project_id')
        user_id = job_data.get('user_id')
        file_path = job_data.get('file_path')
        
        logger.info(f"Processing IFC job: project_id={project_id}, file_path={file_path}")
        
        # Use an async session for the database operations
        async with AsyncSessionLocal() as db:
            service = IFCProcessingService(db)
            result = await service.process_ifc_job(job_data)
            
            # If processing failed, raise exception to trigger retry
            if result.get('status') == 'failed':
                raise Exception(result.get('error', 'Processing failed'))
            
            return result


def run_worker():
    """Entry point for running the worker"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run IFC worker")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent workers")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Poll interval in seconds")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    worker = IFCWorker()
    
    try:
        asyncio.run(worker.run(
            concurrency=args.concurrency,
            poll_interval=args.poll_interval
        ))
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_worker()