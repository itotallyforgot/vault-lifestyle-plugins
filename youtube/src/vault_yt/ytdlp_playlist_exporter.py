"""Explicit yt-dlp playlist exporter for external handoff files."""

from __future__ import annotations

import json
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


class PlaylistEnumerationError(RuntimeError):
    """Raised when a playlist export cannot be proven complete.

    A bulk enumerator must fail closed: a failed resolve, a missing
    authoritative count, or a record total that does not match the count are
    all incomplete enumerations. Emitting an empty/partial handoff and exiting
    0 is never acceptable — "0 new" must never be able to mean "export failed".

    Plain ``RuntimeError`` subclass (not a frozen dataclass like
    ``BrowserSpecError``): an exception must be able to carry a ``__traceback__``
    as it propagates, and a frozen dataclass blocks that assignment
    (``FrozenInstanceError``) the moment it travels uncaught through click/typer.
    """


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
    # Invalidate any prior export to this path up front. A failed/partial
    # resolve below raises before re-writing, so without this a stale
    # `complete: true` handoff + sidecar from an earlier successful run would
    # silently survive and be mistaken for THIS run's result.
    _clear_prior_export(output_path)

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
        raise PlaylistEnumerationError(
            f"playlist enumeration failed for {playlist_url}: yt-dlp returned no "
            "playlist info (private/unavailable, or missing/expired cookies?)"
        )
    info = cast("dict[str, Any]", sanitized)

    # Authoritative total. yt-dlp reports the true playlist_count even under a
    # fetch cap; n_entries is None in flat mode, so it must not be used here.
    playlist_count = info.get("playlist_count")
    raw_entries = info.get("entries")
    entries = raw_entries if isinstance(raw_entries, list) else []
    # enumerated = every item yt-dlp paged through (the completeness signal).
    # records = the subset that resolved to a usable video_id; deleted/private
    # members enumerate but carry no id, so records <= enumerated is normal and
    # must NOT trip the completeness gate.
    enumerated = len(entries)
    records = _records_from_playlist(info, playlist_url=playlist_url, provider=provider)

    if not isinstance(playlist_count, int):
        raise PlaylistEnumerationError(
            f"playlist enumeration for {playlist_url} returned no authoritative "
            "playlist_count; cannot prove the export is complete"
        )
    if enumerated != playlist_count:
        raise PlaylistEnumerationError(
            f"incomplete playlist enumeration for {playlist_url}: paged "
            f"{enumerated} of {playlist_count} items "
            "(pagination truncated, or a partial/failed resolve?)"
        )

    handoff_path = write_handoff(output_path, records)
    _write_meta_sidecar(
        output_path,
        playlist_url=playlist_url,
        info=info,
        provider=provider,
        expected_count=playlist_count,
        enumerated_count=enumerated,
        actual_count=len(records),
    )
    return handoff_path


def meta_sidecar_path(output_path: Path) -> Path:
    """Path of the completeness sidecar written beside a handoff file."""
    return output_path.with_name(output_path.name + ".meta.json")


def _clear_prior_export(output_path: Path) -> None:
    """Remove a prior handoff + its completeness sidecar at this path.

    Called at the start of an export so a failed/incomplete resolve (which
    raises before re-writing) cannot leave a previous run's ``complete: true``
    artifacts behind to be mistaken for the current run. Only the handoff and
    its own ``.meta.json`` sidecar are touched, never sibling files.
    """
    for path in (output_path, meta_sidecar_path(output_path)):
        path.unlink(missing_ok=True)


def _write_meta_sidecar(
    output_path: Path,
    *,
    playlist_url: str,
    info: dict[str, Any],
    provider: str,
    expected_count: int,
    enumerated_count: int,
    actual_count: int,
) -> Path:
    """Write the playlist-level completeness sidecar next to the handoff.

    Carries only playlist provenance and counts, never credentials. ``complete``
    is always True here because ``export_playlist_handoff`` raises before this
    point on any incomplete enumeration; the field exists so a third-party
    adapter emitting its own sidecar can record ``false``, and so downstream
    asserts on one stable key regardless of which adapter produced the handoff.
    """
    meta = {
        "playlist_url": _string_or_none(info.get("webpage_url")) or playlist_url,
        "playlist_id": _string_or_none(info.get("id")),
        "playlist_title": _string_or_none(info.get("title")),
        "source_provider": provider,
        "expected_count": expected_count,
        "enumerated_count": enumerated_count,
        "actual_count": actual_count,
        "complete": True,
    }
    meta_path = meta_sidecar_path(output_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return meta_path


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
