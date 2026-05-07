"""Tests for vault_yt.slug.make."""

from __future__ import annotations

from datetime import date

import pytest

from vault_yt.slug import make

# ---------- determinism ----------


def test_same_inputs_produce_same_slug() -> None:
    a = make("dQw4w9WgXcQ", "Never Gonna Give You Up", date(2009, 10, 25))
    b = make("dQw4w9WgXcQ", "Never Gonna Give You Up", date(2009, 10, 25))
    assert a == b


def test_slug_starts_with_date_youtube_and_id() -> None:
    s = make("dQw4w9WgXcQ", "Never Gonna Give You Up", date(2009, 10, 25))

    assert s == "2009-10-25-youtube-dQw4w9WgXcQ-never-gonna-give-you-up"


def test_title_edits_keep_date_youtube_and_id_prefix() -> None:
    """Title edits change the slug but the date/source/ID prefix is stable."""
    s1 = make("dQw4w9WgXcQ", "Never Gonna Give You Up", date(2009, 10, 25))
    s2 = make("dQw4w9WgXcQ", "Never gonna give you up - REMASTERED", date(2009, 10, 25))
    assert s1 != s2
    assert s1.startswith("2009-10-25-youtube-dQw4w9WgXcQ-")
    assert s2.startswith("2009-10-25-youtube-dQw4w9WgXcQ-")


def test_different_videos_produce_different_slugs_even_with_same_title() -> None:
    s1 = make("aaaaaaaaaaa", "intro to topics", date(2026, 5, 7))
    s2 = make("bbbbbbbbbbb", "intro to topics", date(2026, 5, 7))
    assert s1 != s2
    assert s1.startswith("2026-05-07-youtube-aaaaaaaaaaa-")
    assert s2.startswith("2026-05-07-youtube-bbbbbbbbbbb-")


# ---------- sanitization ----------


def test_lowercases_title() -> None:
    s = make("xyz", "MIXED Case Title", date(2026, 5, 7))
    assert s == "2026-05-07-youtube-xyz-mixed-case-title"


def test_strips_punctuation() -> None:
    s = make("xyz", "Hello, World! It's #1", date(2026, 5, 7))
    # Commas, exclam, apostrophe, hash all gone; word boundaries become dashes.
    assert s == "2026-05-07-youtube-xyz-hello-world-it-s-1"


def test_collapses_runs_of_separators() -> None:
    s = make("xyz", "a   b---c___d", date(2026, 5, 7))
    assert s == "2026-05-07-youtube-xyz-a-b-c-d"


def test_strips_leading_trailing_separators() -> None:
    s = make("xyz", "---trim me---", date(2026, 5, 7))
    assert s == "2026-05-07-youtube-xyz-trim-me"


def test_truncates_long_titles() -> None:
    long_title = "word " * 50
    s = make("xyz", long_title, date(2026, 5, 7))
    # Slug body (after date-youtube-id-) should be at most 60 chars per the conservative cap.
    body = s.removeprefix("2026-05-07-youtube-xyz-")
    assert len(body) <= 60
    # Truncation must not leave a trailing dash.
    assert not body.endswith("-")


def test_unicode_diacritics_normalized() -> None:
    """Unicode letters (accented Latin) should fold to ASCII equivalents."""
    s = make("xyz", "Café Résumé", date(2026, 5, 7))
    assert s == "2026-05-07-youtube-xyz-cafe-resume"


def test_non_latin_script_falls_back_gracefully() -> None:
    """Pure non-Latin titles produce id-only slugs, not empty bodies."""
    s = make("xyz", "中文标题", date(2026, 5, 7))
    # Either date/source/id-only OR transliterated; either way, must start with
    # the stable prefix and never produce a trailing dash or empty body.
    assert s.startswith("2026-05-07-youtube-xyz")
    assert not s.endswith("-")


def test_empty_title_falls_back_to_id_only() -> None:
    assert make("xyz", "", date(2026, 5, 7)) == "2026-05-07-youtube-xyz"


def test_whitespace_only_title_falls_back_to_id_only() -> None:
    assert make("xyz", "   \t\n  ", date(2026, 5, 7)) == "2026-05-07-youtube-xyz"


def test_punctuation_only_title_falls_back_to_id_only() -> None:
    assert make("xyz", "!!!---???", date(2026, 5, 7)) == "2026-05-07-youtube-xyz"


# ---------- input validation ----------


def test_empty_video_id_raises() -> None:
    with pytest.raises(ValueError):
        make("", "any title", date(2026, 5, 7))


def test_whitespace_video_id_raises() -> None:
    with pytest.raises(ValueError):
        make("   ", "any title", date(2026, 5, 7))


def test_invalid_date_raises() -> None:
    with pytest.raises(ValueError):
        make("xyz", "any title", "2026/05/07")


# ---------- filesystem-safety ----------


def test_slug_is_filesystem_safe() -> None:
    """Output contains only chars that are safe across Win/Mac/Linux filesystems."""
    s = make(
        "xyz",
        'Title with "quotes" / slashes \\ pipes | colons : asterisks * ?',
        date(2026, 5, 7),
    )
    # Allowed: lowercase ASCII letters, digits, dash. Underscore not used here.
    safe_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    bad = [c for c in s if c not in safe_chars]
    assert not bad, f"unsafe chars in slug: {bad!r}"
