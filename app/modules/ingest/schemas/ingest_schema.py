from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class IngestRequest(BaseModel):
    filename: str
    filetype: str


class IngestResponse(BaseModel):
    id: UUID
    user_id: UUID
    status: str
    file_url: Optional[str] = None
    message: Optional[str] = None


class FileDetailsResponse(BaseModel):
    id: UUID
    user_id: UUID
    filename: str
    filetype: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    url: str


class FileDeleteResponse(BaseModel):
    message: str
    file_id: UUID
    deleted: bool


class FileListResponse(BaseModel):
    files: list[FileDetailsResponse]
    total: int
    page: int
    page_size: int