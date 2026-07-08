from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# =====================================================
# Requests
# =====================================================

class IFCUploadRequest(BaseModel):
    file_id: Optional[UUID] = None
    filename: Optional[str] = None
    project_name: Optional[str] = None

    def model_post_init(self, __context):
        if not self.file_id and not self.filename:
            raise ValueError(
                "Either file_id or filename must be provided."
            )


# =====================================================
# Misc
# =====================================================

class AvailableFileResponse(BaseModel):
    id: Optional[UUID]
    filename: str
    exists: bool
    path: Optional[str]
    uploaded_at: Optional[datetime]


# =====================================================
# Floor
# =====================================================

class IFCFloorResponse(BaseModel):
    id: UUID

    floor_number: int
    floor_name: Optional[str]
    elevation: Optional[float]

    element_count: int

    status: ProcessingStatus

    csv_url: Optional[str]
    png_url: Optional[str]
    svg_url: Optional[str]
    dxf_url: Optional[str]
    json_url: Optional[str]

    processed_at: Optional[datetime]
    error_message: Optional[str]

    class Config:
        from_attributes = True


# =====================================================
# Project Summary
# Used by GET /projects
# =====================================================

class IFCProjectSummaryResponse(BaseModel):
    id: UUID

    filename: Optional[str]
    project_name: Optional[str]

    status: ProcessingStatus
    progress: int

    total_floors: int
    total_elements: int

    created_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


# =====================================================
# Project Detail
# Used by GET /projects/{id}
# =====================================================

class IFCProjectDetailResponse(IFCProjectSummaryResponse):
    ifc_version: Optional[str]

    error_message: Optional[str]

    floors: List[IFCFloorResponse] = []


# =====================================================
# Project List
# =====================================================

class IFCProjectListResponse(BaseModel):
    projects: List[IFCProjectSummaryResponse]

    total: int
    page: int
    page_size: int


# =====================================================
# Status
# =====================================================

class FloorStatusResponse(BaseModel):
    floor_number: int
    floor_name: Optional[str]

    status: ProcessingStatus

    has_csv: bool
    csv_url: Optional[str] = None

    has_png: bool
    png_url: Optional[str] = None

    has_svg: bool
    svg_url: Optional[str] = None

    has_dxf: bool
    dxf_url: Optional[str] = None

    has_json: bool
    json_url: Optional[str] = None


class ProcessingStatusResponse(BaseModel):
    project_id: UUID

    project_name: Optional[str]

    status: ProcessingStatus
    progress: int

    total_floors: int

    floors: List[FloorStatusResponse] = Field(default_factory=list)

    queue_position: Optional[int] = None

    error_message: Optional[str]

    created_at: datetime
    processed_at: Optional[datetime]


# =====================================================
# Delete
# =====================================================

class DeleteProjectResponse(BaseModel):
    message: str
    success: bool
    project_id: UUID


class ProcessProjectResponse(BaseModel):
    message: str
    project_id: UUID
    status: ProcessingStatus
    queue_position: int | None = None