"""Application settings, read from environment variables (prefix ``GEO_``)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("./data")
    database_url: str | None = None  # defaults to sqlite file inside data_dir
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB per upload
    max_unzipped_bytes: int = 500 * 1024 * 1024  # zip-bomb guard
    max_zip_members: int = 100
    allowed_extensions: tuple[str, ...] = field(default=(".zip", ".kml"))

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'geofiles.db').resolve()}"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("GEO_DATA_DIR", "./data")),
            database_url=os.getenv("GEO_DATABASE_URL"),
            max_upload_bytes=int(float(os.getenv("GEO_MAX_UPLOAD_MB", "50")) * 1024 * 1024),
            max_unzipped_bytes=int(float(os.getenv("GEO_MAX_UNZIPPED_MB", "500")) * 1024 * 1024),
            max_zip_members=int(os.getenv("GEO_MAX_ZIP_MEMBERS", "100")),
        )
