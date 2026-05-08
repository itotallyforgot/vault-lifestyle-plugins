"""Tests for the explicit yt-dlp cookie/browser handoff exporter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.cookies import SUPPORTED_BROWSERS

from vault_yt.handoff import read_handoff
from vault_yt.ytdlp_playlist_exporter import (
    BrowserSpecError,
    export_playlist_handoff,
    parse_browser_spec,
)


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


def _ytdl_mock(extract_info_return: dict):
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
    cls, _ = _ytdl_mock({"id": "PLENG", "entries": []})
    mock_ytdl_class.return_value = cls.return_value
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    export_playlist_handoff(
        "https://www.youtube.com/playlist?list=PLENG",
        tmp_path / "engineering.jsonl",
        cookies=cookies,
    )

    opts = mock_ytdl_class.call_args.args[0]
    assert opts["cookies"] == str(cookies)
    assert "cookiesfrombrowser" not in opts
