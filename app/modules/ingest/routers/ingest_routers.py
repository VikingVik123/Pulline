from app.modules.ingest.models.ingest_model import Ingest
from app.modules.ingest.schemas.ingest_schema import (
    IngestRequest,
    FileResponse,
    FileDetailsResponse,
    FileDeleteResponse,
)
from app.modules.ingest.services.ingest_service import FileIngestService
from fastapi import APIRouter, Depends, UploadFile, Request
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.core import get_settings, get_logger
from app.core.exceptions import FileUploadError, NotFoundError, ValidationError
from urllib.parse import quote, unquote
from uuid import UUID
import os

router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()


@router.post("/files", response_model=FileResponse)
async def upload_file(
    file: UploadFile,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Upload a file for ingestion.
    
    Args:
        file: The file to upload
        request: The HTTP request object (for constructing absolute URL)
        db: Database session
        
    Returns:
        FileResponse: Information about the uploaded file
        
    Raises:
        ValidationError: If file format is invalid
        FileUploadError: If upload fails
    """
    service = FileIngestService(db)
    try:
        ingest_record: Ingest = await service.upload_file(file)
        logger.info(f"File uploaded successfully: {ingest_record.id}")
        # Construct absolute URL with scheme, host, and path
        base_url = str(request.base_url).rstrip("/")
        file_url = f"{base_url}/static/{quote(file.filename)}"
        return FileResponse(
            id=str(ingest_record.id),
            status=ingest_record.status,
            file_url=file_url,
        )
    except (ValidationError, FileUploadError):
        raise  # Re-raise custom exceptions to be handled by app exception handlers


@router.get("/files/list")
async def list_files(request: Request):
    """List all files in the upload directory.
    
    Args:
        request: The HTTP request object (for constructing absolute URLs)
    
    Returns:
        dict: List of files with metadata
    """
    try:
        if not os.path.exists(settings.UPLOAD_DIR):
            logger.debug("Upload directory does not exist")
            return {"files": []}

        base_url = str(request.base_url).rstrip("/")
        files = os.listdir(settings.UPLOAD_DIR)
        file_list = [
            {
                "name": file,
                "size": os.path.getsize(os.path.join(settings.UPLOAD_DIR, file)),
                "download_url": f"{base_url}/ingest/files/download/{quote(file)}",
            }
            for file in files
            if os.path.isfile(os.path.join(settings.UPLOAD_DIR, file))
        ]
        logger.debug(f"Listed {len(file_list)} files")
        return {"files": file_list}
    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        raise FileUploadError(f"Failed to list files: {str(e)}")


@router.get("/files/download/{file_name}")
async def download_file(file_name: str):
    """Download a file from the upload directory.
    
    Args:
        file_name: Name of the file to download (URL-encoded)
        
    Returns:
        FileResponse: The file to download
        
    Raises:
        ValidationError: If file path is invalid
        NotFoundError: If file does not exist
    """
    try:
        # Decode URL-encoded filename
        decoded_file_name = unquote(file_name)
        file_path = os.path.join(settings.UPLOAD_DIR, decoded_file_name)

        # Prevent directory traversal attacks
        if not os.path.abspath(file_path).startswith(
            os.path.abspath(settings.UPLOAD_DIR)
        ):
            logger.warning(f"Directory traversal attempt: {decoded_file_name}")
            raise ValidationError("Invalid file name")

        if not os.path.exists(file_path):
            logger.warning(f"File not found: {decoded_file_name}")
            raise NotFoundError(f"File not found", resource=decoded_file_name)

        logger.info(f"Downloading file: {decoded_file_name}")
        return FastAPIFileResponse(
            path=file_path,
            filename=decoded_file_name,
            media_type="application/octet-stream",
        )
    except (ValidationError, NotFoundError):
        raise  # Re-raise custom exceptions
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise FileUploadError(f"Failed to download file: {str(e)}")


@router.get("/files/{file_id}", response_model=FileDetailsResponse)
async def get_file_details(file_id: str, db: AsyncSession = Depends(get_db)):
    """Get details of a specific file by ID.
    
    Args:
        file_id: The ID of the file
        db: Database session
        
    Returns:
        FileDetailsResponse: File details including id, filename, status, size, created_at
        
    Raises:
        NotFoundError: If file not found
    """
    try:
        service = FileIngestService(db)
        file_record = await service.get_file_by_id(UUID(file_id))
        
        file_size = 0
        if os.path.exists(file_record.storage_path):
            file_size = os.path.getsize(file_record.storage_path)
        
        logger.info(f"Retrieved file details by ID: {file_id}")
        return FileDetailsResponse(
            id=str(file_record.id),
            filename=file_record.filename,
            filetype=file_record.filetype,
            status=file_record.status,
            size=file_size,
            created_at=file_record.created_at,
            storage_path=file_record.storage_path,
        )
    except NotFoundError:
        raise
    except ValueError as e:
        logger.warning(f"Invalid file ID format: {file_id}")
        raise ValidationError("Invalid file ID format")
    except Exception as e:
        logger.error(f"Failed to get file details: {e}")
        raise FileUploadError(f"Failed to get file details: {str(e)}")


@router.get("/files/by-name/{filename}", response_model=FileDetailsResponse)
async def get_file_by_name(filename: str, db: AsyncSession = Depends(get_db)):
    """Get details of a file by filename (URL-encoded).
    
    Args:
        filename: The filename to search for (URL-encoded)
        db: Database session
        
    Returns:
        FileDetailsResponse: File details including id, filename, status, size, created_at
        
    Raises:
        NotFoundError: If file not found
    """
    try:
        decoded_filename = unquote(filename)
        service = FileIngestService(db)
        file_record = await service.get_file_by_filename(decoded_filename)
        
        file_size = 0
        if os.path.exists(file_record.storage_path):
            file_size = os.path.getsize(file_record.storage_path)
        
        logger.info(f"Retrieved file details by filename: {decoded_filename}")
        return FileDetailsResponse(
            id=str(file_record.id),
            filename=file_record.filename,
            filetype=file_record.filetype,
            status=file_record.status,
            size=file_size,
            created_at=file_record.created_at,
            storage_path=file_record.storage_path,
        )
    except NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to get file by name: {e}")
        raise FileUploadError(f"Failed to get file details: {str(e)}")


@router.delete("/files/{file_id}", response_model=FileDeleteResponse)
async def delete_file(file_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a file by ID (removes from disk and database).
    
    Args:
        file_id: The ID of the file to delete
        db: Database session
        
    Returns:
        FileDeleteResponse: Deletion confirmation
        
    Raises:
        NotFoundError: If file not found
        FileUploadError: If deletion fails
    """
    try:
        service = FileIngestService(db)
        deleted = await service.delete_file(file_id=UUID(file_id))
        
        logger.info(f"File deleted successfully by ID: {file_id}")
        return FileDeleteResponse(
            message="File deleted successfully",
            file_id=file_id,
            deleted=deleted,
        )
    except (NotFoundError, FileUploadError):
        raise
    except ValueError as e:
        logger.warning(f"Invalid file ID format: {file_id}")
        raise ValidationError("Invalid file ID format")
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise FileUploadError(f"Failed to delete file: {str(e)}")


@router.delete("/files/by-name/{filename}", response_model=FileDeleteResponse)
async def delete_file_by_name(filename: str, db: AsyncSession = Depends(get_db)):
    """Delete a file by filename (removes from disk and database).
    
    Args:
        filename: The filename to delete (URL-encoded)
        db: Database session
        
    Returns:
        FileDeleteResponse: Deletion confirmation
        
    Raises:
        NotFoundError: If file not found
        FileUploadError: If deletion fails
    """
    try:
        decoded_filename = unquote(filename)
        service = FileIngestService(db)
        deleted = await service.delete_file(filename=decoded_filename)
        
        logger.info(f"File deleted successfully by filename: {decoded_filename}")
        return FileDeleteResponse(
            message="File deleted successfully",
            file_id=decoded_filename,
            deleted=deleted,
        )
    except (NotFoundError, FileUploadError):
        raise
    except Exception as e:
        logger.error(f"Failed to delete file by name: {e}")
        raise FileUploadError(f"Failed to delete file: {str(e)}")