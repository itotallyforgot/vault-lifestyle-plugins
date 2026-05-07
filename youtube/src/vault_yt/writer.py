"""Build and write `raw/<slug>.md` files for the markdown-vault vault.

The writer is the only thing in `vault-yt` that materializes a file under
`<vault>/raw/`. It composes YouTube-specific frontmatter and delegates the
shared raw-page validation, serialization, and atomic write behavior to
`lib/raw_writer`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from raw_writer import RawWriterError, build_raw_markdown, write_raw_file

TranscriptSource = Literal["yt-dlp", "whisper-tiny", "whisper-base", "whisper-small"]

_VALID_TRANSCRIPT_SOURCES: tuple[str, ...] = (
    "yt-dlp",
    "whisper-tiny",
    "whisper-base",
    "whisper-small",
)


class WriterError(RawWriterError):
    """Raised on writer-side contract violations (bad meta, invalid args)."""


def build_raw_md(
    meta: Mapping[str, Any],
    transcript: str,
    transcript_source: str,
    *,
    clipped_at: datetime | None = None,
) -> str:
    """Compose a full `raw/<slug>.md` payload (frontmatter + body).

    Args:
        meta: ``extractor.fetch_meta`` output dict. Required keys: ``id``,
            ``title``. Optional/passthrough: ``channel``, ``channel_url``,
            ``published_at`` (date or None), ``duration_seconds`` (int or
            None).
        transcript: Plain transcript text, already paragraph-broken by the
            extractor / whisper resolver. Written as-is to the body.
        transcript_source: One of ``"yt-dlp"``, ``"whisper-tiny"``,
            ``"whisper-base"``, ``"whisper-small"``. Validated up-front.
        clipped_at: Override the current-time stamp — provided for
            deterministic tests. Defaults to ``datetime.now(UTC)``.

    Returns:
        The full markdown payload as a string. Frontmatter is validated
        against ``lib.frontmatter_schema.Frontmatter`` *before*
        serialization; a contract bug here surfaces as a Pydantic
        ``ValidationError`` rather than a malformed file on disk.

    Raises:
        WriterError: if ``transcript_source`` is unknown or required meta
            fields are missing.
        pydantic.ValidationError: if the assembled frontmatter dict fails
            schema validation (should not happen with a well-formed
            extractor — indicates an internal bug).
    """
    if transcript_source not in _VALID_TRANSCRIPT_SOURCES:
        raise WriterError(
            f"transcript_source must be one of {_VALID_TRANSCRIPT_SOURCES!r}; "
            f"got {transcript_source!r}"
        )
    if "id" not in meta:
        raise WriterError("meta missing required key 'id'")
    if "title" not in meta:
        raise WriterError("meta missing required key 'title'")

    fm = _build_frontmatter_dict(
        meta,
        transcript_source=transcript_source,
        clipped_at=clipped_at or datetime.now(UTC),
    )

    return build_raw_markdown(fm, transcript)


def write(path: Path, content: str, force: bool = False) -> Path:
    """Atomically write ``content`` to ``path``.

    Default behavior is collision-refusing: if ``path`` already exists,
    raises ``FileExistsError`` (mapped to spec exit code 9 by the caller).
    Pass ``force=True`` to overwrite — the existing file is replaced
    atomically; an interrupted write leaves the original intact.

    Parent directories are created as needed.

    Args:
        path: Destination path (typically ``<vault>/raw/<slug>.md``).
        content: Full file contents (frontmatter + body).
        force: When True, overwrite an existing file. Default False.

    Returns:
        The written path.

    Raises:
        FileExistsError: when ``path`` exists and ``force=False``.
        OSError: passed through from the underlying filesystem.
    """
    try:
        return write_raw_file(path, content, force=force)
    except RawWriterError as exc:
        raise WriterError(str(exc)) from exc


def _build_frontmatter_dict(
    meta: Mapping[str, Any],
    *,
    transcript_source: str,
    clipped_at: datetime,
) -> dict[str, Any]:
    """Assemble the frontmatter dict per spec §"Frontmatter contract"."""
    video_id = meta["id"]
    fm: dict[str, Any] = {
        "title": meta["title"],
        "source_url": f"https://youtu.be/{video_id}",
        "source_kind": "youtube",
        "channel": meta.get("channel"),
        "channel_url": meta.get("channel_url"),
        "published_at": meta.get("published_at"),
        "duration_seconds": meta.get("duration_seconds"),
        "clipped_at": clipped_at,
        "transcript_source": transcript_source,
        "ingested": False,
        "ingested_at": None,
        "wiki_page": None,
        "tags": ["youtube"],
    }
    return fm
