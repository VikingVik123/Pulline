from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from uuid import UUID
from pathlib import Path

from app.modules.ifc_processing.services.services import IFCProcessingService
from app.modules.ifc_processing.schemas.ifc_schemas import (
    IFCUploadRequest, IFCProjectResponse, IFCProjectListResponse,
    IFCFloorResponse, AvailableFileResponse
)
from app.tasks.ifc_tasks import get_processing_status
from app.db.database import get_db
from app.modules.auth.routers.auth_routes import get_current_user_from_token
from app.modules.auth.models.auth_model import User
from app.core.redis_queue import RedisQueue  # ✅ Changed from redis_queue2 to redis_queue

router = APIRouter(prefix="/ifc", tags=["ifc-processing"])


@router.get("/queue/stats")
async def get_queue_stats(
    current_user: User = Depends(get_current_user_from_token)
):
    """Get Redis queue statistics"""
    queue = RedisQueue("ifc_processing_queue")
    stats = await queue.get_queue_stats()
    return stats


@router.get("/queue/jobs")
async def get_pending_jobs(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user_from_token)
):
    """Get pending jobs in the queue"""
    queue = RedisQueue("ifc_processing_queue")
    jobs = await queue.get_pending_jobs(limit)
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/queue/job/{job_id}/status")
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user_from_token)
):
    """Get status of a specific job"""
    status = await get_processing_status(job_id)
    if not status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    return status


