"""yt-dlp wrapper: metadata, captions, and audio download for a YouTube URL.

Exposes three functions consumed by later slices:

- `fetch_meta(url)` — metadata dict (Slice 4 builder).
- `fetch_captions(url, lang)` — primary transcript path (Slice 5 CLI).
- `download_audio(url, dest_dir)` — Whisper input (Slice 3 fallback).

Caller never instantiates `YoutubeDL` directly. Tests mock at the
`yt_dlp.YoutubeDL` boundary.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class ExtractorError(RuntimeError):
    """Raised on failures specific to YouTube metadata / caption / audio extraction."""


# ----- public API -----


def fetch_meta(url: str) -> dict[str, Any]:
    """Fetch metadata for a YouTube URL.

    Returns a dict with the keys consumed by the writer (Slice 4):

    - `id`: YouTube video ID.
    - `title`: video title.
    - `channel`, `channel_url`: channel info (falls back to `uploader`/`uploader_url`).
    - `published_at`: ISO 8601 date string `YYYY-MM-DD` derived from yt-dlp's `upload_date` (`YYYYMMDD`); None if absent.
    - `duration_seconds`: int seconds; None if absent.
    - `captions`: sorted list[str] of available subtitle language codes (manual + auto-generated, deduped).
    """
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise ExtractorError(f"yt-dlp failed for {url}: {e}") from e

    if info is None:
        raise ExtractorError(f"yt-dlp returned no info for {url}")

    manual_langs = set((info.get("subtitles") or {}).keys())
    auto_langs = set((info.get("automatic_captions") or {}).keys())
    captions = sorted(manual_langs | auto_langs)

    upload_date = info.get("upload_date")
    published_at: str | None = None
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "published_at": published_at,
        "duration_seconds": info.get("duration"),
        "captions": captions,
    }


def fetch_captions(url: str, lang: str = "en") -> str | None:
    """Fetch captions for `url` in language `lang` and return plain transcript text.

    Tries manual subtitles first (yt-dlp prefers them when both are
    requested); falls back to auto-generated for the same language.
    Returns None if neither is available in `lang`.

    The VTT file is downloaded into a temp directory that is cleaned up
    on return; only the parsed text leaves the function.
    """
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
            with YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            raise ExtractorError(f"caption fetch failed for {url}: {e}") from e

        candidates = sorted(td_path.glob(f"*.{lang}.vtt"))
        if not candidates:
            return None

        return _parse_vtt(candidates[0].read_text(encoding="utf-8"))


def download_audio(url: str, dest_dir: Path) -> Path:
    """Download the smallest audio stream for `url` into `dest_dir`.

    Returns the path to the downloaded audio file. Used as Whisper input
    when captions are absent. Caller is responsible for cleaning up
    `dest_dir` after Whisper finishes.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        # Prefer m4a (smallest, Whisper-friendly); fall back to whatever bestaudio is.
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise ExtractorError(f"audio download failed for {url}: {e}") from e

    if info is None:
        raise ExtractorError(f"yt-dlp returned no info for audio at {url}")

    video_id = info.get("id")
    if not video_id:
        raise ExtractorError(f"yt-dlp returned info without id for {url}")

    matches = list(dest_dir.glob(f"{video_id}.*"))
    if not matches:
        raise ExtractorError(f"audio file not found for {video_id} in {dest_dir}")

    # Multiple format files may be written; return the largest (the actual audio).
    return max(matches, key=lambda p: p.stat().st_size)


# ----- internal helpers -----


_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _parse_vtt(vtt_content: str) -> str:
    """Parse a VTT subtitle string into plain text.

    Strips header (`WEBVTT`), notes, cue numbers, timestamps, and inline
    tags (e.g. `<c>`, `<00:00:00.000>`). Joins remaining text lines with
    newlines. Empty input returns an empty string.
    """
    lines: list[str] = []
    for raw in vtt_content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if "-->" in line:
            continue
        # Cue numbers (lines that are pure integers).
        if line.isdigit():
            continue
        cleaned = _VTT_TAG_RE.sub("", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)
