from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pathlib import Path
from uuid import UUID

from app.modules.ingest.services.ingest_services import IngestionService
from app.modules.ingest.schemas.ingest_schema import (
    IngestRequest, IngestResponse, FileDetailsResponse,
    FileDeleteResponse, FileListResponse
)
from app.db.database import get_db
from app.core.config import settings
from app.modules.auth.routers.auth_routes import get_current_user_from_token
from app.modules.auth.models.auth_model import User
from app.core.auth_dependencies import (
    get_verified_user
)
router = APIRouter(prefix="/ingestion", tags=["file-ingestion"])


@router.post("/upload", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    filetype: Optional[str] = None,
    current_user: User = Depends(get_verified_user),  # Auth required
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a file - returns immediately, processing happens in background
    Authentication required.
    """
    service = IngestionService(db)
    
    ingest_request = IngestRequest(
        filename=file.filename,
        filetype=filetype or file.content_type or "application/octet-stream"
    )
    
    # Service returns file record and filename with user_id
    file_record, safe_filename = await service.upload_file(
        file=file,
        request=ingest_request,
        user_id=current_user.id  # Pass the authenticated user's ID
    )
    
    # Construct full URL in the router
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    file_url = f"{base_url}/uploads/{safe_filename}"
    
    return IngestResponse(
        id=file_record.id,
        user_id=file_record.user_id,
        status=file_record.status,
        file_url=file_url,
        message="File uploaded and queued for processing"
    )


@router.get("/files", response_model=FileListResponse)
async def list_files(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status: queued, processing, completed, failed"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_verified_user),  # Auth required
    db: AsyncSession = Depends(get_db)
):
    """
    List all uploaded files for the current user with pagination
    Authentication required.
    """
    service = IngestionService(db)
    result = await service.get_files(
        user_id=current_user.id,  # Only get files for the current user
        status=status,
        page=page,
        page_size=page_size
    )
    
    # Construct full URLs in the router
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    items = []
    for file in result["files"]:
        items.append(FileDetailsResponse(
            id=file.id,
            user_id=file.user_id,
            filename=file.filename,
            filetype=file.filetype,
            status=file.status,
            created_at=file.created_at,
            url=f"{base_url}/uploads/{file.stored_filename}" if file.stored_filename else ""
        ))
    
    return {
        "files": items,
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"]
    }


@router.get("/files/{file_id}", response_model=FileDetailsResponse)
async def get_file(
    request: Request,
    file_id: str,
    current_user: User = Depends(get_verified_user),  # Auth required
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about a specific file (user must own the file)
    Authentication required.
    """
    service = IngestionService(db)
    file = await service.get_file(UUID(file_id), current_user.id)
    
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Construct full URL in the router
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    
    return FileDetailsResponse(
        id=file.id,
        user_id=file.user_id,
        filename=file.filename,
        filetype=file.filetype,
        status=file.status,
        created_at=file.created_at,
        url=f"{base_url}/uploads/{file.stored_filename}" if file.stored_filename else ""
    )


@router.delete("/files/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    current_user: User = Depends(get_verified_user),  # Auth required
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a file from both database and filesystem (user must own the file)
    Authentication required.
    """
    service = IngestionService(db)
    result = await service.delete_file(UUID(file_id), current_user.id)
    
    if not result.deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.message
        )
    
    return result


@router.get("/download/{file_id}")
async def download_file(
    file_id: str,
    current_user: User = Depends(get_verified_user),  # Auth required
    db: AsyncSession = Depends(get_db)
):
    """
    Download a file by its ID (user must own the file)
    Authentication required.
    """
    service = IngestionService(db)
    file = await service.get_file(UUID(file_id), current_user.id)
    
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    if not (stored_filename := file.stored_filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File URL not found"
        )
    
    upload_dir = Path(settings.UPLOAD_DIR) if hasattr(settings, 'UPLOAD_DIR') else Path("./uploads")
    file_path = upload_dir / stored_filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server"
        )
    
    return FileResponse(
        path=file_path,
        filename=file.filename,
        media_type=file.filetype
    )


@router.get("/queue/stats")
async def get_queue_stats(
    current_user: User = Depends(get_verified_user),  # Auth required
    db: AsyncSession = Depends(get_db)
):
    """
    Get current Redis queue statistics
    Authentication required.
    """
    service = IngestionService(db)
    queue_length = await service.queue.get_queue_length()
    
    return {
        "queue_name": "file_queue",
        "pending_jobs": queue_length,
        "status": "healthy" if queue_length < 1000 else "backlog"
    }