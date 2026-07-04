from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload

from app.modules.ifc_processing.models.ifc_model import IFCProject, IFCFloor, ProcessingStatus
from app.modules.ifc_processing.schemas.ifc_schemas import IFCUploadRequest
from app.modules.ifc_processing.services.ifc_extractor import IFCElementExtractor
from app.modules.ingest.models.model import Ingest
from app.core.redis_queue2 import RedisQueue  # ✅ Changed from redis_queue2 to redis_queue
from app.core.config import settings
import logging
import os
import re
import csv

logger = logging.getLogger(__name__)


class IFCProcessingService:
    """Main service for IFC processing"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.queue = RedisQueue("ifc_processing_queue")
        self.base_output_dir = Path("ifc_outputs")
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    def _find_file_by_id(self, file_id: UUID) -> Optional[Path]:
        """Find file by ID in the uploads folder"""
        # The file might be stored as {uuid}.ifc or with original name
        for ext in settings.ALLOWED_EXTENSIONS:
            file_path = self.upload_dir / f"{file_id}{ext}"
            if file_path.exists():
                return file_path
        
        # Also check if there's a file with this ID in the name pattern
        for file_path in self.upload_dir.glob("*"):
            if file_path.is_file() and str(file_id) in file_path.name:
                return file_path
        
        return None
    
    def _find_file_by_filename(self, filename: str) -> Optional[Path]:
        """Find file by original filename in the uploads folder"""
        # Try exact match first
        file_path = self.upload_dir / filename
        if file_path.exists():
            return file_path
        
        # Try case-insensitive match
        for f in self.upload_dir.iterdir():
            if f.is_file() and f.name.lower() == filename.lower():
                return f
        
        # Try partial match (file might have timestamp prefix)
        for f in self.upload_dir.iterdir():
            if f.is_file() and filename.lower() in f.name.lower():
                return f
        
        return None
    
    def _find_file(self, file_id: Optional[UUID] = None, filename: Optional[str] = None) -> Optional[Path]:
        """Find file by either ID or filename"""
        if file_id:
            return self._find_file_by_id(file_id)
        elif filename:
            return self._find_file_by_filename(filename)
        return None
    
    async def create_processing_task(
        self,
        user_id: UUID,
        request: IFCUploadRequest
    ) -> IFCProject:
        """Create a new IFC processing task"""
        
        # Try to find the file by ID or filename
        file_path = None
        file_record = None
        
        if request.file_id:
            # First try to find by ID in database
            stmt = select(Ingest).where(
                Ingest.id == request.file_id,
                Ingest.user_id == user_id
            )
            result = await self.db.execute(stmt)
            file_record = result.scalar_one_or_none()
            
            if file_record:
                # Try to find the physical file
                file_path = self._find_file_by_id(request.file_id)
                if not file_path:
                    # Try by filename from record
                    file_path = self._find_file_by_filename(file_record.filename)
        
        # If not found by ID, try by filename
        if not file_path and request.filename:
            file_path = self._find_file_by_filename(request.filename)
            
            # Also try to find the file record in database
            if not file_record:
                stmt = select(Ingest).where(
                    Ingest.filename == request.filename,
                    Ingest.user_id == user_id
                )
                result = await self.db.execute(stmt)
                file_record = result.scalar_one_or_none()
        
        # If still not found, check if file exists directly in uploads
        if not file_path and request.filename:
            # Try the exact path
            direct_path = self.upload_dir / request.filename
            if direct_path.exists():
                file_path = direct_path
        
        if not file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found. Please provide a valid file_id or filename. Available files in {self.upload_dir}: {[f.name for f in self.upload_dir.iterdir() if f.is_file()]}"
            )
        
        # Verify it's an IFC file
        if not file_path.suffix.lower() in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File must be an IFC file. Allowed extensions: {settings.ALLOWED_EXTENSIONS}"
            )
        
        # Use filename from record or from the file path
        display_name = file_record.filename if file_record else file_path.name
        
        # Create project record with filename field
        project = IFCProject(
            user_id=user_id,
            file_id=file_record.id if file_record else None,
            filename=display_name,  # ✅ Added filename field
            project_name=request.project_name or display_name,
            status=ProcessingStatus.PENDING
        )
        
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        
        # Queue for processing
        job_data = {
            "project_id": str(project.id),
            "user_id": str(user_id),
            "file_path": str(file_path),
            "file_id": str(file_record.id) if file_record else None,
            "filename": display_name,
            "project_name": request.project_name or display_name
        }
        
        # Try to enqueue with priority, fallback if not supported
        try:
            await self.queue.enqueue(job_data, priority=5)
        except TypeError:
            # Fallback if priority parameter is not supported
            await self.queue.enqueue(job_data)
        
        # Update status
        project.status = ProcessingStatus.PROCESSING
        await self.db.commit()
        
        return project
    
    async def process_ifc_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process an IFC job (called by worker)"""
        
        project_id = UUID(job_data['project_id'])
        user_id = UUID(job_data['user_id'])
        file_path = Path(job_data['file_path'])
        project_name = job_data.get('project_name')
        
        # Get project
        stmt = select(IFCProject).where(IFCProject.id == project_id)
        result = await self.db.execute(stmt)
        project = result.scalar_one_or_none()
        
        if not project:
            return {"status": "failed", "error": "Project not found"}
        
        try:
            # Update status
            project.status = ProcessingStatus.PROCESSING
            project.progress = 10
            await self.db.commit()
            
            # Create output directory for this project
            output_dir = self.base_output_dir / str(user_id) / str(project_id)
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
            output_files = extractor.run(storeys=None)  # Process all storeys
            
            # Create floor records
            base_url = f"/ifc-outputs/{user_id}/{project_id}"
            
            for storey_name, outputs in output_files.items():
                # Find floor number from storey name or assign sequential
                floor_number = self._extract_floor_number(storey_name, storey_names)
                
                # Count elements from CSV (if available)
                element_count = 0
                if outputs.get("csv"):
                    try:
                        with open(outputs["csv"], 'r') as f:
                            reader = csv.reader(f)
                            element_count = sum(1 for _ in reader) - 1  # Subtract header
                    except:
                        pass
                
                safe_name = self._safe_name(storey_name)
                
                floor = IFCFloor(
                    project_id=project.id,
                    floor_number=floor_number,
                    floor_name=storey_name,
                    elevation=0.0,  # Could extract from IFC
                    element_count=element_count,
                    status=ProcessingStatus.COMPLETED,
                    csv_url=f"{base_url}/{safe_name}/{safe_name}.csv" if outputs.get("csv") else None,
                    png_url=f"{base_url}/{safe_name}/{safe_name}.png" if outputs.get("png") else None,
                    svg_url=f"{base_url}/{safe_name}/{safe_name}.svg" if outputs.get("svg") else None,
                    dxf_url=f"{base_url}/{safe_name}/{safe_name}.dxf" if outputs.get("dxf") else None,
                    json_url=f"{base_url}/{safe_name}/{safe_name}.json" if outputs.get("json") else None,
                    processed_at=datetime.utcnow()
                )
                self.db.add(floor)
            
            # Update project
            project.status = ProcessingStatus.COMPLETED
            project.progress = 100
            project.total_floors = len(output_files)
            project.processed_at = datetime.utcnow()
            await self.db.commit()
            
            logger.info(f"IFC processing completed: {len(output_files)} floors")
            
            return {
                "status": "completed",
                "project_id": str(project.id),
                "total_floors": len(output_files)
            }
            
        except Exception as e:
            logger.error(f"IFC processing failed: {str(e)}", exc_info=True)
            project.status = ProcessingStatus.FAILED
            project.error_message = str(e)
            await self.db.commit()
            
            return {
                "status": "failed",
                "project_id": str(project.id),
                "error": str(e)
            }
    
    def _safe_name(self, name: str) -> str:
        """Sanitize name for URL/filename"""
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    
    def _extract_floor_number(self, storey_name: str, all_storeys: List[str]) -> int:
        """Extract floor number from storey name or assign sequential"""
        # Try to extract number from name (e.g., "Floor 1", "Level 2", "Ground Floor" -> 1)
        numbers = re.findall(r'\d+', storey_name)
        if numbers:
            return int(numbers[0])
        
        # If it's "Ground Floor" or similar, assign 1
        if "ground" in storey_name.lower() or "0" in storey_name or "g" in storey_name.lower():
            return 1
        
        # Assign sequential based on position in list
        try:
            return all_storeys.index(storey_name) + 1
        except ValueError:
            return len(all_storeys) + 1
    
    async def get_project(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> Optional[IFCProject]:
        """Get a project by ID with floors eagerly loaded"""
        stmt = select(IFCProject).where(
            IFCProject.id == project_id,
            IFCProject.user_id == user_id
        ).options(selectinload(IFCProject.floors))
        result = await self.db.execute(stmt)
        project = result.scalar_one_or_none()
        
        # Ensure filename is set if it's None
        if project and not project.filename:
            project.filename = project.project_name or "unknown.ifc"
        
        return project
    
    async def get_projects(
        self,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get projects for a user"""
        
        stmt = select(IFCProject).where(IFCProject.user_id == user_id)
        if status:
            stmt = stmt.where(IFCProject.status == status)
        
        # Get total count
        count_stmt = select(func.count()).select_from(IFCProject).where(IFCProject.user_id == user_id)
        if status:
            count_stmt = count_stmt.where(IFCProject.status == status)
        
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar()
        
        # Paginate
        stmt = stmt.order_by(desc(IFCProject.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        stmt = stmt.options(selectinload(IFCProject.floors))
        
        result = await self.db.execute(stmt)
        projects = result.scalars().all()
        
        # Ensure filename is set for all projects
        for project in projects:
            if not project.filename:
                project.filename = project.project_name or "unknown.ifc"
        
        return {
            "projects": projects,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    
    async def delete_project(self, project_id: UUID, user_id: UUID) -> bool:
        """Delete a project and its files"""
        
        project = await self.get_project(project_id, user_id)
        if not project:
            return False
        
        # Delete physical files
        try:
            import shutil
            project_folder = self.base_output_dir / str(user_id) / str(project_id)
            if project_folder.exists():
                shutil.rmtree(project_folder)
                logger.info(f"Deleted project folder: {project_folder}")
        except Exception as e:
            logger.error(f"Failed to delete project files: {e}")
        
        # Delete from database (cascade will delete floors)
        await self.db.delete(project)
        await self.db.commit()
        
        return True
    
    def get_file_path(self, file_url: str, user_id: UUID, project_id: UUID) -> Optional[Path]:
        """Get physical file path from URL"""
        # file_url: /ifc-outputs/{user_id}/{project_id}/floor_name/floor_name.svg
        relative_path = file_url.replace("/ifc-outputs/", "")
        file_path = self.base_output_dir / relative_path
        
        if file_path.exists():
            return file_path
        return None
    
    async def list_available_files(self, user_id: UUID) -> List[Dict[str, Any]]:
        """List all IFC files available for processing"""
        files = []
        
        # Get files from database
        stmt = select(Ingest).where(
            Ingest.user_id == user_id,
            Ingest.filetype.ilike('%ifc%')
        )
        result = await self.db.execute(stmt)
        db_files = result.scalars().all()
        
        for f in db_files:
            # Check if physical file exists
            file_path = self._find_file_by_id(f.id)
            if not file_path:
                file_path = self._find_file_by_filename(f.filename)
            
            files.append({
                "id": f.id,
                "filename": f.filename,
                "exists": file_path is not None,
                "path": str(file_path) if file_path else None,
                "uploaded_at": f.created_at
            })
        
        # Also check for files in uploads folder not in database
        for file_path in self.upload_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in settings.ALLOWED_EXTENSIONS:
                # Check if already in the list
                if not any(f["filename"] == file_path.name for f in files):
                    files.append({
                        "id": None,
                        "filename": file_path.name,
                        "exists": True,
                        "path": str(file_path),
                        "uploaded_at": datetime.fromtimestamp(file_path.stat().st_ctime)
                    })
        
        return files