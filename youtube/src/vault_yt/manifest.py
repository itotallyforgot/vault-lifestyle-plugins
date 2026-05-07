"""Resumable staging manifests for YouTube bulk ingest runs."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ItemStatus = Literal[
    "pending",
    "processing",
    "raw_written",
    "skipped_existing",
    "failed",
    "needs_attention",
]

CandidateFindingsState = Literal[
    "not_requested",
    "pending",
    "ready",
    "failed",
    "accepted_by_vault",
]

VerificationState = Literal[
    "not_requested",
    "pending",
    "partial",
    "complete",
    "blocked",
]

InputKind = Literal["video", "playlist", "url_file"]


@dataclass(frozen=True)
class WorkInput:
    """Original input descriptor for a bulk run."""

    kind: InputKind
    ref: str


@dataclass(frozen=True)
class ManifestError:
    """Structured per-item failure detail."""

    kind: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class ManifestItem:
    """Per-video state stored in a run manifest."""

    video_id: str
    url: str
    title: str | None
    position: int
    status: ItemStatus = "pending"
    raw_path: str | None = None
    source_url: str | None = None
    transcript_source: str | None = None
    transcript_language: str | None = None
    candidate_findings_state: CandidateFindingsState = "not_requested"
    verification_state: VerificationState = "not_requested"
    error: ManifestError | None = None
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class RunManifest:
    """Top-level YouTube staging manifest."""

    run_id: str
    vault_path: str
    inputs: list[WorkInput]
    options: dict[str, Any]
    items: list[ManifestItem]
    schema_version: int = 1
    source_kind: Literal["youtube"] = "youtube"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    summary: dict[str, int] = field(default_factory=dict)


def default_manifest_path(vault_path: Path, run_id: str) -> Path:
    """Return the default manifest path for a vault and run."""
    return Path(vault_path) / ".vault-lifestyle" / "youtube" / "runs" / run_id / "manifest.json"


def new_manifest(
    *,
    run_id: str,
    vault_path: Path,
    inputs: list[WorkInput],
    options: dict[str, Any],
    items: list[ManifestItem],
    now: datetime | None = None,
) -> RunManifest:
    """Build a new manifest with initialized timestamps and summary."""
    ts = now or _utcnow()
    manifest = RunManifest(
        run_id=run_id,
        vault_path=str(vault_path),
        inputs=inputs,
        options=dict(options),
        items=items,
        created_at=ts,
        updated_at=ts,
    )
    return replace(manifest, summary=_summary(items))


def save_manifest(path: Path, manifest: RunManifest) -> Path:
    """Atomically save a manifest as stable, human-readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _to_json_dict(manifest)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise
    return path


def load_manifest(path: Path) -> RunManifest:
    """Load a manifest JSON file from disk."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return _from_json_dict(data)


def update_item_status(
    manifest: RunManifest,
    video_id: str,
    status: ItemStatus,
    *,
    now: datetime | None = None,
    title: str | None = None,
    raw_path: str | None = None,
    transcript_source: str | None = None,
    transcript_language: str | None = None,
    error: ManifestError | None = None,
) -> RunManifest:
    """Return a manifest with one item's status updated."""
    ts = now or _utcnow()
    changed = False
    items: list[ManifestItem] = []
    for item in manifest.items:
        if item.video_id != video_id:
            items.append(item)
            continue
        changed = True
        items.append(
            replace(
                item,
                status=status,
                title=title if title is not None else item.title,
                raw_path=raw_path if raw_path is not None else item.raw_path,
                source_url=item.source_url or item.url,
                transcript_source=transcript_source or item.transcript_source,
                transcript_language=transcript_language or item.transcript_language,
                error=error,
                finished_at=ts if status not in {"pending", "processing"} else item.finished_at,
            )
        )

    if not changed:
        raise ValueError(f"manifest item not found for video_id: {video_id}")

    return replace(manifest, items=items, updated_at=ts, summary=_summary(items))


def _summary(items: list[ManifestItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _to_json_dict(manifest: RunManifest) -> dict[str, Any]:
    data = asdict(manifest)
    data["created_at"] = _format_datetime(manifest.created_at)
    data["updated_at"] = _format_datetime(manifest.updated_at)
    for item, raw in zip(manifest.items, data["items"], strict=True):
        raw["started_at"] = _format_datetime(item.started_at)
        raw["finished_at"] = _format_datetime(item.finished_at)
    return data


def _from_json_dict(data: dict[str, Any]) -> RunManifest:
    return RunManifest(
        schema_version=data["schema_version"],
        run_id=data["run_id"],
        source_kind=data["source_kind"],
        created_at=_parse_datetime(data["created_at"]),
        updated_at=_parse_datetime(data["updated_at"]),
        vault_path=data["vault_path"],
        inputs=[WorkInput(**raw) for raw in data["inputs"]],
        options=data["options"],
        items=[
            ManifestItem(
                **{
                    **raw,
                    "error": ManifestError(**raw["error"]) if raw.get("error") else None,
                    "started_at": _parse_datetime(raw.get("started_at")),
                    "finished_at": _parse_datetime(raw.get("finished_at")),
                }
            )
            for raw in data["items"]
        ],
        summary=data["summary"],
    )


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utcnow() -> datetime:
    return datetime.now(UTC)