@router.get("/files/available", response_model=List[AvailableFileResponse])
async def list_available_ifc_files(
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """List all IFC files available for processing"""
    service = IFCProcessingService(db)
    return await service.list_available_files(current_user.id)


@router.post("/process", response_model=IFCProjectResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_ifc_file(
    request: IFCUploadRequest,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Start processing an IFC file.
    You can provide either:
    - file_id: ID of the uploaded file from the ingestion module
    - filename: Regular filename (will search in uploads folder)
    """
    service = IFCProcessingService(db)
    project = await service.create_processing_task(current_user.id, request)
    
    # Ensure filename is set for the response
    if not project.filename:
        project.filename = project.project_name or "unknown.ifc"
    
    # ✅ Don't check hasattr(project, 'floors') - that triggers lazy loading
    # Just set floors to an empty list since this is a new project
    # We need to bypass SQLAlchemy's lazy loading by using the attribute directly
    try:
        # Try to access floors, but if it's not loaded, use an empty list
        _ = project.floors
    except:
        # If it fails, set a placeholder
        pass
    
    # Create a response object manually to avoid lazy loading
    response_data = {
        "id": project.id,
        "filename": project.filename,
        "project_name": project.project_name,
        "ifc_version": project.ifc_version,
        "status": project.status,
        "progress": project.progress,
        "total_floors": 0,  # New project has no floors yet
        "total_elements": 0,
        "floors": [],  # Empty list for new project
        "created_at": project.created_at,
        "processed_at": project.processed_at,
        "error_message": project.error_message
    }
    
    return IFCProjectResponse.model_validate(response_data)


@router.get("/projects", response_model=IFCProjectListResponse)
async def list_projects(
    status: Optional[str] = Query(None, description="Filter by status: pending, processing, completed, failed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """List all IFC projects for the current user"""
    service = IFCProcessingService(db)
    result = await service.get_projects(
        user_id=current_user.id,
        status=status,
        page=page,
        page_size=page_size
    )
    
    # Get queue positions for pending/processing projects
    queue = RedisQueue("ifc_processing_queue")
    for project in result["projects"]:
        if project.status in ["pending", "processing"]:
            position = await queue.get_job_position(str(project.id))
            # You can add queue_position to response if needed
    
    return result


@router.get("/projects/{project_id}", response_model=IFCProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Get project details with all floors and their outputs"""
    service = IFCProcessingService(db)
    project = await service.get_project(project_id, current_user.id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Ensure filename is set for the response
    if not project.filename:
        project.filename = project.project_name or "unknown.ifc"
    
    return IFCProjectResponse.model_validate(project)


@router.get("/projects/{project_id}/floors", response_model=List[IFCFloorResponse])
async def get_floors(
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Get all floors for a project"""
    service = IFCProcessingService(db)
    project = await service.get_project(project_id, current_user.id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # ✅ Floors are eagerly loaded via selectinload in get_project
    return [IFCFloorResponse.model_validate(floor) for floor in project.floors]


@router.get("/projects/{project_id}/floors/{floor_number}", response_model=IFCFloorResponse)
async def get_floor(
    project_id: UUID,
    floor_number: int,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific floor with its output URLs"""
    service = IFCProcessingService(db)
    project = await service.get_project(project_id, current_user.id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    for floor in project.floors:
        if floor.floor_number == floor_number:
            return IFCFloorResponse.model_validate(floor)
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Floor {floor_number} not found"
    )


@router.get("/download/{project_id}/{floor_number}/{file_type}")
async def download_floor_output(
    project_id: UUID,
    floor_number: int,
    file_type: str,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Download a specific output file for a floor"""
    
    service = IFCProcessingService(db)
    project = await service.get_project(project_id, current_user.id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Find the floor
    floor = None
    for f in project.floors:
        if f.floor_number == floor_number:
            floor = f
            break
    
    if not floor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Floor {floor_number} not found"
        )
    
    # Get the URL based on file type
    url_map = {
        "csv": floor.csv_url,
        "png": floor.png_url,
        "svg": floor.svg_url,
        "dxf": floor.dxf_url,
        "json": floor.json_url
    }
    
    file_url = url_map.get(file_type.lower())
    if not file_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file_type}. Available: csv, png, svg, dxf, json"
        )
    
    # Get physical file path
    file_path = service.get_file_path(file_url, current_user.id, project_id)
    
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    media_types = {
        "csv": "text/csv",
        "png": "image/png",
        "svg": "image/svg+xml",
        "dxf": "application/dxf",
        "json": "application/json"
    }
    
    return FileResponse(
        path=file_path,
        filename=f"floor_{floor_number}.{file_type}",
        media_type=media_types.get(file_type.lower(), "application/octet-stream")
    )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Delete a project and all its floor files"""
    service = IFCProcessingService(db)
    deleted = await service.delete_project(project_id, current_user.id)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    return {"message": "Project deleted successfully", "success": True}


@router.get("/projects/{project_id}/status")
async def get_processing_status(
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Get processing status of a project"""
    service = IFCProcessingService(db)
    project = await service.get_project(project_id, current_user.id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Get queue position if pending
    queue = RedisQueue("ifc_processing_queue")
    queue_position = await queue.get_job_position(str(project_id))
    
    floor_status = []
    for floor in project.floors:
        floor_status.append({
            "floor_number": floor.floor_number,
            "floor_name": floor.floor_name,
            "status": floor.status,
            "has_csv": bool(floor.csv_url),
            "has_png": bool(floor.png_url),
            "has_svg": bool(floor.svg_url),
            "has_dxf": bool(floor.dxf_url),
            "has_json": bool(floor.json_url)
        })
    
    return {
        "project_id": project.id,
        "project_name": project.project_name,
        "status": project.status,
        "progress": project.progress,
        "total_floors": project.total_floors,
        "floors": floor_status,
        "queue_position": queue_position,
        "error_message": project.error_message,
        "created_at": project.created_at,
        "processed_at": project.processed_at
    }


@router.delete("/queue/job/{job_id}")
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user_from_token)
):
    """Cancel a queued or processing job"""
    queue = RedisQueue("ifc_processing_queue")
    cancelled = await queue.cancel_job(job_id)
    
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found or already processed"
        )
    
    return {"message": "Job cancelled successfully", "job_id": job_id}