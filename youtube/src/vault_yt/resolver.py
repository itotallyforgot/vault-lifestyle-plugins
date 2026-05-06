"""Decide which transcript source to use for a given video + language.

Pure function — no I/O, no yt-dlp, no Whisper. Reads the dict produced by
`extractor.fetch_meta` and returns either `"captions"` or `"whisper"`.
The CLI (Slice 5) then dispatches to `extractor.fetch_captions` or
`whisper_fallback.transcribe_audio` accordingly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

TranscriptSource = Literal["captions", "whisper"]


def choose_transcript_source(
    meta: Mapping[str, Any],
    *,
    lang: str = "en",
    force_whisper: bool = False,
) -> TranscriptSource:
    """Pick the transcript source for `lang` given a `fetch_meta`-shape dict.

    Decision:

    1. `force_whisper=True` → always `whisper` (CLI's `--force-whisper`).
    2. `lang` is in `meta["caption_kinds"]` → `captions` (preferred path).
    3. Legacy fallback: `lang` in `meta["captions"]` (the older list-shape) → `captions`.
    4. Otherwise → `whisper`.

    The legacy fallback exists for callers that pass minimal meta dicts
    (e.g., tests, future external consumers) without `caption_kinds`. The
    list `captions` field is the source of truth in that case.
    """
    if force_whisper:
        return "whisper"

    caption_kinds = meta.get("caption_kinds") or {}
    if lang in caption_kinds:
        return "captions"

    captions = meta.get("captions") or []
    if lang in captions:
        return "captions"

    return "whisper"
