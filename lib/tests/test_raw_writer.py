"""Tests for raw_writer shared raw ingest page builder/writer."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import raw_writer
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


def test_write_raw_file_rejects_raw_symlink_escape(tmp_path: Path) -> None:
    """A `raw` symlink pointing outside the vault must not let writes escape."""
    real_vault = tmp_path / "vault"
    real_vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # `<vault>/raw` is a symlink to a directory NOT named raw, outside the vault.
    (real_vault / "raw").symlink_to(outside, target_is_directory=True)
    target = real_vault / "raw" / "abc-test.md"

    with pytest.raises(RawWriterError, match="raw"):
        write_raw_file(target, "payload")

    assert not (outside / "abc-test.md").exists()


def test_write_raw_file_allows_real_raw_dir_behind_symlinked_vault(tmp_path: Path) -> None:
    """A symlinked *vault* whose real `raw/` is still named raw is fine —
    the resolved parent is named `raw`, so legitimate setups keep working."""
    real_vault = tmp_path / "real-vault"
    (real_vault / "raw").mkdir(parents=True)
    link_vault = tmp_path / "linked-vault"
    link_vault.symlink_to(real_vault, target_is_directory=True)
    target = link_vault / "raw" / "abc-test.md"

    result = write_raw_file(target, "hello\n")

    assert result.read_text(encoding="utf-8") == "hello\n"


def test_write_raw_file_fsyncs_file_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durability: the page is fsync'd and the parent dir is fsync'd after the
    rename, so the write survives power loss (not just crash-atomic)."""
    target = tmp_path / "raw" / "abc-test.md"
    fsynced: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(raw_writer.os, "fsync", recording_fsync)

    write_raw_file(target, "durable content")

    # At least two fsyncs: the file before rename, the directory after.
    assert len(fsynced) >= 2
    assert target.read_text(encoding="utf-8") == "durable content"


def test_write_raw_file_survives_unsupported_dir_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Some filesystems reject directory fsync — that must not fail the write,
    since the file data is already fsync'd before the rename."""
    target = tmp_path / "raw" / "abc-test.md"
    real_fsync = os.fsync

    def fsync_rejecting_dirs(fd: int) -> None:
        # Reject directory fds (what _fsync_dir opens); allow regular-file fds.
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("directory fsync unsupported on this filesystem")
        real_fsync(fd)

    monkeypatch.setattr(raw_writer.os, "fsync", fsync_rejecting_dirs)

    result = write_raw_file(target, "content")

    assert result.read_text(encoding="utf-8") == "content"
