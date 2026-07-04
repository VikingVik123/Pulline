from app.db.database import Base
from sqlalchemy import Column, String, DateTime, UUID, ForeignKey, JSON, Text, Integer, Float, Enum, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum


class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class IFCProject(Base):
    __tablename__ = "ifc_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(255), nullable=True)
    project_name = Column(String(255), nullable=True)
    ifc_version = Column(String(50), nullable=True)
    
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    
    total_floors = Column(Integer, default=0)
    total_elements = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationship to floors
    floors = relationship("IFCFloor", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_ifc_projects_user_id', 'user_id'),
        Index('ix_ifc_projects_status', 'status'),
    )


class IFCFloor(Base):
    __tablename__ = "ifc_floors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("ifc_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Floor identification
    floor_number = Column(Integer, nullable=False)
    floor_name = Column(String(255), nullable=True)
    elevation = Column(Float, nullable=True)
    element_count = Column(Integer, default=0)
    
    # Each floor has its own output files
    csv_url = Column(String(500), nullable=True)
    png_url = Column(String(500), nullable=True)
    svg_url = Column(String(500), nullable=True)
    dxf_url = Column(String(500), nullable=True)
    json_url = Column(String(500), nullable=True)
    
    # Each floor has its own status
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    project = relationship("IFCProject", back_populates="floors")

    __table_args__ = (
        Index('ix_ifc_floors_project_id', 'project_id'),
        Index('ix_ifc_floors_floor_number', 'project_id', unique=False),
    )