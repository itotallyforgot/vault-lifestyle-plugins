"""Pydantic model + validator for the second-brain `raw/` frontmatter contract.

Required minimum (per /vault ingest):
    source_url, clipped_at, ingested: false (all three required, not defaulted)

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

# Stock-validator-friendly ISO-8601 patterns. `format: date-time` is advisory
# under jsonschema's Draft202012Validator unless a FormatChecker is wired up,
# so siblings (Node, Go, etc.) get a pattern too.
_URL_PATTERN = r"^https?://"
_DATETIME_TZ_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
# Date-only OR full datetime with timezone. Used for fields where YouTube et al
# typically emit just a date, but a full timestamp is also acceptable.
_DATE_OR_DATETIME_PATTERN = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2}))?$"


class Frontmatter(BaseModel):
    """Frontmatter contract for files newly written under `<vault>/raw/`."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    # Required minimum.
    source_url: str = Field(
        min_length=1,
        pattern=_URL_PATTERN,
        description="Source URL. Must start with http:// or https://.",
    )
    clipped_at: datetime = Field(
        description="ISO-8601 timestamp WITH timezone (e.g., 2026-05-05T12:00:00Z).",
        json_schema_extra={"pattern": _DATETIME_TZ_PATTERN},
    )
    ingested: Literal[False] = Field(
        description=(
            "Must be explicitly set to False on initial write. /vault ingest "
            "flips this to True after consuming the file. Required, no default."
        ),
    )

    # Optional but encouraged for ingest-direction plug-ins.
    source_kind: str | None = None
    title: str | None = None
    channel: str | None = None
    channel_url: str | None = Field(
        default=None,
        pattern=_URL_PATTERN,
        description="Source channel/feed URL. Must start with http:// or https:// if present.",
    )
    author: str | None = None
    published_at: date | datetime | None = Field(
        default=None,
        json_schema_extra={"pattern": _DATE_OR_DATETIME_PATTERN},
    )
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript_source: str | None = None  # e.g. "captions", "whisper-base"
    language: str | None = None  # ISO 639-1
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Strict list of strings. None or bare-string inputs are rejected — "
            'Node siblings emitting `tags: "youtube"` (Obsidian shorthand) must '
            'wrap as `["youtube"]` to match the JSON schema.'
        ),
    )

    # Vault-side ingest tracking — set by /vault ingest, never by ingester.
    ingested_at: datetime | None = Field(
        default=None,
        json_schema_extra={"pattern": _DATETIME_TZ_PATTERN},
    )
    wiki_page: str | None = None

    @field_validator("clipped_at", "ingested_at")
    @classmethod
    def _require_tzinfo(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError(
                "datetime must include timezone (e.g., 'Z' or '+00:00'); naive "
                "timestamps are ambiguous across vaults"
            )
        return v


def validate_frontmatter(d: dict[str, Any]) -> Frontmatter:
    """Validate a frontmatter dict and return the parsed model.

    Raises pydantic.ValidationError if required fields are missing or any
    field violates the contract.
    """
    return Frontmatter.model_validate(d)
