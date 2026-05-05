"""Tests for vault_yt.extractor — yt-dlp boundary mocked for determinism."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vault_yt.extractor import (
    ExtractorError,
    _parse_vtt,
    download_audio,
    fetch_captions,
    fetch_meta,
)


# ============================================================
# fetch_meta
# ============================================================


def _ytdl_mock(extract_info_return: dict | None = None, *, side_effect=None):
    """Build a YoutubeDL mock whose extract_info returns the given dict."""
    ydl = MagicMock()
    ydl.__enter__.return_value = ydl
    ydl.__exit__.return_value = False
    if side_effect is not None:
        ydl.extract_info.side_effect = side_effect
    else:
        ydl.extract_info.return_value = extract_info_return
    cls = MagicMock(return_value=ydl)
    return cls, ydl


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_returns_expected_keys(mock_ytdl_class):
    cls, _ = _ytdl_mock(
        {
            "id": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "channel": "Rick Astley",
            "channel_url": "https://www.youtube.com/@RickAstleyYT",
            "upload_date": "20091025",
            "duration": 213,
            "subtitles": {"en": [{}]},
            "automatic_captions": {"en": [{}], "es": [{}]},
        }
    )
    mock_ytdl_class.side_effect = cls.side_effect or (lambda *a, **kw: cls.return_value)

    meta = fetch_meta("https://youtu.be/dQw4w9WgXcQ")

    assert meta["id"] == "dQw4w9WgXcQ"
    assert meta["title"] == "Never Gonna Give You Up"
    assert meta["channel"] == "Rick Astley"
    assert meta["channel_url"] == "https://www.youtube.com/@RickAstleyYT"
    assert meta["published_at"] == "2009-10-25"
    assert meta["duration_seconds"] == 213
    assert meta["captions"] == ["en", "es"]


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_handles_missing_optional_fields(mock_ytdl_class):
    cls, _ = _ytdl_mock({"id": "abc", "title": "Bare bones"})
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["id"] == "abc"
    assert meta["title"] == "Bare bones"
    assert meta["channel"] is None
    assert meta["channel_url"] is None
    assert meta["published_at"] is None
    assert meta["duration_seconds"] is None
    assert meta["captions"] == []


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_falls_back_to_uploader(mock_ytdl_class):
    """When `channel`/`channel_url` are absent, fall back to `uploader`/`uploader_url`."""
    cls, _ = _ytdl_mock(
        {
            "id": "abc",
            "title": "T",
            "uploader": "Some Channel",
            "uploader_url": "https://youtube.com/@Some",
        }
    )
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["channel"] == "Some Channel"
    assert meta["channel_url"] == "https://youtube.com/@Some"


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_dedupes_caption_langs(mock_ytdl_class):
    """Manual + auto captions in same lang collapse to a single entry."""
    cls, _ = _ytdl_mock(
        {
            "id": "abc",
            "title": "T",
            "subtitles": {"en": [{}]},
            "automatic_captions": {"en": [{}], "fr": [{}]},
        }
    )
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["captions"] == ["en", "fr"]


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_ignores_invalid_upload_date(mock_ytdl_class):
    """upload_date that's not 8 digits is ignored, not crashed on."""
    cls, _ = _ytdl_mock({"id": "abc", "title": "T", "upload_date": "garbage"})
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["published_at"] is None


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_on_extractor_failure(mock_ytdl_class):
    cls, _ = _ytdl_mock(side_effect=RuntimeError("video unavailable"))
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError, match="yt-dlp failed"):
        fetch_meta("https://youtu.be/badurl")


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_when_info_is_none(mock_ytdl_class):
    cls, _ = _ytdl_mock(None)
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError, match="no info"):
        fetch_meta("https://youtu.be/none")


# ============================================================
# fetch_captions
# ============================================================


def _ytdl_with_side_effect_writing_vtt(vtt_text: str, lang: str = "en", video_id: str = "abc"):
    """Build a YoutubeDL mock whose extract_info writes a VTT file to outtmpl's dir."""

    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            outtmpl = Path(opts["outtmpl"])
            target_dir = outtmpl.parent
            (target_dir / f"{video_id}.{lang}.vtt").write_text(vtt_text, encoding="utf-8")
            return {"id": video_id}

        ydl.extract_info = extract_info
        return ydl

    return factory


