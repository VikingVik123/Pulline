from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db

from app.modules.auth.models.auth_model import User
from app.modules.auth.routers.auth_routes import (
    get_current_user_from_token,
)

from app.modules.ingest.models.model import Ingest

from app.modules.ifc_processing.models.ifc_model import (
    IFCProject,
)

from app.modules.ifc_processing.schemas.ifc_schemas import (
    IFCUploadRequest,
    IFCProjectSummaryResponse,
    IFCProjectDetailResponse,
    IFCProjectListResponse,
    ProcessingStatusResponse,
    DeleteProjectResponse,
    ProcessingStatus,
    ProcessProjectResponse
)

from app.modules.ifc_processing.services.services import (
    IFCProcessingService,
)

from app.core.redis_config import RedisService

redis = RedisService()

def build_file_url(
    request: Request,
    path: str | None,
) -> str | None:

    if not path:
        return None

    return str(
        request.url_for(
            "ifc_output",
            path=path,
        )
    )

router = APIRouter(
    prefix="/ifc",
    tags=["IFC Processing"],
)


# -------------------------------------------------------
# Create project
# -------------------------------------------------------

@router.post(
    "/projects",
    response_model=IFCProjectSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    payload: IFCUploadRequest,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):

    ingest = await db.get(Ingest, payload.file_id)

    if ingest is None:
        raise HTTPException(
            status_code=404,
            detail="Uploaded file not found.",
        )

    if ingest.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You do not own this file.",
        )

    project = IFCProject(
        user_id=current_user.id,
        file_id=ingest.id,
        filename=ingest.filename,
        project_name=payload.project_name,
    )

    db.add(project)

    await db.commit()
    await db.refresh(project)

    return project


# -------------------------------------------------------
# Process project
# -------------------------------------------------------

@router.post(
    "/projects/{project_id}/process",
    response_model=ProcessProjectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_project(
    request: Request,
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):

    project = await db.get(IFCProject, project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )
    if project.status == ProcessingStatus.PROCESSING:
        raise HTTPException(
            status_code=409,
            detail="Project already processing"
        )

    if project.status == ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="Project already processed"
        )

    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Forbidden.",
        )

    # update DB
    project.status = ProcessingStatus.PENDING
    project.progress = 0

    await db.commit()
    await db.refresh(project)

    # enqueue
    await redis.enqueue_project(project.id)

    position = await redis.queue_position(project.id)

    return ProcessProjectResponse(
        message="Project queued successfully.",
        project_id=project.id,
        status=project.status,
        queue_position=position,
    )
"""
    service = IFCProcessingService(db)

    await service.process_project(project.id)

    stmt = (
        select(IFCProject)
        .options(selectinload(IFCProject.floors))
        .where(IFCProject.id == project.id)
    )

    result = await db.execute(stmt)

    project = result.scalar_one()
    for floor in project.floors:
        floor.csv_url = build_file_url(request, floor.csv_url)
        floor.png_url = build_file_url(request, floor.png_url)
        floor.svg_url = build_file_url(request, floor.svg_url)
        floor.dxf_url = build_file_url(request, floor.dxf_url)
        floor.json_url = build_file_url(request, floor.json_url)

    return project
"""

# -------------------------------------------------------
# List projects (NO FLOORS)
# -------------------------------------------------------

@router.get(
    "/projects",
    response_model=IFCProjectListResponse,
)
async def list_projects(
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):

    stmt = (
        select(IFCProject)
        .where(IFCProject.user_id == current_user.id)
        .order_by(IFCProject.created_at.desc())
    )

    result = await db.execute(stmt)

    projects = result.scalars().all()

    return IFCProjectListResponse(
        projects=projects,
        total=len(projects),
        page=1,
        page_size=len(projects),
    )


# -------------------------------------------------------
# Processing status
# -------------------------------------------------------

@router.get(
    "/projects/{project_id}/status",
    response_model=ProcessingStatusResponse,
)
async def project_status(
    request: Request,
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):

    stmt = (
        select(IFCProject)
        .options(selectinload(IFCProject.floors))
        .where(
            IFCProject.id == project_id,
            IFCProject.user_id == current_user.id,
        )
    )

    result = await db.execute(stmt)

    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    return ProcessingStatusResponse(
        project_id=project.id,
        project_name=project.project_name,
        status=project.status,
        progress=project.progress,
        total_floors=project.total_floors,
        created_at=project.created_at,
        processed_at=project.processed_at,
        error_message=project.error_message,
        floors=[
            {
                "floor_number": floor.floor_number,
                "floor_name": floor.floor_name,
                "status": floor.status,

                "has_csv": floor.csv_url is not None,
                "csv_url": build_file_url(request, floor.csv_url),

                "has_png": floor.png_url is not None,
                "png_url": build_file_url(request, floor.png_url),

                "has_svg": floor.svg_url is not None,
                "svg_url": build_file_url(request, floor.svg_url),

                "has_dxf": floor.dxf_url is not None,
                "dxf_url": build_file_url(request, floor.dxf_url),

                "has_json": floor.json_url is not None,
                "json_url": build_file_url(request, floor.json_url),
            }
            for floor in project.floors
        ],
    )


# -------------------------------------------------------
# Get single project (WITH FLOORS)
# -------------------------------------------------------

@router.get(
    "/projects/{project_id}",
    response_model=IFCProjectDetailResponse,
)
async def get_project(
    request: Request,
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):

    stmt = (
        select(IFCProject)
        .options(selectinload(IFCProject.floors))
        .where(
            IFCProject.id == project_id,
            IFCProject.user_id == current_user.id,
        )
    )

    result = await db.execute(stmt)

    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    for floor in project.floors:
        floor.csv_url = build_file_url(request, floor.csv_url)
        floor.png_url = build_file_url(request, floor.png_url)
        floor.svg_url = build_file_url(request, floor.svg_url)
        floor.dxf_url = build_file_url(request, floor.dxf_url)
        floor.json_url = build_file_url(request, floor.json_url)

    return project


# -------------------------------------------------------
# Delete project
# -------------------------------------------------------

@router.delete(
    "/projects/{project_id}",
    response_model=DeleteProjectResponse,
)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):

    project = await db.get(IFCProject, project_id)

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Forbidden.",
        )

    await db.delete(project)
    await db.commit()

    return DeleteProjectResponse(
        message="Project deleted.",
        success=True,
        project_id=project_id,
    )