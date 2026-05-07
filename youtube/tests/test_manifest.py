"""Tests for resumable YouTube bulk ingest manifests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from vault_yt.manifest import (
    ManifestItem,
    RunManifest,
    WorkInput,
    default_manifest_path,
    load_manifest,
    new_manifest,
    save_manifest,
    update_item_status,
)


def test_default_manifest_path_lives_under_vault_staging_area(tmp_path: Path) -> None:
    path = default_manifest_path(tmp_path, "run-123")

    assert path == tmp_path / ".vault-lifestyle" / "youtube" / "runs" / "run-123" / "manifest.json"


def test_new_manifest_contains_contract_fields(tmp_path: Path) -> None:
    created = datetime(2026, 5, 7, 20, 30, tzinfo=UTC)

    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[WorkInput(kind="playlist", ref="https://youtube.com/playlist?list=abc")],
        options={"limit": 3, "transcript_language": "en"},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="A video",
                position=0,
            )
        ],
        now=created,
    )

    assert manifest.schema_version == 1
    assert manifest.run_id == "run-123"
    assert manifest.source_kind == "youtube"
    assert manifest.created_at == created
    assert manifest.updated_at == created
    assert manifest.vault_path == str(tmp_path)
    assert manifest.inputs[0].kind == "playlist"
    assert manifest.options["limit"] == 3
    assert manifest.items[0].status == "pending"
    assert manifest.summary == {"pending": 1}


def test_save_manifest_writes_atomic_json_and_loads_roundtrip(tmp_path: Path) -> None:
    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[WorkInput(kind="video", ref="https://youtu.be/abc123")],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="A video",
                position=0,
            )
        ],
        now=datetime(2026, 5, 7, 20, 30, tzinfo=UTC),
    )
    path = default_manifest_path(tmp_path, manifest.run_id)

    save_manifest(path, manifest)
    loaded = load_manifest(path)

    assert loaded == manifest
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["items"][0]["video_id"] == "abc123"
    assert not list(path.parent.glob("*.tmp"))


def test_update_item_status_recomputes_summary_and_timestamps(tmp_path: Path) -> None:
    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[WorkInput(kind="video", ref="https://youtu.be/abc123")],
        options={},
        items=[
            ManifestItem(
                video_id="abc123", url="https://youtu.be/abc123", title="A video", position=0
            ),
            ManifestItem(
                video_id="def456", url="https://youtu.be/def456", title="B video", position=1
            ),
        ],
        now=datetime(2026, 5, 7, 20, 30, tzinfo=UTC),
    )
    updated_at = datetime(2026, 5, 7, 20, 45, tzinfo=UTC)

    updated = update_item_status(
        manifest,
        "abc123",
        "raw_written",
        now=updated_at,
        title="Updated title",
        raw_path="raw/2026-05-07-youtube-abc123-a-video.md",
        transcript_source="yt-dlp",
        transcript_language="en",
    )

    assert updated.updated_at == updated_at
    assert updated.items[0].status == "raw_written"
    assert updated.items[0].title == "Updated title"
    assert updated.items[0].raw_path == "raw/2026-05-07-youtube-abc123-a-video.md"
    assert updated.items[0].finished_at == updated_at
    assert updated.summary == {"raw_written": 1, "pending": 1}


def test_update_item_status_unknown_video_raises(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id="run-123", vault_path=str(tmp_path), inputs=[], options={}, items=[]
    )

    try:
        update_item_status(manifest, "missing", "failed")
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected ValueError")
