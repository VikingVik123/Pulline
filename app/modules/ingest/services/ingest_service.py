from fastapi import UploadFile
from app.modules.ingest.models.ingest_model import Ingest
from app.db.database import AsyncSession
from app.core import get_settings, get_logger
from app.core.exceptions import FileUploadError, ValidationError, NotFoundError
from sqlalchemy import select
import os
from uuid import UUID

logger = get_logger(__name__)
settings = get_settings()


class FileIngestService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_dir = settings.UPLOAD_DIR
        self.allowed_extensions = settings.ALLOWED_EXTENSIONS

    async def file_exists(self, filename: str) -> bool:
        """Check if a file with the same filename already exists in the database.
        
        Args:
            filename: The filename to check
            
        Returns:
            bool: True if file exists, False otherwise
        """
        query = select(Ingest).where(Ingest.filename == filename).limit(1)
        result = await self.db.execute(query)
        return result.first() is not None

    async def get_file_by_id(self, file_id: UUID) -> Ingest:
        """Get a file record by ID.
        
        Args:
            file_id: The file ID
            
        Returns:
            Ingest: The file record
            
        Raises:
            NotFoundError: If file not found
        """
        query = select(Ingest).where(Ingest.id == file_id)
        result = await self.db.execute(query)
        file_record = result.scalar_one_or_none()
        
        if not file_record:
            logger.warning(f"File not found: {file_id}")
            raise NotFoundError(f"File not found", resource=str(file_id))
        
        return file_record

    async def get_file_by_filename(self, filename: str) -> Ingest:
        """Get a file record by filename.
        
        Args:
            filename: The filename to search for
            
        Returns:
            Ingest: The file record (returns first match if multiple exist)
            
        Raises:
            NotFoundError: If file not found
        """
        query = select(Ingest).where(Ingest.filename == filename).limit(1)
        result = await self.db.execute(query)
        file_record = result.first()
        
        if not file_record or not file_record[0]:
            logger.warning(f"File not found: {filename}")
            raise NotFoundError(f"File not found", resource=filename)
        
        return file_record[0]

    async def upload_file(self, file: UploadFile) -> Ingest:
        """Upload and store a file, then create a database record.
        
        Args:
            file: The uploaded file
            
        Returns:
            Ingest: The created ingest record
            
        Raises:
            ValidationError: If file extension is not allowed or duplicate exists
            FileUploadError: If file storage fails
        """
        logger.debug(f"Uploading file: {file.filename}")
        
        # Check if the file extension is allowed
        if not any(file.filename.endswith(ext) for ext in self.allowed_extensions):
            logger.warning(f"File type not allowed: {file.filename}")
            raise ValidationError(
                "File type not allowed",
                details={
                    "filename": file.filename,
                    "allowed_extensions": list(self.allowed_extensions),
                },
            )

        # Check for duplicate uploads
        if await self.file_exists(file.filename):
            logger.warning(f"Duplicate file upload attempted: {file.filename}")
            raise ValidationError(
                "File with this name already exists",
                details={"filename": file.filename},
            )

        try:
            # Create upload directory
            os.makedirs(self.file_dir, exist_ok=True)
            file_location = os.path.join(self.file_dir, file.filename)

            # Save file to disk
            with open(file_location, "wb") as f:
                content = await file.read()
                f.write(content)
            logger.info(f"File saved to disk: {file_location}")
        except IOError as e:
            logger.error(f"Failed to save file to disk: {e}")
            raise FileUploadError(
                f"Failed to save file: {str(e)}",
                filename=file.filename,
            )

        try:
            # Create DB record
            ingest_record = Ingest(
                filename=file.filename,
                filetype=file.content_type,
                storage_path=file_location,
                status="INGESTED",
            )
            self.db.add(ingest_record)
            await self.db.commit()
            await self.db.refresh(ingest_record)
            logger.info(f"Database record created: {ingest_record.id}")
            return ingest_record
        except Exception as e:
            logger.error(f"Failed to create database record: {e}")
            # Clean up uploaded file on database error
            try:
                os.remove(file_location)
            except:
                pass
            raise FileUploadError(
                f"Failed to save file metadata: {str(e)}",
                filename=file.filename,
            )

    async def delete_file(self, file_id: UUID = None, filename: str = None) -> bool:
        """Delete a file by ID or filename (removes from disk and database).
        
        Args:
            file_id: The file ID to delete (optional if filename provided)
            filename: The filename to delete (optional if file_id provided)
            
        Returns:
            bool: True if deleted successfully
            
        Raises:
            ValidationError: If neither file_id nor filename provided
            NotFoundError: If file not found
            FileUploadError: If deletion fails
        """
        if not file_id and not filename:
            raise ValidationError(
                "Either file_id or filename must be provided",
                details={"file_id": file_id, "filename": filename},
            )
        
        # Get file record
        if file_id:
            logger.debug(f"Deleting file by ID: {file_id}")
            file_record = await self.get_file_by_id(file_id)
        else:
            logger.debug(f"Deleting file by filename: {filename}")
            file_record = await self.get_file_by_filename(filename)
        
        # Delete from filesystem
        try:
            if os.path.exists(file_record.storage_path):
                os.remove(file_record.storage_path)
                logger.info(f"File deleted from disk: {file_record.storage_path}")
        except IOError as e:
            logger.error(f"Failed to delete file from disk: {e}")
            raise FileUploadError(
                f"Failed to delete file from disk: {str(e)}",
                filename=file_record.filename,
            )
        
        # Delete from database
        try:
            await self.db.delete(file_record)
            await self.db.commit()
            logger.info(f"Database record deleted: {file_record.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete database record: {e}")
            raise FileUploadError(
                f"Failed to delete file record: {str(e)}",
                filename=file_record.filename,
            )