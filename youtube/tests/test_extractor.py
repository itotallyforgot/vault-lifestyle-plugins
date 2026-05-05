"""Tests for vault_yt.extractor — yt-dlp boundary mocked for determinism."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vault_yt.extractor import (
    MAX_AUDIO_FILESIZE_BYTES,
    MAX_VIDEO_DURATION_SECONDS,
    ExtractorError,
    _duration_filter,
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
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/dQw4w9WgXcQ")

    assert meta["id"] == "dQw4w9WgXcQ"
    assert meta["title"] == "Never Gonna Give You Up"
    assert meta["channel"] == "Rick Astley"
    assert meta["channel_url"] == "https://www.youtube.com/@RickAstleyYT"
    assert meta["published_at"] == date(2009, 10, 25)
    assert isinstance(meta["published_at"], date)
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


# ----- caption_kinds (manual-vs-auto per-lang map; resolver consumer) -----


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_caption_kinds_manual_only(mock_ytdl_class):
    cls, _ = _ytdl_mock(
        {"id": "abc", "title": "T", "subtitles": {"en": [{}]}}
    )
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["caption_kinds"] == {"en": "manual"}


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_caption_kinds_auto_only(mock_ytdl_class):
    cls, _ = _ytdl_mock(
        {"id": "abc", "title": "T", "automatic_captions": {"en": [{}]}}
    )
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["caption_kinds"] == {"en": "auto"}


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_caption_kinds_manual_wins_over_auto(mock_ytdl_class):
    """When the same lang has both manual and auto, manual wins."""
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

    assert meta["caption_kinds"] == {"en": "manual", "fr": "auto"}


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_caption_kinds_empty_when_no_captions(mock_ytdl_class):
    cls, _ = _ytdl_mock({"id": "abc", "title": "T"})
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["caption_kinds"] == {}


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_returns_published_at_as_date_object(mock_ytdl_class):
    """published_at is a `datetime.date`, not a string — keeps the type contract
    explicit at the boundary instead of relying on Pydantic coercion downstream."""
    cls, _ = _ytdl_mock(
        {"id": "abc", "title": "T", "upload_date": "20091025"}
    )
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert isinstance(meta["published_at"], date)
    assert meta["published_at"] == date(2009, 10, 25)


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_ignores_invalid_upload_date(mock_ytdl_class):
    """upload_date that's not 8 digits is ignored, not crashed on."""
    cls, _ = _ytdl_mock({"id": "abc", "title": "T", "upload_date": "garbage"})
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["published_at"] is None


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_ignores_impossible_upload_date(mock_ytdl_class):
    """upload_date with valid digit count but impossible date silently drops."""
    cls, _ = _ytdl_mock(
        {"id": "abc", "title": "T", "upload_date": "20211332"}  # month 13
    )
    mock_ytdl_class.return_value = cls.return_value

    meta = fetch_meta("https://youtu.be/abc")

    assert meta["published_at"] is None


# ----- failure-mode tests with kind discriminator -----


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_network_kind_on_extractor_failure(mock_ytdl_class):
    cls, _ = _ytdl_mock(side_effect=RuntimeError("video unavailable"))
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError) as exc_info:
        fetch_meta("https://youtu.be/badurl")

    assert exc_info.value.kind == "network"
    assert "yt-dlp failed" in str(exc_info.value)


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_no_info_kind_when_info_is_none(mock_ytdl_class):
    cls, _ = _ytdl_mock(None)
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError) as exc_info:
        fetch_meta("https://youtu.be/none")

    assert exc_info.value.kind == "no_info"


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_no_info_kind_when_id_missing(mock_ytdl_class):
    """Non-empty id is required at the boundary, not silently passed through."""
    cls, _ = _ytdl_mock({"id": None, "title": "T"})
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError) as exc_info:
        fetch_meta("https://youtu.be/no-id")

    assert exc_info.value.kind == "no_info"
    assert "id" in str(exc_info.value)


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_no_info_kind_when_id_empty_string(mock_ytdl_class):
    cls, _ = _ytdl_mock({"id": "", "title": "T"})
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError) as exc_info:
        fetch_meta("https://youtu.be/empty-id")

    assert exc_info.value.kind == "no_info"


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_meta_raises_no_info_kind_when_title_missing(mock_ytdl_class):
    cls, _ = _ytdl_mock({"id": "abc", "title": None})
    mock_ytdl_class.return_value = cls.return_value

    with pytest.raises(ExtractorError) as exc_info:
        fetch_meta("https://youtu.be/no-title")

    assert exc_info.value.kind == "no_info"
    assert "title" in str(exc_info.value)


