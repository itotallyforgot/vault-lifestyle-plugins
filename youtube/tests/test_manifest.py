"""Tests for resumable YouTube bulk ingest manifests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vault_yt.manifest import (
    InvalidRunIdError,
    ManifestItem,
    RunManifest,
    VerificationEvidence,
    WorkInput,
    add_candidate_finding,
    add_verification_evidence,
    default_manifest_path,
    load_manifest,
    new_manifest,
    render_run_report,
    save_manifest,
    update_item_status,
    validate_run_id,
)


def test_default_manifest_path_lives_under_vault_staging_area(tmp_path: Path) -> None:
    path = default_manifest_path(tmp_path, "run-123")

    assert path == tmp_path / ".vault-lifestyle" / "youtube" / "runs" / "run-123" / "manifest.json"


@pytest.mark.parametrize(
    "run_id",
    [
        "../../../../tmp/x",
        "..",
        ".",
        "a/b",
        "a\\b",
        "run id with spaces",
        "",
        "/abs/path",
        "foo/../bar",
    ],
)
def test_validate_run_id_rejects_traversal_and_separators(run_id: str) -> None:
    with pytest.raises(InvalidRunIdError):
        validate_run_id(run_id)


@pytest.mark.parametrize(
    "run_id",
    ["run-123", "2026-06-11T183000Z-youtube", "abc.DEF_123", "a"],
)
def test_validate_run_id_accepts_safe_labels(run_id: str) -> None:
    assert validate_run_id(run_id) == run_id


def test_default_manifest_path_rejects_traversing_run_id(tmp_path: Path) -> None:
    """A hostile --run-id must not let the manifest path escape the vault."""
    with pytest.raises(InvalidRunIdError):
        default_manifest_path(tmp_path, "../../../../tmp/evil")


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


def test_add_candidate_finding_sets_pending_handoff_state(tmp_path: Path) -> None:
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
                raw_path="raw/a-video.md",
                source_url="https://youtu.be/abc123",
            )
        ],
        now=datetime(2026, 5, 7, 20, 30, tzinfo=UTC),
    )

    updated = add_candidate_finding(
        manifest,
        "abc123",
        claim="Rust ownership prevents data races at compile time.",
        transcript_span="00:01:00.000 --> 00:01:08.000",
        confidence=0.82,
        notes="Speaker framed this as a core language guarantee.",
    )

    finding = updated.items[0].candidate_findings[0]
    assert updated.items[0].candidate_findings_state == "ready"
    assert updated.items[0].verification_state == "pending"
    assert finding.id == "abc123-finding-1"
    assert finding.claim == "Rust ownership prevents data races at compile time."
    assert finding.source_url == "https://youtu.be/abc123"
    assert finding.raw_path == "raw/a-video.md"
    assert finding.verification_status == "pending"


def test_add_verification_evidence_updates_finding_and_item_state(tmp_path: Path) -> None:
    checked_at = datetime(2026, 5, 7, 21, 0, tzinfo=UTC)
    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="A video",
                position=0,
                raw_path="raw/a-video.md",
                source_url="https://youtu.be/abc123",
            )
        ],
    )
    manifest = add_candidate_finding(
        manifest,
        "abc123",
        claim="Claim that needs checking.",
        transcript_span="cue:1-2",
    )

    updated = add_verification_evidence(
        manifest,
        video_id="abc123",
        finding_id="abc123-finding-1",
        evidence=VerificationEvidence(
            evidence_url="https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
            verifier="George",
            checked_at=checked_at,
            result="accepted",
            notes="Rust Book supports this.",
        ),
    )

    finding = updated.items[0].candidate_findings[0]
    assert updated.items[0].verification_state == "complete"
    assert finding.verification_status == "accepted"
    assert finding.evidence[0].result == "accepted"
    assert finding.evidence[0].checked_at == checked_at


def test_add_verification_evidence_can_leave_item_partial(tmp_path: Path) -> None:
    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="A video",
                position=0,
            )
        ],
    )
    manifest = add_candidate_finding(manifest, "abc123", claim="Accepted.", transcript_span="cue:1")
    manifest = add_candidate_finding(
        manifest, "abc123", claim="Still pending.", transcript_span="cue:2"
    )

    updated = add_verification_evidence(
        manifest,
        video_id="abc123",
        finding_id="abc123-finding-1",
        evidence=VerificationEvidence(
            evidence_url="https://example.com",
            verifier="George",
            checked_at=datetime(2026, 5, 7, 21, 0, tzinfo=UTC),
            result="accepted",
        ),
    )

    assert updated.items[0].verification_state == "partial"
    assert [finding.verification_status for finding in updated.items[0].candidate_findings] == [
        "accepted",
        "pending",
    ]


def test_candidate_findings_and_evidence_roundtrip_json(tmp_path: Path) -> None:
    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[],
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
    manifest = add_candidate_finding(manifest, "abc123", claim="Claim.", transcript_span="cue:1")
    manifest = add_verification_evidence(
        manifest,
        video_id="abc123",
        finding_id="abc123-finding-1",
        evidence=VerificationEvidence(
            evidence_url="https://example.com",
            verifier="George",
            checked_at=datetime(2026, 5, 7, 21, 0, tzinfo=UTC),
            result="unresolved",
        ),
    )
    path = default_manifest_path(tmp_path, "run-123")

    save_manifest(path, manifest)
    loaded = load_manifest(path)

    assert loaded == manifest
    assert loaded.items[0].candidate_findings[0].evidence[0].result == "unresolved"


def test_render_run_report_summarizes_findings_and_verification(tmp_path: Path) -> None:
    manifest = new_manifest(
        run_id="run-123",
        vault_path=tmp_path,
        inputs=[],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="A video",
                position=0,
                status="raw_written",
                raw_path="raw/a-video.md",
            ),
            ManifestItem(
                video_id="def456",
                url="https://youtu.be/def456",
                title="B video",
                position=1,
                status="failed",
            ),
        ],
    )
    manifest = add_candidate_finding(manifest, "abc123", claim="Claim.", transcript_span="cue:1")

    report = render_run_report(manifest)

    assert "run: run-123" in report
    assert "raw_written: 1" in report
    assert "failed: 1" in report
    assert "candidate_findings: 1" in report
    assert "verification_pending: 1" in report
    assert "raw/a-video.md" in report