def _ytdl_writing_no_vtt():
    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False
        ydl.extract_info.return_value = {"id": "no-captions"}
        return ydl

    return factory


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_returns_text_when_present(mock_ytdl_class):
    vtt = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Hello world\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "Second line\n"
    )
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_vtt(vtt)

    text = fetch_captions("https://youtu.be/abc", lang="en")

    assert text is not None
    assert "Hello world" in text
    assert "Second line" in text
    assert "WEBVTT" not in text
    assert "-->" not in text


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_returns_none_when_absent(mock_ytdl_class):
    mock_ytdl_class.side_effect = _ytdl_writing_no_vtt()

    text = fetch_captions("https://youtu.be/no-captions", lang="en")

    assert text is None


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_uses_requested_lang(mock_ytdl_class):
    """If the requested lang has no VTT but other langs do, returns None."""
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_vtt(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n", lang="fr"
    )

    # Asking for English when only French was written.
    text = fetch_captions("https://youtu.be/fr", lang="en")
    assert text is None


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_raises_on_yt_dlp_error(mock_ytdl_class):
    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False
        ydl.extract_info.side_effect = RuntimeError("network")
        return ydl

    mock_ytdl_class.side_effect = factory

    with pytest.raises(ExtractorError, match="caption fetch failed"):
        fetch_captions("https://youtu.be/explode")


# ============================================================
# download_audio
# ============================================================


def _ytdl_writing_audio(video_id: str = "abc", ext: str = "m4a", size: int = 100):
    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            outtmpl = Path(opts["outtmpl"])
            target_dir = outtmpl.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            audio_file = target_dir / f"{video_id}.{ext}"
            audio_file.write_bytes(b"x" * size)
            return {"id": video_id}

        ydl.extract_info = extract_info
        return ydl

    return factory


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_returns_file_path(mock_ytdl_class, tmp_path: Path):
    mock_ytdl_class.side_effect = _ytdl_writing_audio()

    result = download_audio("https://youtu.be/abc", tmp_path)

    assert result.exists()
    assert result.name == "abc.m4a"
    assert result.parent == tmp_path


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_picks_largest_when_multiple_files(mock_ytdl_class, tmp_path: Path):
    """yt-dlp may write multiple format files; return the largest (the audio)."""

    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            (tmp_path / "abc.m4a").write_bytes(b"x" * 1000)
            (tmp_path / "abc.json").write_text("metadata")  # smaller sidecar
            return {"id": "abc"}

        ydl.extract_info = extract_info
        return ydl

    mock_ytdl_class.side_effect = factory

    result = download_audio("https://youtu.be/abc", tmp_path)

    assert result.name == "abc.m4a"


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_creates_dest_dir(mock_ytdl_class, tmp_path: Path):
    target = tmp_path / "deep" / "nested"
    mock_ytdl_class.side_effect = _ytdl_writing_audio()

    result = download_audio("https://youtu.be/abc", target)

    assert target.is_dir()
    assert result.parent == target


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_raises_on_yt_dlp_error(mock_ytdl_class, tmp_path: Path):
    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False
        ydl.extract_info.side_effect = RuntimeError("offline")
        return ydl

    mock_ytdl_class.side_effect = factory

    with pytest.raises(ExtractorError, match="audio download failed"):
        download_audio("https://youtu.be/dead", tmp_path)


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_raises_when_no_file_written(mock_ytdl_class, tmp_path: Path):
    """yt-dlp returned an id but no file landed → caller-visible error, not silent failure."""

    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            return {"id": "ghost"}  # no file written

        ydl.extract_info = extract_info
        return ydl

    mock_ytdl_class.side_effect = factory

    with pytest.raises(ExtractorError, match="audio file not found"):
        download_audio("https://youtu.be/ghost", tmp_path)


# ============================================================
# _parse_vtt (pure function; thoroughly covered)
# ============================================================


def test_parse_vtt_empty_returns_empty_string():
    assert _parse_vtt("") == ""


def test_parse_vtt_header_only_returns_empty_string():
    assert _parse_vtt("WEBVTT\n\n") == ""


def test_parse_vtt_strips_timestamps_and_returns_text():
    vtt = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Hello\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "World\n"
    )
    assert _parse_vtt(vtt) == "Hello\nWorld"


def test_parse_vtt_strips_cue_numbers():
    vtt = (
        "WEBVTT\n"
        "\n"
        "1\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "First cue\n"
        "\n"
        "2\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "Second cue\n"
    )
    assert _parse_vtt(vtt) == "First cue\nSecond cue"


def test_parse_vtt_strips_inline_tags():
    vtt = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "<c.color>Hello</c> <00:00:00.500>world\n"
    )
    assert _parse_vtt(vtt) == "Hello world"


def test_parse_vtt_strips_notes():
    vtt = (
        "WEBVTT\n"
        "\n"
        "NOTE this is a note\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Real text\n"
    )
    assert _parse_vtt(vtt) == "Real text"
