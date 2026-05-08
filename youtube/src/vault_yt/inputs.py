"""Expand supported YouTube inputs into deterministic ingest work items."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

AppearanceKind = Literal["video", "playlist"]
InputKind = Literal["video", "playlist"]


@dataclass(frozen=True)
class InputAppearance:
    """One place a video appeared in the user's input."""

    kind: AppearanceKind
    source: str
    url: str
    line_number: int | None = None
    playlist_id: str | None = None
    playlist_title: str | None = None
    playlist_url: str | None = None
    playlist_index: int | None = None
    source_provider: str | None = None


@dataclass(frozen=True)
class WorkItem:
    """A unique YouTube video to ingest."""

    video_id: str
    url: str
    appearances: tuple[InputAppearance, ...]
    title: str | None = None


class InputExpansionError(ValueError):
    """Raised when an input cannot be expanded cleanly."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        line_number: int | None = None,
        entry: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.line_number = line_number
        self.entry = entry


@dataclass(frozen=True)
class _ParsedInput:
    kind: InputKind
    video_id: str | None = None
    playlist_id: str | None = None


@dataclass(frozen=True)
class _InputContext:
    source: str
    line_number: int | None = None
    path: Path | None = None


def expand_input(input_value: str | Path) -> list[WorkItem]:
    """Expand a single URL or URL-list file into ordered, deduped work items."""
    return expand_inputs([input_value])


def expand_inputs(input_values: Iterable[str | Path]) -> list[WorkItem]:
    """Expand multiple inputs, collapsing duplicate videos in first-seen order."""
    state = _ExpansionState()
    for input_value in input_values:
        _expand_one(input_value, state)
    return state.items()


def parse_video_id(url: str) -> str:
    """Return a YouTube video ID from a supported video URL."""
    parsed = _parse_youtube_input(url)
    if parsed.video_id is None:
        raise InputExpansionError(f"unsupported YouTube video input: {url}")
    return parsed.video_id


class _ExpansionState:
    def __init__(self) -> None:
        self._order: list[str] = []
        self._urls: dict[str, str] = {}
        self._appearances: dict[str, list[InputAppearance]] = {}
        self._titles: dict[str, str | None] = {}

    def add(
        self,
        video_id: str,
        url: str,
        appearance: InputAppearance,
        *,
        title: str | None = None,
    ) -> None:
        if video_id not in self._appearances:
            self._order.append(video_id)
            self._urls[video_id] = url
            self._appearances[video_id] = []
            self._titles[video_id] = title
        elif self._titles[video_id] is None and title is not None:
            self._titles[video_id] = title
        self._appearances[video_id].append(appearance)

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


def _expand_one(input_value: str | Path, state: _ExpansionState) -> None:
    if isinstance(input_value, Path):
        if input_value.is_file():
            _expand_url_file(input_value, state)
            return
        raise InputExpansionError(f"url-list file not found: {input_value}", path=input_value)

    value = input_value.strip()
    if not value:
        raise InputExpansionError("empty input")

    path = Path(value)
    if path.is_file():
        _expand_url_file(path, state)
        return

    _expand_url(value, _InputContext(source=value), state)


def _expand_url_file(path: Path, state: _ExpansionState) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise InputExpansionError(f"could not read url-list file: {path}", path=path) from e

    for line_number, raw_line in enumerate(lines, start=1):
        entry = raw_line.strip()
        if not entry or entry.startswith("#"):
            continue
        try:
            context = _InputContext(source=str(path), line_number=line_number, path=path)
            _expand_url(entry, context, state)
        except InputExpansionError as e:
            reason = str(e)
            prefix = (
                "malformed url-list entry"
                if reason.startswith(("malformed url", "unsupported YouTube input"))
                else "url-list entry failed"
            )
            raise InputExpansionError(
                f"{prefix} at {path}:{line_number}: {entry}",
                path=path,
                line_number=line_number,
                entry=entry,
            ) from e


def _expand_url(url: str, context: _InputContext, state: _ExpansionState) -> None:
    parsed = _parse_youtube_input(url)
    if parsed.kind == "playlist":
        _expand_playlist(url, context, state)
        return

    if parsed.video_id is None:
        raise InputExpansionError(f"unsupported YouTube input: {url}")

    video_url = _canonical_video_url(parsed.video_id)
    state.add(
        parsed.video_id,
        video_url,
        InputAppearance(
            kind="video",
            source=context.source,
            url=url,
            line_number=context.line_number,
        ),
    )


def _expand_playlist(url: str, context: _InputContext, state: _ExpansionState) -> None:
    info = _fetch_playlist_info(url)
    entries = info.get("entries") or []
    playlist_id = _string_or_none(info.get("id")) or _parse_youtube_input(url).playlist_id
    playlist_title = _string_or_none(info.get("title"))
    playlist_url = _string_or_none(info.get("webpage_url")) or url

    for position, entry in enumerate(entries, start=1):
        video_id = _entry_video_id(entry)
        if video_id is None:
            continue
        playlist_index = _entry_playlist_index(entry) or position
        video_url = _entry_video_url(entry, video_id)
        state.add(
            video_id,
            _canonical_video_url(video_id),
            InputAppearance(
                kind="playlist",
                source=context.source,
                url=video_url,
                line_number=context.line_number,
                playlist_id=playlist_id,
                playlist_title=playlist_title,
                playlist_url=playlist_url,
                playlist_index=playlist_index,
            ),
        )


def _fetch_playlist_info(url: str) -> dict[str, Any]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    try:
        with YoutubeDL(cast(Any, opts)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise InputExpansionError(f"yt-dlp failed for playlist {url}: {e}") from e

    if not isinstance(info, dict):
        raise InputExpansionError(f"yt-dlp returned no playlist info for {url}")
    return info


def _parse_youtube_input(url: str) -> _ParsedInput:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InputExpansionError(f"malformed url: {url}")

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}:
        raise InputExpansionError(f"unsupported YouTube input: {url}")

    query = parse_qs(parsed.query)
    playlist_id = _first_query_value(query, "list")
    if playlist_id:
        return _ParsedInput(kind="playlist", playlist_id=playlist_id)

    video_id: str | None = None
    parts = [part for part in parsed.path.split("/") if part]
    if host == "youtu.be":
        video_id = parts[0] if parts else None
    elif parsed.path == "/watch":
        video_id = _first_query_value(query, "v")
    elif len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
        video_id = parts[1]

    if video_id:
        return _ParsedInput(kind="video", video_id=video_id)
    raise InputExpansionError(f"unsupported YouTube input: {url}")


def _entry_video_id(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None

    entry_id = _string_or_none(entry.get("id"))
    if entry_id:
        return entry_id

    for key in ("webpage_url", "url"):
        value = _string_or_none(entry.get(key))
        if not value:
            continue
        if _looks_like_url(value):
            try:
                return _parse_youtube_input(value).video_id
            except InputExpansionError:
                continue
        return value
    return None


def _entry_video_url(entry: object, video_id: str) -> str:
    if isinstance(entry, dict):
        webpage_url = _string_or_none(entry.get("webpage_url"))
        if webpage_url:
            return webpage_url
        raw_url = _string_or_none(entry.get("url"))
        if raw_url and _looks_like_url(raw_url):
            return raw_url
    return _canonical_video_url(video_id)


def _entry_playlist_index(entry: object) -> int | None:
    if not isinstance(entry, dict):
        return None
    value = entry.get("playlist_index")
    return value if isinstance(value, int) else None


def _canonical_video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