# ============================================================
# fetch_captions
# ============================================================


def _ytdl_with_side_effect_writing_files(filename_to_content: dict[str, str]):
    """Build a YoutubeDL mock whose extract_info writes the given files into outtmpl's dir."""

    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            outtmpl = Path(opts["outtmpl"])
            target_dir = outtmpl.parent
            for name, content in filename_to_content.items():
                (target_dir / name).write_text(content, encoding="utf-8")
            # video id derived from first key for return-info determinism
            return {"id": next(iter(filename_to_content)).split(".")[0]}

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
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_files(
        {"abc.en.vtt": vtt}
    )

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
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_files(
        {"abc.fr.vtt": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nBonjour\n"}
    )

    text = fetch_captions("https://youtu.be/fr", lang="en")
    assert text is None


# ----- new tests covering real-world yt-dlp filename shapes (P0-1) -----


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_handles_auto_suffix(mock_ytdl_class):
    """yt-dlp writes auto-captions as `<id>.<lang>-auto.vtt` — must match."""
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nAuto text\n"
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_files(
        {"abc.en-auto.vtt": vtt}
    )

    text = fetch_captions("https://youtu.be/abc", lang="en")

    assert text == "Auto text"


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_handles_orig_suffix(mock_ytdl_class):
    """yt-dlp may suffix with `-orig` when normalizing (e.g. en-US → en)."""
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOriginal text\n"
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_files(
        {"abc.en-orig.vtt": vtt}
    )

    text = fetch_captions("https://youtu.be/abc", lang="en")

    assert text == "Original text"


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_prefers_manual_over_auto(mock_ytdl_class):
    """When both manual and auto captions are written, prefer manual."""
    manual_vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nManual text\n"
    auto_vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nAuto text\n"
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_files(
        {"abc.en.vtt": manual_vtt, "abc.en-auto.vtt": auto_vtt}
    )

    text = fetch_captions("https://youtu.be/abc", lang="en")

    assert text == "Manual text"
    assert "Auto" not in text


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_falls_back_to_auto_when_no_manual(mock_ytdl_class):
    auto_vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nAuto only\n"
    mock_ytdl_class.side_effect = _ytdl_with_side_effect_writing_files(
        {"abc.en-auto.vtt": auto_vtt}
    )

    text = fetch_captions("https://youtu.be/abc", lang="en")

    assert text == "Auto only"


@patch("vault_yt.extractor.YoutubeDL")
def test_fetch_captions_raises_network_kind_on_yt_dlp_error(mock_ytdl_class):
    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False
        ydl.extract_info.side_effect = RuntimeError("network")
        return ydl

    mock_ytdl_class.side_effect = factory

    with pytest.raises(ExtractorError) as exc_info:
        fetch_captions("https://youtu.be/explode")

    assert exc_info.value.kind == "network"


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
def test_download_audio_passes_size_and_duration_caps(mock_ytdl_class, tmp_path: Path):
    """Spec-pinned trust-boundary defaults must reach yt-dlp's opts."""
    captured: dict = {}

    def factory(opts):
        captured.update(opts)
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            (tmp_path / "abc.m4a").write_bytes(b"x" * 100)
            return {"id": "abc"}

        ydl.extract_info = extract_info
        return ydl

    mock_ytdl_class.side_effect = factory

    download_audio("https://youtu.be/abc", tmp_path)

    assert captured["max_filesize"] == MAX_AUDIO_FILESIZE_BYTES
    assert callable(captured["match_filter"])


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_raises_network_kind_on_yt_dlp_error(mock_ytdl_class, tmp_path: Path):
    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False
        ydl.extract_info.side_effect = RuntimeError("offline")
        return ydl

    mock_ytdl_class.side_effect = factory

    with pytest.raises(ExtractorError) as exc_info:
        download_audio("https://youtu.be/dead", tmp_path)

    assert exc_info.value.kind == "network"


@patch("vault_yt.extractor.YoutubeDL")
def test_download_audio_raises_no_audio_file_kind_when_no_file_written(
    mock_ytdl_class, tmp_path: Path
):
    """yt-dlp returned an id but no file landed → caller-visible error with the right kind."""

    def factory(opts):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.__exit__.return_value = False

        def extract_info(url, download=True):
            return {"id": "ghost"}  # no file written

        ydl.extract_info = extract_info
        return ydl

    mock_ytdl_class.side_effect = factory

    with pytest.raises(ExtractorError) as exc_info:
        download_audio("https://youtu.be/ghost", tmp_path)

    assert exc_info.value.kind == "no_audio_file"


# ----- _duration_filter (P1-3) -----


def test_duration_filter_accepts_normal_video():
    assert _duration_filter({"duration": 213}) is None


def test_duration_filter_accepts_at_cap():
    assert _duration_filter({"duration": MAX_VIDEO_DURATION_SECONDS}) is None


def test_duration_filter_rejects_over_cap():
    reason = _duration_filter({"duration": MAX_VIDEO_DURATION_SECONDS + 1})
    assert reason is not None
    assert "too long" in reason


def test_duration_filter_accepts_missing_duration():
    """Missing duration shouldn't reject — let yt-dlp's filesize cap handle it."""
    assert _duration_filter({}) is None


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


# ----- new edge cases (P1-5) -----


def test_parse_vtt_strips_bom():
    """UTF-8 BOM at file start should not bleed into transcript."""
    vtt = "﻿WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nClean text\n"
    assert _parse_vtt(vtt) == "Clean text"


def test_parse_vtt_unescapes_html_entities():
    """YouTube auto-captions emit `&amp;`, `&#39;`, `&quot;` — must unescape."""
    vtt = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Tom &amp; Jerry &#39;s &quot;adventures&quot;\n"
    )
    assert _parse_vtt(vtt) == "Tom & Jerry 's \"adventures\""


