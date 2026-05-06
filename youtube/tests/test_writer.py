"""Tests for vault_yt.writer.build_raw_md and write."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from frontmatter_schema import validate_frontmatter

from vault_yt.writer import (
    WriterError,
    build_raw_md,
    write,
)

# ---------- fixtures ----------


def _meta(**overrides) -> dict:
    base = {
        "id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "channel": "Rick Astley",
        "channel_url": "https://www.youtube.com/@RickAstleyYT",
        "published_at": date(2009, 10, 25),
        "duration_seconds": 213,
        "captions": ["en"],
    }
    base.update(overrides)
    return base


# ---------- build_raw_md ----------


def test_output_starts_with_frontmatter_fence() -> None:
    md = build_raw_md(_meta(), "Hello world.", transcript_source="yt-dlp")
    assert md.startswith("---\n")
    # Closing fence then blank then body.
    assert "\n---\n\n" in md


def test_output_includes_required_minimum_fields() -> None:
    md = build_raw_md(_meta(), "Hello world.", transcript_source="yt-dlp")
    assert "source_url:" in md
    assert "clipped_at:" in md
    assert "ingested: false" in md


def test_source_url_uses_short_youtu_be_form() -> None:
    md = build_raw_md(_meta(id="dQw4w9WgXcQ"), "body", transcript_source="yt-dlp")
    assert "source_url: https://youtu.be/dQw4w9WgXcQ" in md


def test_clipped_at_is_iso8601_utc_with_z_suffix() -> None:
    """clipped_at must satisfy the schema's tz-required ISO8601 pattern."""
    md = build_raw_md(_meta(), "body", transcript_source="yt-dlp")
    fm = _parse_frontmatter(md)
    # Schema's pattern is r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
    import re

    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$",
        fm["clipped_at"],
    )


def test_published_at_serialized_as_yyyy_mm_dd() -> None:
    md = build_raw_md(
        _meta(published_at=date(2009, 10, 25)),
        "body",
        transcript_source="yt-dlp",
    )
    assert "published_at: 2009-10-25" in md


def test_optional_fields_emitted_when_present() -> None:
    md = build_raw_md(_meta(), "body", transcript_source="yt-dlp")
    assert "title: Never Gonna Give You Up" in md
    assert "source_kind: youtube" in md
    assert "channel: Rick Astley" in md
    assert "duration_seconds: 213" in md
    assert "transcript_source: yt-dlp" in md
    assert "tags:" in md
    assert "- youtube" in md


def test_optional_fields_omitted_or_null_when_absent() -> None:
    """Channel + published_at None should not crash; fields nulled or omitted."""
    md = build_raw_md(
        _meta(channel=None, channel_url=None, published_at=None, duration_seconds=None),
        "body",
        transcript_source="yt-dlp",
    )
    # Body still present.
    assert "\n---\n\nbody" in md


def test_body_appears_after_frontmatter_fence() -> None:
    md = build_raw_md(_meta(), "This is the transcript.", transcript_source="yt-dlp")
    fence_close_idx = md.index("\n---\n", 4)  # second --- (closing fence)
    body_part = md[fence_close_idx + len("\n---\n") :].lstrip("\n")
    assert body_part.startswith("This is the transcript.")


def test_output_validates_against_frontmatter_schema() -> None:
    """Round-trip: parse our output's frontmatter, validate against Pydantic."""
    md = build_raw_md(_meta(), "body", transcript_source="yt-dlp")
    fm = _parse_frontmatter(md)
    # validate_frontmatter raises on contract violations.
    validate_frontmatter(fm)


def test_whisper_transcript_source_accepted() -> None:
    md = build_raw_md(_meta(), "body", transcript_source="whisper-base")
    assert "transcript_source: whisper-base" in md


def test_whisper_tiny_transcript_source_accepted() -> None:
    md = build_raw_md(_meta(), "body", transcript_source="whisper-tiny")
    assert "transcript_source: whisper-tiny" in md


def test_invalid_transcript_source_rejected() -> None:
    with pytest.raises((ValueError, WriterError)):
        build_raw_md(_meta(), "body", transcript_source="not-a-real-source")


def test_missing_required_meta_field_raises() -> None:
    bad = _meta()
    del bad["id"]
    with pytest.raises((KeyError, WriterError)):
        build_raw_md(bad, "body", transcript_source="yt-dlp")


def test_yaml_serialization_is_stable() -> None:
    """Same inputs → byte-identical output (no key reordering, no timestamp drift)."""
    # Pin clipped_at by patching now() — done via build_raw_md's clipped_at_now arg.
    fixed_now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
    a = build_raw_md(_meta(), "body", transcript_source="yt-dlp", clipped_at=fixed_now)
    b = build_raw_md(_meta(), "body", transcript_source="yt-dlp", clipped_at=fixed_now)
    assert a == b


# ---------- write ----------


def test_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "raw" / "abc-test.md"
    target.parent.mkdir()
    result = write(target, "hello\n")
    assert result == target
    assert target.read_text() == "hello\n"


def test_write_is_idempotent_when_force_false_and_path_missing(tmp_path: Path) -> None:
    target = tmp_path / "abc-test.md"
    write(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_write_collision_without_force_raises(tmp_path: Path) -> None:
    target = tmp_path / "abc-test.md"
    target.write_text("existing")
    with pytest.raises(FileExistsError):
        write(target, "new content")
    # Original content preserved.
    assert target.read_text() == "existing"


def test_write_collision_with_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "abc-test.md"
    target.write_text("existing")
    result = write(target, "new content", force=True)
    assert result == target
    assert target.read_text() == "new content"


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "raw" / "abc.md"
    write(target, "x")
    assert target.exists()
    assert target.read_text() == "x"


def test_write_atomicity_uses_tempfile_rename(tmp_path: Path, monkeypatch) -> None:
    """If a write is interrupted, the original file (if any) survives."""
    target = tmp_path / "abc.md"
    target.write_text("original")

    # Simulate write failure mid-stream by raising during the temp-file write.
    real_replace = Path.replace

    def fail_replace(self, dst):  # type: ignore[no-redef]
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        write(target, "new", force=True)

    # Original survived.
    assert target.read_text() == "original"

    # Restore for other tests.
    monkeypatch.setattr(Path, "replace", real_replace)


# ---------- helpers ----------


def _parse_frontmatter(md: str) -> dict:
    """Extract YAML frontmatter from a `--- ... ---` block."""
    import yaml

    assert md.startswith("---\n"), "frontmatter must start with `---`"
    end = md.index("\n---\n", 4)
    return yaml.safe_load(md[4:end])
