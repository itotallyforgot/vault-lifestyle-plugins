"""Build and write `raw/<slug>.md` files for the second-brain vault.

The writer is the only thing in `vault-yt` that materializes a file under
`<vault>/raw/`. It composes YAML frontmatter (validated against
`lib/frontmatter_schema`) with a transcript body, then performs an atomic,
collision-aware write.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from frontmatter_schema import validate_frontmatter

TranscriptSource = Literal["yt-dlp", "whisper-tiny", "whisper-base", "whisper-small"]

_VALID_TRANSCRIPT_SOURCES: tuple[str, ...] = (
    "yt-dlp",
    "whisper-tiny",
    "whisper-base",
    "whisper-small",
)


class WriterError(RuntimeError):
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

    # Validate before serializing — catches contract bugs at the source.
    validate_frontmatter(fm)

    yaml_block = _serialize_frontmatter(fm)
    return f"---\n{yaml_block}---\n\n{transcript}"


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
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        raise FileExistsError(f"raw/<slug>.md already exists at {path} — pass --force to overwrite")

    # Atomic write: temp file in the same directory, then rename. Same
    # directory matters because rename is only atomic on the same FS.
    parent = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        tmp_path.replace(path)
    except BaseException:
        # Clean up temp file on any failure (including KeyboardInterrupt).
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise

    return path


# ----- internal helpers -----


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


def _serialize_frontmatter(fm: dict[str, Any]) -> str:
    """Serialize frontmatter dict to deterministic YAML.

    Key order matches the spec's Frontmatter contract example. PyYAML's
    ``safe_dump`` emits ``YYYY-MM-DD`` for ``date`` and ISO with offset for
    timezone-aware ``datetime``; we coerce ``datetime`` to a Z-suffixed
    string up-front so the schema's ISO-8601 pattern is satisfied
    regardless of YAML emitter quirks.
    """
    serializable: dict[str, Any] = {}
    for k, v in fm.items():
        if isinstance(v, datetime):
            # Force `Z`-suffix UTC string so the schema's tz-required pattern
            # is satisfied regardless of YAML emitter quirks.
            serializable[k] = _iso_z(v)
        else:
            # Leave bare `date` objects (and everything else) as-is — PyYAML
            # emits dates as unquoted YAML timestamps (`2009-10-25`).
            serializable[k] = v

    return yaml.safe_dump(
        serializable,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def _iso_z(ts: datetime) -> str:
    """Format a tz-aware datetime as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)."""
    if ts.tzinfo is None:
        raise WriterError(f"clipped_at must be timezone-aware; got {ts!r}")
    utc = ts.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
