"""Tests for raw_writer shared raw ingest page builder/writer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from raw_writer import RawWriterError, build_raw_markdown, write_raw_file


def _frontmatter(**overrides) -> dict:
    base = {
        "title": "Shared Raw Page",
        "source_url": "https://example.com/source",
        "source_kind": "test",
        "clipped_at": datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC),
        "ingested": False,
        "tags": ["test"],
    }
    base.update(overrides)
    return base


def test_build_raw_markdown_validates_and_serializes_frontmatter() -> None:
    md = build_raw_markdown(_frontmatter(), "Transcript body.")

    assert md == (
        "---\n"
        "title: Shared Raw Page\n"
        "source_url: https://example.com/source\n"
        "source_kind: test\n"
        "clipped_at: '2026-05-05T12:00:00Z'\n"
        "ingested: false\n"
        "tags:\n"
        "- test\n"
        "---\n"
        "\n"
        "Transcript body."
    )


def test_build_raw_markdown_rejects_invalid_frontmatter() -> None:
    with pytest.raises(ValidationError):
        build_raw_markdown(_frontmatter(ingested=True), "body")


def test_write_raw_file_creates_parent_and_writes_under_raw(tmp_path: Path) -> None:
    target = tmp_path / "raw" / "abc-test.md"

    result = write_raw_file(target, "hello\n")

    assert result == target
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_raw_file_rejects_non_raw_destination(tmp_path: Path) -> None:
    target = tmp_path / "notes" / "abc-test.md"

    with pytest.raises(RawWriterError, match="raw"):
        write_raw_file(target, "hello\n")

    assert not target.exists()


def test_write_raw_file_collision_without_force_preserves_existing(tmp_path: Path) -> None:
    target = tmp_path / "raw" / "abc-test.md"
    target.parent.mkdir()
    target.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_raw_file(target, "new content")

    assert target.read_text(encoding="utf-8") == "existing"


def test_write_raw_file_collision_with_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "raw" / "abc-test.md"
    target.parent.mkdir()
    target.write_text("existing", encoding="utf-8")

    result = write_raw_file(target, "new content", force=True)

    assert result == target
    assert target.read_text(encoding="utf-8") == "new content"


def test_write_raw_file_atomicity_preserves_original_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "raw" / "abc-test.md"
    target.parent.mkdir()
    target.write_text("original", encoding="utf-8")

    def fail_replace(self: Path, dst: Path) -> Path:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        write_raw_file(target, "new", force=True)

    assert target.read_text(encoding="utf-8") == "original"
    assert list(target.parent.glob("*.tmp")) == []
