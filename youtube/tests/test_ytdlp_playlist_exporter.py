"""Tests for the explicit yt-dlp cookie/browser handoff exporter."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from yt_dlp import YoutubeDL
from yt_dlp.cookies import SUPPORTED_BROWSERS

from vault_yt.handoff import read_handoff
from vault_yt.ytdlp_playlist_exporter import (
    BrowserSpecError,
    PlaylistEnumerationError,
    export_playlist_handoff,
    parse_browser_spec,
)


def _documented_youtubedl_params() -> set[str]:
    """Real YoutubeDL option names, parsed from its `__init__` param docstring.

    yt-dlp documents each accepted programmatic option as a column-aligned
    ``name:  description`` line in the ``YoutubeDL`` class docstring. The leading
    indentation has shifted across yt-dlp releases (e.g. it was 4-space indented
    historically and dedented to column 0 by 2026.6.9), so this matches any
    leading indent and keys off the snake_case name plus the 2+ aligned spaces
    after the colon. Anything not in this set is silently ignored by yt-dlp at
    runtime.
    """
    doc = YoutubeDL.__doc__ or ""
    names: set[str] = set()
    for line in doc.splitlines():
        match = re.match(r"^\s*([a-z_][a-z0-9_]*):\s{2,}\S", line)
        if match:
            names.add(match.group(1))
    return names


@pytest.mark.parametrize("browser", sorted(SUPPORTED_BROWSERS))
def test_parse_browser_spec_accepts_every_yt_dlp_supported_browser(browser: str) -> None:
    assert parse_browser_spec(browser)[0] == browser


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("chrome:Default", ("chrome", "Default", None, None)),
        ("firefox::work", ("firefox", None, None, "work")),
        ("brave:Profile 1::youtube", ("brave", "Profile 1", None, "youtube")),
    ],
)
def test_parse_browser_spec_accepts_profile_and_container_styles(
    spec: str, expected: tuple[str, str | None, str | None, str | None]
) -> None:
    assert parse_browser_spec(spec) == expected


def test_parse_browser_spec_accepts_supported_keyring() -> None:
    browser, profile, keyring, container = parse_browser_spec("chrome+kwallet:Default")

    assert browser == "chrome"
    assert profile == "Default"
    assert keyring == "KWALLET"
    assert container is None


def test_parse_browser_spec_rejects_unknown_browser() -> None:
    with pytest.raises(BrowserSpecError, match="unsupported browser"):
        parse_browser_spec("netscape")


def _ytdl_mock(extract_info_return: dict | None):
    ydl = MagicMock()
    ydl.__enter__.return_value = ydl
    ydl.__exit__.return_value = False
    ydl.extract_info.return_value = extract_info_return
    ydl.sanitize_info.side_effect = lambda info: json.loads(json.dumps(info))
    return MagicMock(return_value=ydl), ydl


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_playlist_handoff_writes_jsonl_from_browser_auth(
    mock_ytdl_class, tmp_path: Path
) -> None:
    cls, ydl = _ytdl_mock(
        {
            "id": "PLENG",
            "title": "Engineering",
            "webpage_url": "https://www.youtube.com/playlist?list=PLENG",
            "playlist_count": 1,
            "entries": [
                {
                    "id": "abc123",
                    "title": "First",
                    "url": "abc123",
                    "playlist_index": 1,
                    "channel": "Example",
                    "channel_url": "https://www.youtube.com/@example",
                }
            ],
        }
    )
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    export_playlist_handoff(
        "https://www.youtube.com/playlist?list=PLENG",
        output,
        browser="chrome:Default",
        verbose=True,
    )

    assert mock_ytdl_class.call_args.args[0]["extract_flat"] is True
    assert mock_ytdl_class.call_args.args[0]["cookiesfrombrowser"] == (
        "chrome",
        "Default",
        None,
        None,
    )
    ydl.extract_info.assert_called_once_with(
        "https://www.youtube.com/playlist?list=PLENG", download=False
    )
    items = read_handoff(output)
    assert items[0].video_id == "abc123"
    assert items[0].title == "First"
    assert items[0].appearances[0].source_provider == "yt-dlp-browser"
    assert items[0].appearances[0].playlist_title == "Engineering"


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_playlist_handoff_uses_cookie_file_when_provided(
    mock_ytdl_class, tmp_path: Path
) -> None:
    cls, _ = _ytdl_mock({"id": "PLENG", "playlist_count": 0, "entries": []})
    mock_ytdl_class.return_value = cls.return_value
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    export_playlist_handoff(
        "https://www.youtube.com/playlist?list=PLENG",
        tmp_path / "engineering.jsonl",
        cookies=cookies,
    )

    opts = mock_ytdl_class.call_args.args[0]
    assert opts["cookiefile"] == str(cookies)
    assert "cookies" not in opts
    assert "cookiesfrombrowser" not in opts


def test_documented_param_parser_finds_real_cookie_options() -> None:
    """Guard the parser itself: known-real options present, bogus ones absent.

    If yt-dlp ever reshapes its docstring and this set comes back empty, the
    parity test below would vacuously pass — so assert the parser has teeth.
    """
    params = _documented_youtubedl_params()
    assert "cookiefile" in params
    assert "cookiesfrombrowser" in params
    assert "extract_flat" in params
    # `cookies` is NOT a real YoutubeDL option — it was the original L1 bug.
    assert "cookies" not in params


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="public"),
        pytest.param({"cookies": "COOKIE_PATH"}, id="cookiefile"),
        pytest.param({"browser": "chrome:Default"}, id="browser"),
    ],
)
@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_every_opts_key_is_a_real_youtubedl_param(
    mock_ytdl_class, tmp_path: Path, kwargs: dict[str, Any]
) -> None:
    """Parity guard: every option key the exporter hands YoutubeDL must be a
    real, documented parameter. A silently-ignored key (the L1 `cookies`
    no-op) would fail here regardless of which auth mode set it."""
    cls, _ = _ytdl_mock({"id": "PLENG", "playlist_count": 0, "entries": []})
    mock_ytdl_class.return_value = cls.return_value

    call_kwargs = dict(kwargs)
    if "cookies" in call_kwargs:
        cookie_path = tmp_path / "cookies.txt"
        cookie_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        call_kwargs["cookies"] = cookie_path

    export_playlist_handoff(
        "https://www.youtube.com/playlist?list=PLENG",
        tmp_path / "engineering.jsonl",
        **call_kwargs,
    )

    opts = mock_ytdl_class.call_args.args[0]
    documented = _documented_youtubedl_params()
    unknown = set(opts) - documented
    assert not unknown, f"exporter set non-YoutubeDL opts keys: {sorted(unknown)}"


# ---------------------------------------------------------------------------
# Fail-closed enumeration guard (empty/partial must never report as success).
# A bulk enumerator must verify records against the authoritative total and
# raise on any incomplete/failed resolve — never write an empty handoff and
# return as if it succeeded.
# ---------------------------------------------------------------------------


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_raises_on_resolve_failure_instead_of_empty_success(
    mock_ytdl_class, tmp_path: Path
) -> None:
    """A private playlist with no/expired cookies makes yt-dlp (under
    ignoreerrors) return None. The exporter must raise, not write an empty
    handoff and return its path."""
    cls, _ = _ytdl_mock(None)
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    with pytest.raises(PlaylistEnumerationError):
        export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    assert not output.exists(), "no handoff file may be written on resolve failure"


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_raises_when_count_positive_but_zero_records(
    mock_ytdl_class, tmp_path: Path
) -> None:
    """yt-dlp reports an authoritative count but returns no entries (a partial
    auth/resolve masquerade). 0 records for a non-zero playlist is a failed
    enumeration, not an empty playlist."""
    cls, _ = _ytdl_mock({"id": "PLENG", "playlist_count": 5, "entries": []})
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    with pytest.raises(PlaylistEnumerationError):
        export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    assert not output.exists()


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_raises_on_truncated_enumeration(mock_ytdl_class, tmp_path: Path) -> None:
    """Pagination truncation: yt-dlp reports 166 total but only 3 entries came
    back. YouTube orders playlists date-added-ascending, so the dropped tail is
    exactly the newest videos — the silent-truncation failure this guard exists
    to catch."""
    entries = [
        {"id": f"vid{n:08d}", "title": f"v{n}", "url": f"vid{n:08d}", "playlist_index": n}
        for n in range(1, 4)
    ]
    cls, _ = _ytdl_mock({"id": "PLENG", "playlist_count": 166, "entries": entries})
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    with pytest.raises(PlaylistEnumerationError, match="3 of 166"):
        export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    assert not output.exists()


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_raises_when_count_is_missing(mock_ytdl_class, tmp_path: Path) -> None:
    """No authoritative playlist_count means completeness cannot be proven.
    Fail closed rather than trust an unverifiable enumeration."""
    entries = [{"id": "abc123", "title": "First", "url": "abc123", "playlist_index": 1}]
    cls, _ = _ytdl_mock({"id": "PLENG", "entries": entries})  # no playlist_count
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    with pytest.raises(PlaylistEnumerationError, match="no authoritative playlist_count"):
        export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    assert not output.exists()


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_accepts_genuinely_empty_playlist(mock_ytdl_class, tmp_path: Path) -> None:
    """A real empty playlist (count 0, no entries) is complete, not a failure.
    0 == 0, so the guard must NOT raise; it writes an empty handoff."""
    cls, _ = _ytdl_mock({"id": "PLENG", "playlist_count": 0, "entries": []})
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    assert output.exists()
    assert read_handoff(output) == []


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_tolerates_deleted_members_without_false_truncation(
    mock_ytdl_class, tmp_path: Path
) -> None:
    """A complete playlist can contain deleted/private members that enumerate
    with no video_id. Those are paged (so completeness holds: enumerated ==
    count) but skipped as records. The guard must compare enumerated entries to
    the count, not resolved records — otherwise a complete export false-fails."""
    entries = [
        {"id": "abc123", "title": "Live one", "url": "abc123", "playlist_index": 1},
        {"title": "[Deleted video]", "playlist_index": 2},  # no id, no usable url
    ]
    cls, _ = _ytdl_mock({"id": "PLENG", "playlist_count": 2, "entries": entries})
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    items = read_handoff(output)
    assert [i.video_id for i in items] == ["abc123"]  # the deleted member is dropped


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_export_writes_count_meta_sidecar_on_success(mock_ytdl_class, tmp_path: Path) -> None:
    """A successful export emits a `<output>.meta.json` sidecar recording the
    authoritative expected count, how many items were enumerated, how many
    resolved to usable videos, and complete:true. Downstream asserts on this
    instead of re-deriving completeness. The sidecar carries only playlist
    provenance + counts — never credentials."""
    entries = [
        {"id": "abc123", "title": "One", "url": "abc123", "playlist_index": 1},
        {"title": "[Deleted video]", "playlist_index": 2},  # enumerated, not a record
    ]
    cls, _ = _ytdl_mock(
        {"id": "PLENG", "title": "Engineering", "playlist_count": 2, "entries": entries}
    )
    mock_ytdl_class.return_value = cls.return_value
    output = tmp_path / "engineering.jsonl"

    export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)

    meta_path = Path(str(output) + ".meta.json")
    assert meta_path.exists(), "successful export must write a .meta.json sidecar"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["expected_count"] == 2
    assert meta["enumerated_count"] == 2
    assert meta["actual_count"] == 1
    assert meta["complete"] is True
    assert meta["playlist_id"] == "PLENG"


@patch("vault_yt.ytdlp_playlist_exporter.YoutubeDL")
def test_failed_reexport_does_not_leave_stale_complete_artifacts(
    mock_ytdl_class, tmp_path: Path
) -> None:
    """Re-exporting to a path that already holds a prior SUCCESSFUL export must
    not let the stale complete:true handoff + sidecar survive a later FAILED
    resolve. Otherwise 'export failed' silently masquerades as the prior run's
    success — a stale success mistaken for the current run."""
    output = tmp_path / "engineering.jsonl"
    meta = Path(str(output) + ".meta.json")

    # Run 1: a clean success leaves a complete:true handoff + sidecar.
    cls, _ = _ytdl_mock(
        {
            "id": "PLENG",
            "playlist_count": 1,
            "entries": [{"id": "abc123", "url": "abc123", "playlist_index": 1}],
        }
    )
    mock_ytdl_class.return_value = cls.return_value
    export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)
    assert output.exists() and meta.exists()
    assert json.loads(meta.read_text(encoding="utf-8"))["complete"] is True

    # Run 2: same output path, resolve now fails (e.g. expired cookies).
    cls2, _ = _ytdl_mock(None)
    mock_ytdl_class.return_value = cls2.return_value
    with pytest.raises(PlaylistEnumerationError):
        export_playlist_handoff("https://www.youtube.com/playlist?list=PLENG", output)

    # The prior run's success artifacts must NOT survive the failed re-export.
    assert not meta.exists(), "stale complete:true sidecar survived a failed re-export"
    assert not output.exists(), "stale handoff survived a failed re-export"
