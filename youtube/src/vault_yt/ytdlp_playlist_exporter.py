"""Explicit yt-dlp playlist exporter for external handoff files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS

from vault_yt.handoff import HandoffRecord, write_handoff


@dataclass(frozen=True)
class BrowserSpecError(ValueError):
    """Raised when a browser cookie source is not supported by yt-dlp."""

    message: str

    def __str__(self) -> str:
        return self.message


def parse_browser_spec(spec: str) -> tuple[str, str | None, str | None, str | None]:
    """Parse yt-dlp's BROWSER[+KEYRING][:PROFILE][::CONTAINER] style."""
    match = re.fullmatch(
        r"""(?x)
        (?P<name>[^+:]+)
        (?:\s*\+\s*(?P<keyring>[^:]+))?
        (?:\s*:\s*(?!:)(?P<profile>.+?))?
        (?:\s*::\s*(?P<container>.+))?
        """,
        spec,
    )
    if match is None:
        raise BrowserSpecError(f"invalid browser cookie spec: {spec}")

    browser_name, keyring, profile, container = match.group(
        "name", "keyring", "profile", "container"
    )
    browser_name = browser_name.lower()
    if browser_name not in SUPPORTED_BROWSERS:
        raise BrowserSpecError(
            f"unsupported browser specified for cookies: {browser_name}. "
            f"Supported browsers are: {', '.join(sorted(SUPPORTED_BROWSERS))}"
        )

    if keyring is not None:
        keyring = keyring.upper()
        if keyring not in SUPPORTED_KEYRINGS:
            raise BrowserSpecError(
                f"unsupported keyring specified for cookies: {keyring}. "
                f"Supported keyrings are: {', '.join(sorted(SUPPORTED_KEYRINGS))}"
            )
    return browser_name, profile, keyring, container


def export_playlist_handoff(
    playlist_url: str,
    output_path: Path,
    *,
    browser: str | None = None,
    cookies: Path | None = None,
    verbose: bool = False,
) -> Path:
    """Export a playlist into the repo-owned handoff JSONL schema."""
    opts: dict[str, Any] = {
        "ignoreerrors": "only_download",
        "extract_flat": True,
        "quiet": not verbose,
        "no_warnings": not verbose,
        "skip_download": True,
    }
    provider = "yt-dlp-public"
    if cookies is not None:
        # yt-dlp's programmatic option is `cookiefile`, not `cookies`. The
        # latter is silently ignored, so the export would run unauthenticated
        # while stamping source_provider as cookie-authenticated.
        opts["cookiefile"] = str(cookies)
        provider = "yt-dlp-cookies"
    elif browser is not None:
        opts["cookiesfrombrowser"] = parse_browser_spec(browser)
        provider = "yt-dlp-browser"

    with YoutubeDL(cast(Any, opts)) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        sanitized = ydl.sanitize_info(info)

    if not isinstance(sanitized, dict):
        records: list[HandoffRecord] = []
    else:
        records = _records_from_playlist(sanitized, playlist_url=playlist_url, provider=provider)
    return write_handoff(output_path, records)


def _records_from_playlist(
    info: dict[str, Any], *, playlist_url: str, provider: str
) -> list[HandoffRecord]:
    entries = info.get("entries") or []
    if not isinstance(entries, list):
        return []

    playlist_id = _string_or_none(info.get("id"))
    playlist_title = _string_or_none(info.get("title"))
    playlist_webpage_url = _string_or_none(info.get("webpage_url")) or playlist_url
    records: list[HandoffRecord] = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        video_id = _string_or_none(entry.get("id")) or _video_id_from_url(entry)
        if video_id is None:
            continue
        playlist_index = entry.get("playlist_index")
        records.append(
            HandoffRecord(
                video_id=video_id,
                url=_entry_url(entry, video_id),
                title=_string_or_none(entry.get("title")),
                source_provider=provider,
                playlist_id=playlist_id,
                playlist_title=playlist_title,
                playlist_url=playlist_webpage_url,
                playlist_index=playlist_index if isinstance(playlist_index, int) else position,
                channel=_string_or_none(entry.get("channel")),
                channel_url=_string_or_none(entry.get("channel_url")),
            )
        )
    return records


def _video_id_from_url(entry: dict[str, Any]) -> str | None:
    value = _string_or_none(entry.get("url")) or _string_or_none(entry.get("webpage_url"))
    if value and not value.startswith(("http://", "https://")):
        return value
    return None


def _entry_url(entry: dict[str, Any], video_id: str) -> str:
    for key in ("webpage_url", "url"):
        value = _string_or_none(entry.get(key))
        if value and value.startswith(("http://", "https://")):
            return value
    return f"https://youtu.be/{video_id}"


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
