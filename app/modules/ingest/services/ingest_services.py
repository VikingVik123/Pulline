import os
import shutil
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from uuid import UUID

from app.modules.ingest.models.model import Ingest
from app.modules.ingest.schemas.ingest_schema import (
    IngestRequest, IngestResponse, FileDetailsResponse,
    FileDeleteResponse, FileListResponse
)
from app.core.config import settings
from app.core.redis_queue import RedisQueue


class IngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
        self.queue = RedisQueue("file_queue")
        self._ensure_upload_dir()

    def _ensure_upload_dir(self):
        """Ensure upload directory exists"""
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def upload_file(
        self,
        file: UploadFile,
        request: IngestRequest,
        user_id: UUID  # Add user_id parameter
    ) -> tuple[Ingest, str]:
        """
        Upload a file - saves file and queues it for background processing
        Returns the file record and the safe filename
        """
        
        # Generate safe filename with timestamp to avoid conflicts
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = self.upload_dir / safe_filename
        
        # Get file size
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        # Validate file size (default 50MB)
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 50 * 1024 * 1024)
        if file_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Max size: {max_size / (1024*1024):.0f}MB"
            )
        
        # Save file
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file: {str(e)}"
            )
        
        # Create database record with user_id
        new_file = Ingest(
            user_id=user_id,  # Add user_id
            filename=file.filename,
            filetype=request.filetype or file.content_type or "application/octet-stream",
            url=safe_filename,
            status="queued"
        )
        
        self.db.add(new_file)
        await self.db.commit()
        await self.db.refresh(new_file)
        
        # Add to Redis queue for background processing
        job_data = {
            "file_id": str(new_file.id),
            "user_id": str(user_id),
            "file_path": str(file_path)
        }
        
        await self.queue.enqueue(job_data)
        
        return new_file, safe_filename

    async def process_file_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a file job (called by worker)"""
        file_id = job_data.get('file_id')
        if not file_id:
            return {"status": "failed", "error": "No file_id in job"}
        
        stmt = select(Ingest).where(Ingest.id == UUID(file_id))
        result = await self.db.execute(stmt)
        file = result.scalar_one_or_none()
        
        if not file:
            return {"status": "failed", "error": "File not found"}
        
        try:
            file.status = "completed"
            await self.db.commit()
            
            job_id = job_data.get('job_id')
            if job_id:
                await self.queue.delete_job(job_id)
            
            return {
                "status": "completed",
                "file_id": file_id,
                "user_id": str(file.user_id),
                "message": "File processed successfully"
            }
            
        except Exception as e:
            file.status = "failed"
            await self.db.commit()
            
            return {
                "status": "failed",
                "file_id": file_id,
                "error": str(e)
            }

    async def get_file(self, file_id: UUID, user_id: UUID) -> Optional[Ingest]:
        """Get a file by ID (with user validation)"""
        stmt = select(Ingest).where(
            Ingest.id == file_id,
            Ingest.user_id == user_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_files(
        self,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get files for a specific user with pagination"""
        
        stmt = select(Ingest).where(Ingest.user_id == user_id)
        if status:
            stmt = stmt.where(Ingest.status == status)
        
        # Get total count
        count_stmt = select(func.count()).select_from(Ingest).where(Ingest.user_id == user_id)
        if status:
            count_stmt = count_stmt.where(Ingest.status == status)
        
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar()
        
        # Paginate
        stmt = stmt.order_by(desc(Ingest.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.db.execute(stmt)
        files = result.scalars().all()
        
        return {
            "files": files,
            "total": total,
            "page": page,
            "page_size": page_size
        }

    async def delete_file(self, file_id: UUID, user_id: UUID) -> FileDeleteResponse:
        """Delete a file (with user validation)"""
        file = await self.get_file(file_id, user_id)
        if not file:
            return FileDeleteResponse(
                message="File not found",
                file_id=file_id,
                deleted=False
            )
        
        # Delete physical file
        if file.url:
            file_path = self.upload_dir / file.url
            if file_path.exists():
                file_path.unlink()
        
        await self.db.delete(file)
        await self.db.commit()
        
        return FileDeleteResponse(
            message="File deleted successfully",
            file_id=file_id,
            deleted=True
        )