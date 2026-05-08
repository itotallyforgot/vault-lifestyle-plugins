"""Tests for external playlist handoff JSONL parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vault_yt.handoff import HandoffError, read_handoff


def test_read_handoff_jsonl_dedupes_and_preserves_playlist_appearances(tmp_path: Path) -> None:
    handoff = tmp_path / "engineering.jsonl"
    handoff.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "video_id": "abc123",
                        "title": "First Video",
                        "source_provider": "yt-dlp-cookies",
                        "playlist_id": "PLENG",
                        "playlist_title": "Engineering",
                        "playlist_url": "https://www.youtube.com/playlist?list=PLENG",
                        "playlist_index": 1,
                    }
                ),
                json.dumps(
                    {
                        "url": "https://www.youtube.com/watch?v=def456",
                        "title": "Second Video",
                        "source_provider": "youtube-mcp",
                        "playlist_id": "PLENG",
                        "playlist_title": "Engineering",
                        "playlist_index": 2,
                    }
                ),
                json.dumps(
                    {
                        "video_id": "abc123",
                        "url": "https://youtu.be/abc123",
                        "source_provider": "manual-review",
                        "playlist_id": "PLOTHER",
                        "playlist_title": "Other",
                        "playlist_index": 7,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    items = read_handoff(handoff)

    assert [item.video_id for item in items] == ["abc123", "def456"]
    assert items[0].url == "https://youtu.be/abc123"
    assert items[0].title == "First Video"
    assert [appearance.source_provider for appearance in items[0].appearances] == [
        "yt-dlp-cookies",
        "manual-review",
    ]
    assert [appearance.playlist_title for appearance in items[0].appearances] == [
        "Engineering",
        "Other",
    ]
    assert items[1].appearances[0].playlist_index == 2
    assert items[1].appearances[0].line_number == 2


def test_read_handoff_reports_jsonl_line_errors(tmp_path: Path) -> None:
    handoff = tmp_path / "bad.jsonl"
    handoff.write_text('{"video_id": "abc123"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(HandoffError) as exc_info:
        read_handoff(handoff)

    assert exc_info.value.path == handoff
    assert exc_info.value.line_number == 2
    assert "malformed handoff JSON" in str(exc_info.value)


def test_read_handoff_requires_video_id_or_youtube_url(tmp_path: Path) -> None:
    handoff = tmp_path / "bad.jsonl"
    handoff.write_text(json.dumps({"title": "No ID"}) + "\n", encoding="utf-8")

    with pytest.raises(HandoffError) as exc_info:
        read_handoff(handoff)

    assert exc_info.value.line_number == 1
    assert "video_id or YouTube url" in str(exc_info.value)
