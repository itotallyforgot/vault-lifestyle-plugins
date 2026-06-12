"""Shared builder/writer for vault `raw/<slug>.md` ingest pages."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from frontmatter_schema import validate_frontmatter


class RawWriterError(RuntimeError):
    """Raised when raw writer arguments violate the vault ingest contract."""


def build_raw_markdown(frontmatter: Mapping[str, Any], body: str) -> str:
    """Build a raw ingest markdown page after validating frontmatter."""
    fm = dict(frontmatter)
    validate_frontmatter(fm)

    yaml_block = _serialize_frontmatter(fm)
    return f"---\n{yaml_block}---\n\n{body}"


def write_raw_file(path: Path, content: str, force: bool = False) -> Path:
    """Atomically and durably write content to a vault raw destination.

    The write is both crash-atomic (write to a sibling temp file, then
    `os.replace`, so a reader never sees a half-written page) and durable
    (`fsync` the file before the rename and `fsync` the parent directory after,
    so the rename itself survives a power loss). Best-effort on the directory
    fsync — some filesystems (e.g. certain network mounts) reject it; an
    unsupported fsync must not fail an otherwise-complete write.
    """
    path = Path(path)
    _ensure_raw_destination(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        raise FileExistsError(f"raw/<slug>.md already exists at {path} - pass --force to overwrite")

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
        _fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise

    return path


def _fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename into it is durably recorded. Best-effort.

    Directory fsync is unsupported on some platforms/filesystems (raises
    OSError); swallow that rather than failing a write whose data is already
    fsync'd. The file-level fsync above is the load-bearing guarantee.
    """
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _ensure_raw_destination(path: Path) -> None:
    """Reject writes that don't land directly inside a real `raw/` directory.

    Resolves the parent (following symlinks) so a `raw` symlink pointing at a
    differently-named directory can't be used to escape the intended write
    boundary, then asserts the resolved file sits directly inside that resolved
    `raw/` directory.
    """
    resolved_parent = path.parent.resolve()
    if resolved_parent.name != "raw":
        raise RawWriterError(f"raw ingest writes must target a file directly under raw/: {path}")
    # The fully-resolved destination must be a direct child of the resolved
    # raw/ dir — catches `..` segments and symlinked file names that would
    # otherwise land the write outside raw/.
    resolved_file = (resolved_parent / path.name).resolve()
    if resolved_file.parent != resolved_parent:
        raise RawWriterError(f"raw ingest path escapes its raw/ directory: {path}")


def _serialize_frontmatter(fm: Mapping[str, Any]) -> str:
    serializable: dict[str, Any] = {}
    for key, value in fm.items():
        if isinstance(value, datetime):
            serializable[key] = _iso_z(value)
        else:
            serializable[key] = value

    return yaml.safe_dump(
        serializable,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def _iso_z(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise RawWriterError(f"datetime values must be timezone-aware; got {ts!r}")
    utc = ts.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