def test_parse_vtt_dedupes_rolling_window_cues():
    """YouTube auto-captions repeat the last cue line at the start of the next.
    Adjacent-line dedup collapses these to a single occurrence."""
    vtt = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "first line\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "first line\n"
        "second line\n"
    )
    # Without dedup we'd see "first line\nfirst line\nsecond line"
    # With dedup: only one "first line".
    assert _parse_vtt(vtt) == "first line\nsecond line"


def test_parse_vtt_keeps_distinct_repeated_phrases_when_not_adjacent():
    """Non-adjacent repeats are kept (not a rolling-window artifact)."""
    vtt = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "hello\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "world\n"
        "\n"
        "00:00:04.000 --> 00:00:06.000\n"
        "hello\n"
    )
    assert _parse_vtt(vtt) == "hello\nworld\nhello"


# ============================================================
# ExtractorError class
# ============================================================


def test_extractor_error_carries_kind():
    err = ExtractorError("network", "boom")
    assert err.kind == "network"
    assert str(err) == "boom"
    assert isinstance(err, RuntimeError)


def test_extractor_error_kind_is_attribute_not_arg():
    """`kind` must be accessible after construction without re-parsing the message."""
    try:
        raise ExtractorError("no_audio_file", "missing file at /tmp/x")
    except ExtractorError as e:
        assert e.kind == "no_audio_file"
