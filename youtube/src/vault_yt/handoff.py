"""External playlist handoff JSONL for authless bulk ingest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vault_yt.inputs import InputAppearance, InputExpansionError, WorkItem, parse_video_id


@dataclass(frozen=True)
class HandoffError(ValueError):
    """Raised when an external handoff file cannot be consumed safely."""

    message: str
    path: Path | None = None
    line_number: int | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class HandoffRecord:
    """One JSONL record written by an authenticated external playlist exporter."""

    video_id: str
    url: str
    title: str | None = None
    source_provider: str | None = None
    playlist_id: str | None = None
    playlist_title: str | None = None
    playlist_url: str | None = None
    playlist_index: int | None = None
    channel: str | None = None
    channel_url: str | None = None


def read_handoff(path: Path) -> list[WorkItem]:
    """Read handoff JSONL into ordered, deduped work items."""
    state = _HandoffState()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise HandoffError(f"could not read handoff file: {path}", path=path) from e

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        record = _parse_line(line, path=path, line_number=line_number)
        state.add(record, path=path, line_number=line_number)
    return state.items()


def write_handoff(path: Path, records: list[HandoffRecord]) -> Path:
    """Write records as newline-delimited JSON with stable keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(_record_to_json(record), ensure_ascii=False, sort_keys=True)
        for record in records
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


class _HandoffState:
    def __init__(self) -> None:
        self._order: list[str] = []
        self._urls: dict[str, str] = {}
        self._titles: dict[str, str | None] = {}
        self._appearances: dict[str, list[InputAppearance]] = {}

    def add(self, record: HandoffRecord, *, path: Path, line_number: int) -> None:
        if record.video_id not in self._appearances:
            self._order.append(record.video_id)
            self._urls[record.video_id] = record.url
            self._titles[record.video_id] = record.title
            self._appearances[record.video_id] = []
        elif self._titles[record.video_id] is None and record.title is not None:
            self._titles[record.video_id] = record.title

        self._appearances[record.video_id].append(
            InputAppearance(
                kind="playlist" if record.playlist_id or record.playlist_title else "video",
                source=str(path),
                url=record.url,
                line_number=line_number,
                playlist_id=record.playlist_id,
                playlist_title=record.playlist_title,
                playlist_url=record.playlist_url,
                playlist_index=record.playlist_index,
                source_provider=record.source_provider,
            )
        )

    def items(self) -> list[WorkItem]:
        return [
            WorkItem(
                video_id=video_id,
                url=self._urls[video_id],
                appearances=tuple(self._appearances[video_id]),
                title=self._titles[video_id],
            )
            for video_id in self._order
        ]


def _parse_line(line: str, *, path: Path, line_number: int) -> HandoffRecord:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as e:
        raise HandoffError(
            f"malformed handoff JSON at {path}:{line_number}: {e.msg}",
            path=path,
            line_number=line_number,
        ) from e
    if not isinstance(raw, dict):
        raise HandoffError(
            f"handoff record at {path}:{line_number} must be a JSON object",
            path=path,
            line_number=line_number,
        )

    video_id = _string_or_none(raw.get("video_id"))
    url = _string_or_none(raw.get("url"))
    if video_id is None and url is not None:
        try:
            video_id = parse_video_id(url)
        except InputExpansionError as e:
            raise HandoffError(
                f"handoff record at {path}:{line_number} has unsupported YouTube url",
                path=path,
                line_number=line_number,
            ) from e
    if video_id is None:
        raise HandoffError(
            f"handoff record at {path}:{line_number} requires video_id or YouTube url",
            path=path,
            line_number=line_number,
        )

    return HandoffRecord(
        video_id=video_id,
        url=url or f"https://youtu.be/{video_id}",
        title=_string_or_none(raw.get("title")),
        source_provider=_string_or_none(raw.get("source_provider")),
        playlist_id=_string_or_none(raw.get("playlist_id")),
        playlist_title=_string_or_none(raw.get("playlist_title")),
        playlist_url=_string_or_none(raw.get("playlist_url")),
        playlist_index=_int_or_none(raw.get("playlist_index")),
        channel=_string_or_none(raw.get("channel")),
        channel_url=_string_or_none(raw.get("channel_url")),
    )


def _record_to_json(record: HandoffRecord) -> dict[str, Any]:
    return {key: value for key, value in record.__dict__.items() if value is not None}


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
