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
    """Atomically write content to a vault raw destination."""
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
        tmp_path.replace(path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise

    return path


def _ensure_raw_destination(path: Path) -> None:
    if path.parent.name != "raw":
        raise RawWriterError(f"raw ingest writes must target a file directly under raw/: {path}")


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
