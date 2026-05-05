"""Pydantic model + validator for the second-brain `raw/` frontmatter contract.

Required minimum (per /vault ingest):
    source_url, clipped_at, ingested: false

Optional fields are passthrough — preserved by /vault ingest as source-page
metadata. Per-integration extras (e.g. `youtube_video_id`) are also accepted
via `extra="allow"`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class Frontmatter(BaseModel):
    """Frontmatter contract for files newly written under `<vault>/raw/`."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    # Required minimum.
    source_url: str = Field(min_length=1)
    clipped_at: datetime
    ingested: Literal[False] = Field(
        default=False,
        description=(
            "Must be False on initial write. /vault ingest flips this to True "
            "after consuming the file. Setting True here is a contract violation."
        ),
    )

    # Optional but encouraged for ingest-direction plug-ins.
    source_kind: str | None = None
    title: str | None = None
    channel: str | None = None
    channel_url: str | None = None
    author: str | None = None
    published_at: date | datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript_source: str | None = None  # e.g. "captions", "whisper-base"
    language: str | None = None  # ISO 639-1
    tags: list[str] = Field(default_factory=list)

    # Vault-side ingest tracking — set by /vault ingest, never by ingester.
    ingested_at: datetime | None = None
    wiki_page: str | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v


def validate_frontmatter(d: dict) -> Frontmatter:
    """Validate a frontmatter dict and return the parsed model.

    Raises pydantic.ValidationError if required fields are missing or any
    field violates the contract.
    """
    return Frontmatter.model_validate(d)
