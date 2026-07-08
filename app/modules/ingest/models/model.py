from app.db.database import Base
from sqlalchemy import Column, String, DateTime, UUID, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid


class Ingest(Base):
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False, index=True)
    filetype = Column(String, nullable=False)
    stored_filename = Column(String, nullable=True)
    status = Column(String, nullable=False)  # queued | processing | completed | failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="files")

    __table_args__ = (
        Index('ix_files_user_id', 'user_id'),
        Index('ix_files_status', 'status'),
        Index('ix_files_created_at', 'created_at'),
    )