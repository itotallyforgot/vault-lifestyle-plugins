"""Tests for vault_yt.inputs — deterministic expansion with yt-dlp mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vault_yt.inputs import InputExpansionError, expand_input, expand_inputs


def _ytdl_mock(extract_info_return: dict | None = None, *, side_effect=None):
    ydl = MagicMock()
    ydl.__enter__.return_value = ydl
    ydl.__exit__.return_value = False
    if side_effect is not None:
        ydl.extract_info.side_effect = side_effect
    else:
        ydl.extract_info.return_value = extract_info_return
    return MagicMock(return_value=ydl), ydl


def test_single_video_url_expands_to_one_work_item() -> None:
    items = expand_input("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert len(items) == 1
    assert items[0].video_id == "dQw4w9WgXcQ"
    assert items[0].url == "https://youtu.be/dQw4w9WgXcQ"
    assert items[0].appearances[0].kind == "video"
    assert items[0].appearances[0].source == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@patch("vault_yt.inputs.YoutubeDL")
def test_playlist_url_expands_entries_in_yt_dlp_order(mock_ytdl_class) -> None:
    cls, _ = _ytdl_mock(
        {
            "id": "PL123",
            "title": "Playlist Title",
            "webpage_url": "https://www.youtube.com/playlist?list=PL123",
            "entries": [
                {"id": "video1111111", "url": "video1111111", "playlist_index": 1},
                {
                    "id": "video2222222",
                    "webpage_url": "https://www.youtube.com/watch?v=video2222222",
                    "playlist_index": 2,
                },
            ],
        }
    )
    mock_ytdl_class.return_value = cls.return_value

    items = expand_input("https://www.youtube.com/playlist?list=PL123")

    assert [item.video_id for item in items] == ["video1111111", "video2222222"]
    assert [item.appearances[0].playlist_index for item in items] == [1, 2]
    assert items[0].appearances[0].playlist_id == "PL123"
    assert items[0].appearances[0].playlist_title == "Playlist Title"


@patch("vault_yt.inputs.YoutubeDL")
def test_url_list_file_expands_non_empty_non_comment_lines_in_order(
    mock_ytdl_class, tmp_path: Path
) -> None:
    cls, _ = _ytdl_mock(
        {
            "id": "PL123",
            "title": "Playlist Title",
            "entries": [
                {"id": "playlistvid1", "playlist_index": 1},
                {"id": "playlistvid2", "playlist_index": 2},
            ],
        }
    )
    mock_ytdl_class.return_value = cls.return_value
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "\n"
        "# comment\n"
        "https://youtu.be/directvid1\n"
        "  https://www.youtube.com/playlist?list=PL123  \n",
        encoding="utf-8",
    )

    items = expand_input(url_file)

    assert [item.video_id for item in items] == ["directvid1", "playlistvid1", "playlistvid2"]
    assert items[0].appearances[0].source == str(url_file)
    assert items[0].appearances[0].line_number == 3
    assert items[1].appearances[0].line_number == 4


@patch("vault_yt.inputs.YoutubeDL")
def test_duplicate_videos_collapse_first_seen_and_preserve_appearances(
    mock_ytdl_class, tmp_path: Path
) -> None:
    cls, _ = _ytdl_mock(
        {
            "id": "PL123",
            "title": "Playlist Title",
            "entries": [
                {"id": "dupvideo01", "playlist_index": 1},
                {"id": "newvideo01", "playlist_index": 2},
            ],
        }
    )
    mock_ytdl_class.return_value = cls.return_value
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "https://youtu.be/dupvideo01\n"
        "https://www.youtube.com/playlist?list=PL123\n"
        "https://www.youtube.com/watch?v=dupvideo01\n",
        encoding="utf-8",
    )

    items = expand_input(url_file)

    assert [item.video_id for item in items] == ["dupvideo01", "newvideo01"]
    assert items[0].url == "https://youtu.be/dupvideo01"
    assert [appearance.kind for appearance in items[0].appearances] == [
        "video",
        "playlist",
        "video",
    ]
    assert [appearance.line_number for appearance in items[0].appearances] == [1, 2, 3]
    assert items[0].appearances[1].playlist_id == "PL123"


def test_expand_inputs_collapses_duplicates_across_inputs() -> None:
    items = expand_inputs(
        [
            "https://youtu.be/firstvideo",
            "https://www.youtube.com/watch?v=secondvideo",
            "https://www.youtube.com/watch?v=firstvideo",
        ]
    )

    assert [item.video_id for item in items] == ["firstvideo", "secondvideo"]
    assert len(items[0].appearances) == 2


def test_malformed_url_list_entry_reports_file_and_line(tmp_path: Path) -> None:
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "https://youtu.be/goodvideo\nnot a url\n",
        encoding="utf-8",
    )

    with pytest.raises(InputExpansionError) as exc_info:
        expand_input(url_file)

    assert exc_info.value.path == url_file
    assert exc_info.value.line_number == 2
    assert exc_info.value.entry == "not a url"
    assert "malformed url-list entry" in str(exc_info.value)


def test_non_youtube_url_is_rejected_cleanly() -> None:
    with pytest.raises(InputExpansionError) as exc_info:
        expand_input("https://example.com/watch?v=dQw4w9WgXcQ")

    assert "unsupported YouTube input" in str(exc_info.value)


@patch("vault_yt.inputs.YoutubeDL")
def test_playlist_yt_dlp_failure_is_wrapped(mock_ytdl_class) -> None:
    cls, _ = _ytdl_mock(side_effect=RuntimeError("network sad"))
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(InputExpansionError) as exc_info:
        expand_input("https://www.youtube.com/playlist?list=PL123")

    assert "yt-dlp failed for playlist" in str(exc_info.value)
