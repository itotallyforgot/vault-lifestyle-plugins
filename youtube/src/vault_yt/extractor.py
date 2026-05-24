"""yt-dlp wrapper: metadata, captions, and audio download for a YouTube URL.

Exposes functions consumed by later slices:

- `fetch_meta(url)` — metadata dict (Slice 4 builder).
- `fetch_captions(url, lang)` — primary transcript path (Slice 5 CLI).
- `fetch_caption_cues(url, lang)` — caption cues with VTT timestamps for provenance prep.
- `download_audio(url, dest_dir)` — Whisper input (Slice 3 fallback).

Caller never instantiates `YoutubeDL` directly. Tests mock at the
`yt_dlp.YoutubeDL` boundary.

Failures raise `ExtractorError` with a `kind` discriminator so Slice 5
(CLI) can map cleanly to spec exit codes without regex-matching message
strings. Kinds: `network`, `no_info`, `no_audio_file`, `unknown`.
"""

from __future__ import annotations

import html
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


ExtractorErrorKind = Literal["network", "no_info", "no_audio_file", "unknown"]


@dataclass(frozen=True)
class CaptionCue:
    """A parsed VTT cue with source timestamps preserved."""

    start: str
    end: str
    text: str


class ExtractorError(RuntimeError):
    """Raised on failures specific to YouTube metadata / caption / audio extraction.

    The `kind` discriminator lets the CLI (Slice 5) map cleanly to the
    spec's exit-code table — `network` is retryable, `no_info` /
    `no_audio_file` are permanent for the given URL.
    """

    def __init__(self, kind: ExtractorErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ExtractorErrorKind = kind


# Conservative trust-boundary defaults for `download_audio`. Larger inputs
# are rejected by yt-dlp before bytes hit disk.
MAX_AUDIO_FILESIZE_BYTES = 500 * 1024 * 1024  # 500 MiB
MAX_VIDEO_DURATION_SECONDS = 8 * 60 * 60  # 8 hours — blocks livestream rips


# ----- public API -----


def fetch_meta(url: str) -> dict[str, Any]:
    """Fetch metadata for a YouTube URL.

    Returns a dict with the keys consumed by the writer (Slice 4):

    - `id`: YouTube video ID (validated non-empty).
    - `title`: video title (validated non-empty).
    - `channel`, `channel_url`: channel info (falls back to `uploader`/`uploader_url`); may be None.
    - `published_at`: `datetime.date` derived from yt-dlp's `upload_date`
      (`YYYYMMDD`); None if absent or malformed.
    - `duration_seconds`: int seconds; None if absent.
    - `captions`: sorted list[str] of available subtitle language codes
      (manual + auto-generated, deduped).
    - `caption_kinds`: dict[lang, "manual" | "auto"]. Manual wins when both
      exist for the same language. Used by `resolver` to skip a second
      yt-dlp round-trip.

    Raises:
        ExtractorError(kind="network"): yt-dlp's extract_info raised.
        ExtractorError(kind="no_info"): yt-dlp returned None or an info dict missing `id`/`title`.
    """
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with YoutubeDL(cast(Any, opts)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise ExtractorError("network", f"yt-dlp failed for {url}: {e}") from e

    if info is None:
        raise ExtractorError("no_info", f"yt-dlp returned no info for {url}")

    video_id = info.get("id")
    title = info.get("title")
    if not isinstance(video_id, str) or not video_id:
        raise ExtractorError("no_info", f"yt-dlp info missing `id` for {url}")
    if not isinstance(title, str) or not title:
        raise ExtractorError("no_info", f"yt-dlp info missing `title` for {url}")

    manual_langs = set((info.get("subtitles") or {}).keys())
    auto_langs = set((info.get("automatic_captions") or {}).keys())
    captions = sorted(manual_langs | auto_langs)
    # Per-language source. Build auto-first then overlay manual so the
    # manual-wins invariant is reorder-safe — flipping the order of these
    # two statements still yields manual-wins. Used by
    # `resolver.choose_transcript_source` to avoid a second yt-dlp round-trip.
    caption_kinds: dict[str, str] = {lang: "auto" for lang in auto_langs}
    caption_kinds.update({lang: "manual" for lang in manual_langs})

    upload_date = info.get("upload_date")
    published_at: date | None = None
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            published_at = date.fromisoformat(
                f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
            )
        except ValueError:
            published_at = None  # malformed (e.g., `20211332`) — silently drop

    return {
        "id": video_id,
        "title": title,
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "published_at": published_at,
        "duration_seconds": info.get("duration"),
        "captions": captions,
        "caption_kinds": caption_kinds,
    }


def fetch_captions(url: str, lang: str = "en") -> str | None:
    """Fetch captions for `url` in language `lang` and return plain transcript text.

    Tries manual subtitles first, falls back to auto-generated for the
    same language. Returns None if neither is available in `lang`.

    yt-dlp writes subtitle filenames in several real-world shapes:
    `<id>.<lang>.vtt` (manual), `<id>.<lang>-orig.vtt` (manual with
    normalized lang), `<id>.<lang>-auto.vtt` (auto-generated). Glob
    matches all three; we prefer non-`-auto` files when both exist.

    Raises:
        ExtractorError(kind="network"): yt-dlp's extract_info raised.
    """
    vtt_content = _fetch_caption_vtt(url, lang)
    if vtt_content is None:
        return None
    return _parse_vtt(vtt_content)


def fetch_caption_cues(url: str, lang: str = "en") -> list[CaptionCue] | None:
    """Fetch captions for `url` and return parsed VTT cues with timestamps.

    This is a prep API for provenance-aware callers. It intentionally leaves
    `fetch_captions(url, lang)` unchanged: that function still returns plain
    transcript text without timestamp anchors.

    Raises:
        ExtractorError(kind="network"): yt-dlp's extract_info raised.
    """
    vtt_content = _fetch_caption_vtt(url, lang)
    if vtt_content is None:
        return None
    return _parse_vtt_cues(vtt_content)


def download_audio(url: str, dest_dir: Path) -> Path:
    """Download the smallest audio stream for `url` into `dest_dir`.

    Returns the path to the downloaded audio file. Used as Whisper input
    when captions are absent. Caller is responsible for cleaning up
    `dest_dir` after Whisper finishes.

    Trust boundary: `dest_dir` is created if absent. Caller is expected
    to pass an absolute path under a known root (e.g. a tmp dir or a
    plug-in cache) — this function does not validate path-traversal
    semantics. Within `dest_dir`, yt-dlp's `outtmpl` shape ensures the
    written filename is `<id>.<ext>` only.

    Size + duration caps:
    - `MAX_AUDIO_FILESIZE_BYTES` (500 MiB) — yt-dlp aborts before disk fill.
    - `MAX_VIDEO_DURATION_SECONDS` (8 h) — `match_filter` rejects livestreams.

    Raises:
        ExtractorError(kind="network"): yt-dlp's extract_info raised
            (includes filesize/duration filter rejections wrapped by yt-dlp).
        ExtractorError(kind="no_info"): yt-dlp returned None or info without `id`.
        ExtractorError(kind="no_audio_file"): yt-dlp succeeded but no file landed.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        # Prefer m4a (smallest, Whisper-friendly); fall back to whatever bestaudio is.
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "max_filesize": MAX_AUDIO_FILESIZE_BYTES,
        "match_filter": _duration_filter,
    }
    try:
        with YoutubeDL(cast(Any, opts)) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise ExtractorError("network", f"audio download failed for {url}: {e}") from e

    if info is None:
        raise ExtractorError("no_info", f"yt-dlp returned no info for audio at {url}")

    video_id = info.get("id")
    if not video_id:
        raise ExtractorError("no_info", f"yt-dlp returned info without id for {url}")

    matches = list(dest_dir.glob(f"{video_id}.*"))
    if not matches:
        raise ExtractorError(
            "no_audio_file",
            f"audio file not found for {video_id} in {dest_dir} "
            "(likely filesize/duration cap rejected the source)",
        )

    # Multiple format files may be written; return the largest (the actual audio).
    return max(matches, key=lambda p: p.stat().st_size)


# ----- internal helpers -----


_VTT_TAG_RE = re.compile(r"<[^>]+>")
_VTT_TIMESTAMP_RE = re.compile(
    r"^(?P<start>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})(?:\s+.*)?$"
)
_BOM = "﻿"


def _fetch_caption_vtt(url: str, lang: str) -> str | None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": str(td_path / "%(id)s.%(ext)s"),
        }
        try:
            with YoutubeDL(cast(Any, opts)) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            raise ExtractorError("network", f"caption fetch failed for {url}: {e}") from e

        # Match all real-world shapes: bare, `-auto`, `-orig`, etc.
        candidates = sorted(td_path.glob(f"*.{lang}*.vtt"))
        if not candidates:
            return None

        # Prefer manual (no `-auto` suffix) over auto-generated when both exist.
        manual = [c for c in candidates if "-auto" not in c.name]
        chosen = manual[0] if manual else candidates[0]

        return chosen.read_text(encoding="utf-8")


def _duration_filter(info_dict: dict[str, Any]) -> str | None:
    """yt-dlp `match_filter` callable. Returns a reject reason or None."""
    duration = info_dict.get("duration")
    if isinstance(duration, int | float) and duration > MAX_VIDEO_DURATION_SECONDS:
        return (
            f"video too long ({int(duration)}s > {MAX_VIDEO_DURATION_SECONDS}s cap); "
            "livestreams not supported"
        )
    return None


def _parse_vtt(vtt_content: str) -> str:
    """Parse a VTT subtitle string into plain text.

    Strips: BOM, header (`WEBVTT`), notes, cue numbers, timestamps,
    inline tags (e.g. `<c>`, `<00:00:00.000>`), and rolling-window
    duplicate cues (YouTube auto-captions repeat the last line of cue
    N at the start of cue N+1 to animate the caption — strip the dup).
    Unescapes HTML entities (`&amp;`, `&#39;`, ...).

    Empty input returns an empty string.
    """
    cues = _parse_vtt_cues(vtt_content)
    lines: list[str] = []
    for cue in cues:
        cue_lines = cue.text.splitlines()
        for cleaned in cue_lines:
            # Rolling-window dedup: skip if identical to the previous emitted line.
            if lines and lines[-1] == cleaned:
                continue
            lines.append(cleaned)
    return "\n".join(lines)


def _parse_vtt_cues(vtt_content: str) -> list[CaptionCue]:
    """Parse a VTT subtitle string into cues with timestamp boundaries."""
    if vtt_content.startswith(_BOM):
        vtt_content = vtt_content[len(_BOM) :]

    cues: list[CaptionCue] = []
    current_start: str | None = None
    current_end: str | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_start, current_end, current_lines
        if current_start is None or current_end is None:
            current_lines = []
            return
        text = "\n".join(current_lines).strip()
        if text:
            cues.append(CaptionCue(start=current_start, end=current_end, text=text))
        current_start = None
        current_end = None
        current_lines = []

    for raw in vtt_content.splitlines():
        line = raw.strip()
        if not line:
            flush_current()
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        timestamp_match = _VTT_TIMESTAMP_RE.match(line)
        if timestamp_match:
            flush_current()
            current_start = timestamp_match.group("start")
            current_end = timestamp_match.group("end")
            continue
        # Cue numbers (lines that are pure integers).
        if line.isdigit():
            continue
        cleaned = html.unescape(_VTT_TAG_RE.sub("", line)).strip()
        if not cleaned:
            continue
        if current_start is not None:
            current_lines.append(cleaned)

    flush_current()
    return cues


def _format_cues_with_timestamps(cues: list[CaptionCue]) -> str:
    """Format cues as transcript text with readable start-time anchors."""
    return "\n".join(f"[{_timestamp_anchor(cue.start)}] {cue.text}" for cue in cues)


def _timestamp_anchor(timestamp: str) -> str:
    parts = timestamp.split(".")[0].split(":")
    if len(parts) == 3 and parts[0] == "00":
        return f"{parts[1]}:{parts[2]}"
    return ":".join(parts)
