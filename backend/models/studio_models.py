from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class StudioProductionAsset(
    SQLModel,
    table=True,
):
    __tablename__ = "studio_production_asset"
    __table_args__ = (
        UniqueConstraint(
            "production_type",
            "source_id",
            "version_number",
            "asset_type",
            "language_code",
            name=(
                "uix_studio_asset_"
                "production_version_type_lang"
            ),
        ),
    )

    id: Optional[int] = Field(
        default=None,
        primary_key=True,
    )

    production_type: str = Field(index=True)
    source_id: int = Field(index=True)
    slug: str = Field(index=True)
    title: str

    version_number: int = Field(default=1)
    asset_type: str = Field(index=True)
    language_code: str = Field(index=True)

    filename: str
    local_path: Optional[str] = None

    storage_provider: str = Field(
        default="local_archive"
    )
    storage_bucket: Optional[str] = None
    storage_key: Optional[str] = None

    content_type: str
    file_size_bytes: int
    duration_seconds: Optional[float] = None
    sha256: str = Field(index=True)

    status: str = Field(default="complete")
    is_current: bool = Field(default=True)

    youtube_video_id: Optional[str] = None
    youtube_url: Optional[str] = None

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
