from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


class ProcessingStatus(str, Enum):
    """Processing status enum"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IFCUploadRequest(BaseModel):
    """Request to process an IFC file - can use either file_id or filename"""
    file_id: Optional[UUID] = Field(None, description="ID of the uploaded file")
    filename: Optional[str] = Field(None, description="Filename of the file (regular name)")
    project_name: Optional[str] = Field(None, max_length=255, description="Optional project name")
    
    def model_post_init(self, __context):
        """Validate that at least one identifier is provided"""
        if not self.file_id and not self.filename:
            raise ValueError("Either file_id or filename must be provided")


class AvailableFileResponse(BaseModel):
    """Response for available IFC files"""
    id: Optional[UUID] = Field(None, description="File ID if available in database")
    filename: str = Field(..., description="Filename")
    exists: bool = Field(..., description="Whether the file exists physically")
    path: Optional[str] = Field(None, description="Full path to the file")
    uploaded_at: Optional[datetime] = Field(None, description="When the file was uploaded")


class IFCFloorResponse(BaseModel):
    """Response for a single floor with all its output files"""
    id: UUID = Field(..., description="Floor record ID")
    floor_number: int = Field(..., description="Floor number (1, 2, 3, etc.)")
    floor_name: Optional[str] = Field(None, description="Name of the floor")
    elevation: Optional[float] = Field(None, description="Elevation in meters")
    element_count: int = Field(0, description="Number of elements on this floor")
    status: ProcessingStatus = Field(..., description="Processing status of this floor")
    
    # Each floor has its own output URLs
    csv_url: Optional[str] = Field(None, description="URL to CSV file")
    png_url: Optional[str] = Field(None, description="URL to PNG image")
    svg_url: Optional[str] = Field(None, description="URL to SVG file")
    dxf_url: Optional[str] = Field(None, description="URL to DXF file")
    json_url: Optional[str] = Field(None, description="URL to JSON data")
    
    processed_at: Optional[datetime] = Field(None, description="When this floor was processed")
    error_message: Optional[str] = Field(None, description="Error message if processing failed")
    
    class Config:
        from_attributes = True


class IFCProjectResponse(BaseModel):
    """Response for project with all floors"""
    id: UUID = Field(..., description="Project ID")
    filename: Optional[str] = Field(None, description="Original filename")
    project_name: Optional[str] = Field(None, description="Project name")
    ifc_version: Optional[str] = Field(None, description="IFC version")
    status: ProcessingStatus = Field(..., description="Overall project status")
    progress: int = Field(0, description="Processing progress (0-100)")
    total_floors: int = Field(0, description="Total number of floors")
    total_elements: int = Field(0, description="Total number of elements")
    
    # List of all floors with their outputs
    floors: Optional[List[IFCFloorResponse]] = Field(None, description="List of floors")
    
    created_at: datetime = Field(..., description="When the project was created")
    processed_at: Optional[datetime] = Field(None, description="When the project was processed")
    error_message: Optional[str] = Field(None, description="Error message if processing failed")
    
    class Config:
        from_attributes = True


class IFCProjectListResponse(BaseModel):
    """Response for listing IFC projects with pagination"""
    projects: List[IFCProjectResponse] = Field(..., description="List of projects")
    total: int = Field(..., description="Total number of projects")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(20, description="Number of items per page")


class FloorStatusResponse(BaseModel):
    """Individual floor status in status check"""
    floor_number: int = Field(..., description="Floor number")
    floor_name: Optional[str] = Field(None, description="Floor name")
    status: ProcessingStatus = Field(..., description="Floor processing status")
    has_csv: bool = Field(False, description="Whether CSV is available")
    has_png: bool = Field(False, description="Whether PNG is available")
    has_svg: bool = Field(False, description="Whether SVG is available")
    has_dxf: bool = Field(False, description="Whether DXF is available")
    has_json: bool = Field(False, description="Whether JSON is available")


class ProcessingStatusResponse(BaseModel):
    """Response for processing status of a project"""
    project_id: UUID = Field(..., description="Project ID")
    project_name: Optional[str] = Field(None, description="Project name")
    status: ProcessingStatus = Field(..., description="Overall project status")
    progress: int = Field(0, description="Processing progress (0-100)")
    total_floors: int = Field(0, description="Total number of floors")
    floors: List[FloorStatusResponse] = Field(default_factory=list, description="Status of each floor")
    queue_position: Optional[int] = Field(None, description="Position in the processing queue")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    created_at: datetime = Field(..., description="When the project was created")
    processed_at: Optional[datetime] = Field(None, description="When the project was processed")


class QueueStatsResponse(BaseModel):
    """Response for Redis queue statistics"""
    queue_name: str = Field(..., description="Name of the queue")
    pending: int = Field(0, description="Number of pending jobs")
    processing: int = Field(0, description="Number of jobs currently processing")
    completed: int = Field(0, description="Number of completed jobs")
    failed: int = Field(0, description="Number of failed jobs")
    total: int = Field(0, description="Total number of jobs")


class JobStatusResponse(BaseModel):
    """Response for a single job status"""
    job_id: str = Field(..., description="Job ID")
    status: str = Field(..., description="Current status: queued, processing, completed, failed")
    current_status: Optional[str] = Field(None, description="Detailed current status")
    enqueued_at: Optional[str] = Field(None, description="When the job was enqueued")
    dequeued_at: Optional[str] = Field(None, description="When the job was dequeued")
    completed_at: Optional[str] = Field(None, description="When the job was completed")
    failed_at: Optional[str] = Field(None, description="When the job failed")
    error: Optional[str] = Field(None, description="Error message if failed")
    result: Optional[dict] = Field(None, description="Result data if completed")
    retry_count: int = Field(0, description="Number of retries attempted")
    max_retries: int = Field(3, description="Maximum number of retries")


class DeleteProjectResponse(BaseModel):
    """Response for project deletion"""
    message: str = Field(..., description="Status message")
    success: bool = Field(..., description="Whether deletion was successful")
    project_id: UUID = Field(..., description="ID of the deleted project")


class CancelJobResponse(BaseModel):
    """Response for job cancellation"""
    message: str = Field(..., description="Status message")
    job_id: str = Field(..., description="ID of the cancelled job")


class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str = Field(..., description="Error message")
    status_code: Optional[int] = Field(None, description="HTTP status code")
    path: Optional[str] = Field(None, description="Request path")


# Re-export commonly used types
__all__ = [
    "ProcessingStatus",
    "IFCUploadRequest",
    "AvailableFileResponse",
    "IFCFloorResponse",
    "IFCProjectResponse",
    "IFCProjectListResponse",
    "FloorStatusResponse",
    "ProcessingStatusResponse",
    "QueueStatsResponse",
    "JobStatusResponse",
    "DeleteProjectResponse",
    "CancelJobResponse",
    "ErrorResponse"
]