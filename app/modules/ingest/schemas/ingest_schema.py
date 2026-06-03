from pydantic import BaseModel, Field
from fastapi import UploadFile
from typing import Optional
from datetime import datetime


class FileResponse(BaseModel):
    """Response when a file is uploaded."""
    id: str
    status: str
    file_url: Optional[str] = None


class FileDetailsResponse(BaseModel):
    """Response with detailed file information."""
    id: str
    filename: str
    filetype: Optional[str] = None
    status: str
    size: int
    created_at: Optional[datetime] = None
    storage_path: str

    class Config:
        from_attributes = True


class FileDeleteResponse(BaseModel):
    """Response when a file is deleted."""
    message: str
    file_id: str
    deleted: bool


class IngestRequest(BaseModel):
    file: UploadFile = Field(..., description="The file to be analyzed")