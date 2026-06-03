from app.db.database import Base
from sqlalchemy import Column, Integer, String, DateTime, UUID, func  # type: ignore[reportMissingImports]
import uuid

class Ingest(Base):
    __tablename__ = "incoming_files"

    id: uuid.UUID = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True, nullable=False, primary_key=True)
    filename: str = Column(String, index=True, nullable=False)
    filetype: str = Column(String, nullable=True)
    storage_path: str = Column(String, nullable=True)
    status: str = Column(String, nullable=False)   # INGESTED | PROCESSING | FAILED | COMPLETED
    created_at: DateTime = Column(DateTime(timezone=True), server_default=func.now())