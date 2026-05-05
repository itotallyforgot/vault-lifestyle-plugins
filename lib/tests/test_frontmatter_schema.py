"""Tests for frontmatter_schema.Frontmatter + validate_frontmatter."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from frontmatter_schema import Frontmatter, validate_frontmatter


def _minimal_valid() -> dict:
    return {
        "source_url": "https://youtu.be/dQw4w9WgXcQ",
        "clipped_at": "2026-05-05T12:00:00Z",
        "ingested": False,
    }


# ---------- happy paths ----------


def test_minimal_valid_passes() -> None:
    fm = validate_frontmatter(_minimal_valid())
    assert fm.ingested is False
    assert fm.source_url == "https://youtu.be/dQw4w9WgXcQ"
    assert fm.clipped_at == datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
    assert fm.tags == []


def test_full_youtube_frontmatter_passes() -> None:
    d = {
        **_minimal_valid(),
        "source_kind": "youtube",
        "title": "Never Gonna Give You Up",
        "channel": "Rick Astley",
        "channel_url": "https://www.youtube.com/@RickAstleyYT",
        "published_at": "2009-10-25",
        "duration_seconds": 213,
        "transcript_source": "captions",
        "language": "en",
        "tags": ["youtube"],
    }
    fm = validate_frontmatter(d)
    assert fm.source_kind == "youtube"
    assert fm.duration_seconds == 213
    assert fm.tags == ["youtube"]
    assert isinstance(fm.published_at, date)


def test_unknown_extra_fields_pass_through() -> None:
    d = {**_minimal_valid(), "youtube_video_id": "dQw4w9WgXcQ", "custom_field": 42}
    fm = validate_frontmatter(d)
    dumped = fm.model_dump()
    assert dumped["youtube_video_id"] == "dQw4w9WgXcQ"
    assert dumped["custom_field"] == 42


def test_published_at_accepts_date_only() -> None:
    d = {**_minimal_valid(), "published_at": "2009-10-25"}
    fm = validate_frontmatter(d)
    assert fm.published_at == date(2009, 10, 25)


def test_published_at_preserves_datetime_when_time_is_set() -> None:
    """Pydantic smart-union picks `datetime` when sub-day precision is present."""
    d = {**_minimal_valid(), "published_at": "2009-10-25T12:34:56Z"}
    fm = validate_frontmatter(d)
    assert isinstance(fm.published_at, datetime)
    assert fm.published_at == datetime(2009, 10, 25, 12, 34, 56, tzinfo=UTC)


def test_zero_duration_accepted() -> None:
    d = {**_minimal_valid(), "duration_seconds": 0}
    fm = validate_frontmatter(d)
    assert fm.duration_seconds == 0


def test_clipped_at_with_offset_tz_accepted() -> None:
    d = {**_minimal_valid(), "clipped_at": "2026-05-05T12:00:00+05:30"}
    fm = validate_frontmatter(d)
    assert fm.clipped_at.tzinfo is not None


# ---------- failure modes — required fields ----------


def test_missing_source_url_fails() -> None:
    d = _minimal_valid()
    del d["source_url"]
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_missing_clipped_at_fails() -> None:
    d = _minimal_valid()
    del d["clipped_at"]
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_missing_ingested_fails() -> None:
    """ingested is required (no default) — must be explicit on write."""
    d = {k: v for k, v in _minimal_valid().items() if k != "ingested"}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


# ---------- failure modes — value validation ----------


def test_empty_source_url_fails() -> None:
    d = {**_minimal_valid(), "source_url": ""}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_non_http_source_url_fails() -> None:
    """source_url must be http(s)://. Junk strings are rejected."""
    d = {**_minimal_valid(), "source_url": "x"}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_ftp_source_url_fails() -> None:
    """Only http(s):// schemes are accepted."""
    d = {**_minimal_valid(), "source_url": "ftp://example.com/file"}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_non_http_channel_url_fails() -> None:
    d = {**_minimal_valid(), "channel_url": "not-a-url"}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_naive_clipped_at_rejected() -> None:
    """clipped_at without timezone is ambiguous across vaults."""
    d = {**_minimal_valid(), "clipped_at": "2026-05-05T12:00:00"}
    with pytest.raises(ValidationError, match="timezone"):
        validate_frontmatter(d)


def test_ingested_must_be_false_on_write() -> None:
    """Ingester output MUST set ingested: False. /vault ingest flips it later."""
    d = {**_minimal_valid(), "ingested": True}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_negative_duration_fails() -> None:
    d = {**_minimal_valid(), "duration_seconds": -1}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_invalid_clipped_at_fails() -> None:
    d = {**_minimal_valid(), "clipped_at": "not-a-date"}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


# ---------- tags: strict list (no coercion) ----------


def test_string_tags_rejected() -> None:
    """Bare-string tags rejected — siblings must emit `[\"x\"]` not `\"x\"`."""
    d = {**_minimal_valid(), "tags": "youtube"}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_none_tags_rejected() -> None:
    """Explicit None for tags rejected — omit the field instead."""
    d = {**_minimal_valid(), "tags": None}
    with pytest.raises(ValidationError):
        validate_frontmatter(d)


def test_omitted_tags_defaults_to_empty_list() -> None:
    """Omitting tags entirely defaults to []."""
    fm = validate_frontmatter(_minimal_valid())
    assert fm.tags == []


# ---------- JSON Schema export ----------


def test_json_schema_exposes_required_fields() -> None:
    schema = Frontmatter.model_json_schema()
    assert "source_url" in schema["properties"]
    assert "clipped_at" in schema["properties"]
    assert "ingested" in schema["properties"]
    # All three minimums are required (no Pydantic-side defaults to mask them).
    assert set(schema["required"]) >= {"source_url", "clipped_at", "ingested"}


def test_json_schema_marks_extras_allowed() -> None:
    schema = Frontmatter.model_json_schema()
    # Pydantic v2 with extra="allow" sets additionalProperties to True.
    assert schema.get("additionalProperties") is True


def test_json_schema_includes_url_pattern() -> None:
    schema = Frontmatter.model_json_schema()
    src = schema["properties"]["source_url"]
    assert "pattern" in src
    assert src["pattern"].startswith("^https?")


def test_json_schema_includes_datetime_pattern() -> None:
    schema = Frontmatter.model_json_schema()
    clipped = schema["properties"]["clipped_at"]
    assert "pattern" in clipped
    # Pattern requires timezone suffix at the end.
    assert "Z" in clipped["pattern"]
