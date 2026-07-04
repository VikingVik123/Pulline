"""
Task definitions for IFC processing.
These are called by the worker to process specific jobs.
"""

import asyncio
from typing import Dict, Any
from pathlib import Path
from uuid import UUID
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.modules.ifc_processing.models.ifc_model import IFCProject, ProcessingStatus
from app.modules.ifc_processing.services.ifc_extractor import IFCElementExtractor
from app.core.config import settings
from app.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def process_ifc_file_task(
    project_id: UUID,
    user_id: UUID,
    file_path: Path,
    project_name: str = None
) -> Dict[str, Any]:
    """
    Task to process an IFC file and generate outputs.
    This is the core processing logic.
    """
    try:
        # Create output directory
        base_output_dir = Path("ifc_outputs")
        output_dir = base_output_dir / str(user_id) / str(project_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Processing IFC: {file_path}")
        logger.info(f"Output directory: {output_dir}")
        
        # Initialize extractor
        extractor = IFCElementExtractor(
            ifc_path=file_path,
            output_dir=output_dir,
            z_tolerance=0.05,
            min_segment_length=0.05
        )
        
        # Get all storey names
        extractor.get_storey_map()
        storey_names = list(set(extractor.storey_map.values()))
        logger.info(f"Found storeys: {storey_names}")
        
        # Run extraction for all storeys
        output_files = extractor.run(storeys=None)
        
        # Prepare floor data for database
        floors_data = []
        base_url = f"/ifc-outputs/{user_id}/{project_id}"
        
        for storey_name, outputs in output_files.items():
            safe_name = extractor._safe_name(storey_name)
            
            floor_data = {
                "floor_number": _extract_floor_number(storey_name, storey_names),
                "floor_name": storey_name,
                "elevation": 0.0,
                "element_count": _count_elements_from_csv(outputs.get("csv")),
                "csv_url": f"{base_url}/{safe_name}/{safe_name}.csv" if outputs.get("csv") else None,
                "png_url": f"{base_url}/{safe_name}/{safe_name}.png" if outputs.get("png") else None,
                "svg_url": f"{base_url}/{safe_name}/{safe_name}.svg" if outputs.get("svg") else None,
                "dxf_url": f"{base_url}/{safe_name}/{safe_name}.dxf" if outputs.get("dxf") else None,
                "json_url": f"{base_url}/{safe_name}/{safe_name}.json" if outputs.get("json") else None,
            }
            floors_data.append(floor_data)
        
        return {
            "status": "completed",
            "total_floors": len(floors_data),
            "floors": floors_data,
            "output_files": {k: str(v) for k, v in output_files.items()}
        }
        
    except Exception as e:
        logger.error(f"IFC processing failed: {str(e)}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e)
        }


def _extract_floor_number(storey_name: str, all_storeys: list) -> int:
    """Extract floor number from storey name"""
    import re
    
    numbers = re.findall(r'\d+', storey_name)
    if numbers:
        return int(numbers[0])
    
    if "ground" in storey_name.lower() or "0" in storey_name or "g" in storey_name.lower():
        return 1
    
    try:
        return all_storeys.index(storey_name) + 1
    except ValueError:
        return len(all_storeys) + 1


def _count_elements_from_csv(csv_path: Path) -> int:
    """Count elements from CSV file"""
    if not csv_path or not csv_path.exists():
        return 0
    
    try:
        import csv
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            return sum(1 for _ in reader) - 1  # Subtract header
    except:
        return 0


async def create_processing_job(
    project_id: UUID,
    user_id: UUID,
    file_path: Path,
    project_name: str = None
) -> Dict[str, Any]:
    """
    Create a processing job and add to queue
    """
    from app.core.redis_queue import RedisQueue
    
    queue = RedisQueue("ifc_processing_queue")
    
    job_data = {
        "project_id": str(project_id),
        "user_id": str(user_id),
        "file_path": str(file_path),
        "project_name": project_name,
        "task": "process_ifc_file"
    }
    
    job_id = await queue.enqueue(job_data, priority=5)
    
    return {
        "job_id": job_id,
        "project_id": project_id,
        "status": "queued"
    }


async def get_processing_status(job_id: str) -> Dict[str, Any]:
    """Get processing status for a job"""
    from app.core.redis_queue import RedisQueue
    
    queue = RedisQueue("ifc_processing_queue")
    return await queue.get_job_status(job_id)