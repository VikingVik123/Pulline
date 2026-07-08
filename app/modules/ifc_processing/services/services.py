from pathlib import Path
from typing import Optional
from uuid import UUID
from datetime import datetime
import logging
import re

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.ingest.models.model import Ingest
from app.modules.ifc_processing.models.ifc_model import (
    IFCProject,
    IFCFloor,
    ProcessingStatus,
)
from app.modules.ifc_processing.services.ext import IFCElementExtractor

logger = logging.getLogger(__name__)


class IFCProcessingService:

    def __init__(self, db: AsyncSession):
        self.db = db

        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.output_root = Path("ifc_outputs")

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------
    # Database helpers
    # ----------------------------------------------------

    async def _get_project(
        self,
        project_id: UUID,
    ) -> IFCProject:

        stmt = (
            select(IFCProject)
            .where(IFCProject.id == project_id)
        )

        result = await self.db.execute(stmt)

        project = result.scalar_one_or_none()

        if project is None:
            raise ValueError("Project not found.")

        return project

    async def _get_ingest(
        self,
        file_id: UUID,
    ) -> Ingest:

        stmt = (
            select(Ingest)
            .where(Ingest.id == file_id)
        )

        result = await self.db.execute(stmt)

        ingest = result.scalar_one_or_none()

        if ingest is None:
            raise ValueError("Uploaded IFC file not found.")

        return ingest

    # ----------------------------------------------------
    # Filesystem helpers
    # ----------------------------------------------------

    def _get_ifc_path(
        self,
        ingest: Ingest,
    ) -> Path:

        path = self.upload_dir / ingest.stored_filename

        if not path.exists():
            raise FileNotFoundError(path)

        return path

    def _safe_name(
        self,
        value: str,
    ) -> str:

        value = Path(value).stem
        value = re.sub(r"[^\w\-]", "_", value)
        return re.sub(r"_+", "_", value).strip("_")

    def _create_output_directory(
        self,
        project: IFCProject,
    ) -> Path:

        path = (
            self.output_root
            / str(project.user_id)
            / str(project.id)
        )

        path.mkdir(parents=True, exist_ok=True)

        return path

    def _relative_path(
        self,
        path: Optional[str],
    ) -> Optional[str]:

        if path is None:
            return None

        return str(
            Path(path).relative_to(self.output_root)
        ).replace("\\", "/")

    # ----------------------------------------------------
    # Processing
    # ----------------------------------------------------

    async def process_project(
        self,
        project_id: UUID,
    ) -> IFCProject:

        project = await self._get_project(project_id)

        ingest = await self._get_ingest(project.file_id)

        project.status = ProcessingStatus.PROCESSING
        project.progress = 5

        await self.db.commit()

        try:

            ifc_path = self._get_ifc_path(ingest)

            output_dir = self._create_output_directory(project)

            extractor = IFCElementExtractor(
                ifc_path=str(ifc_path),
                output_dir=str(output_dir),
            )

            outputs = extractor.run()

            await self.db.execute(
                delete(IFCFloor)
                .where(IFCFloor.project_id == project.id)
            )

            floor_number = 1

            for floor_name, data in outputs.items():

                floor = IFCFloor(
                    project_id=project.id,
                    floor_number=floor_number,
                    floor_name=floor_name,
                    element_count=data["segment_count"],

                    csv_url=self._relative_path(data["csv"]),
                    svg_url=self._relative_path(data["svg"]),
                    png_url=self._relative_path(data["png"]),
                    dxf_url=self._relative_path(data["dxf"]),

                    status=ProcessingStatus.COMPLETED,
                    processed_at=datetime.utcnow(),
                )

                self.db.add(floor)

                floor_number += 1

            project.total_floors = len(outputs)
            project.filename = ingest.filename
            project.progress = 100
            project.status = ProcessingStatus.COMPLETED
            project.processed_at = datetime.utcnow()

            await self.db.commit()
            await self.db.refresh(project)

            return project

        except Exception as e:

            logger.exception(e)

            project.status = ProcessingStatus.FAILED
            project.error_message = str(e)

            await self.db.commit()

            raise