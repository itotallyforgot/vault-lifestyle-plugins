"""Date + ID anchored slug generator for `raw/<slug>.md` paths.

Slugs are deterministic, filesystem-safe, and start with the source date,
source kind, and YouTube video ID so that vault scans stay chronological
while title edits across re-runs never collide on existing files.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# Slug body cap — keeps total filename well under filesystem limits when
# combined with the video ID prefix and `.md` extension.
_TITLE_BODY_MAX = 60

_NON_SLUG_CHAR = re.compile(r"[^a-z0-9]+")
_TRIM_DASHES = re.compile(r"^-+|-+$")


def make(video_id: str, title: str, slug_date: date | datetime | str) -> str:
    """Build a YouTube slug `<yyyy-mm-dd>-youtube-<id>-<sanitized-title>`.

    Args:
        video_id: YouTube video ID (e.g. ``dQw4w9WgXcQ``). Must be non-empty
            after stripping.
        title: Source title. Sanitized to ASCII lowercase; non-Latin and
            punctuation runs collapse to single dashes.
        slug_date: Source date used as the filename prefix. Accepts a
            ``date``, ``datetime``, or ISO ``YYYY-MM-DD`` string.

    Returns:
        A slug containing only ``[a-z0-9-]``. If the title is empty or
        produces nothing extractable, returns ``video_id`` alone (no
        trailing dash).

    Raises:
        ValueError: when ``video_id`` is empty or whitespace-only.
    """
    vid = video_id.strip()
    if not vid:
        raise ValueError("video_id must be non-empty")

    prefix = f"{_coerce_slug_date(slug_date)}-youtube-{vid}"
    body = _sanitize_title(title)
    if not body:
        return prefix
    return f"{prefix}-{body}"


def _sanitize_title(title: str) -> str:
    """Lower-case ASCII-fold a title and reduce to filesystem-safe slug body."""
    # NFKD decomposes accented Latin into base + combining marks; strip the
    # marks to leave plain ASCII (e.g. "Café" → "Cafe"). Non-Latin scripts
    # (CJK, Cyrillic) decompose to themselves and get filtered out below.
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")

    lowered = ascii_only.lower()
    # Replace any run of non-[a-z0-9] with a single dash, then trim edges.
    dashed = _NON_SLUG_CHAR.sub("-", lowered)
    body = _TRIM_DASHES.sub("", dashed)

    if len(body) > _TITLE_BODY_MAX:
        body = body[:_TITLE_BODY_MAX]
        # Truncation may land on a dash — strip trailing dashes again.
        body = _TRIM_DASHES.sub("", body)

    return body


def _coerce_slug_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError("slug_date must be YYYY-MM-DD") from exc
    raise TypeError("slug_date must be a date, datetime, or YYYY-MM-DD string")
