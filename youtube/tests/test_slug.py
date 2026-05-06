"""Tests for vault_yt.slug.make."""

from __future__ import annotations

import pytest

from vault_yt.slug import make

# ---------- determinism ----------


def test_same_inputs_produce_same_slug() -> None:
    a = make("dQw4w9WgXcQ", "Never Gonna Give You Up")
    b = make("dQw4w9WgXcQ", "Never Gonna Give You Up")
    assert a == b


def test_id_anchored_slug_changes_when_title_changes_but_starts_with_id() -> None:
    """Title edits change the slug but the ID prefix is stable."""
    s1 = make("dQw4w9WgXcQ", "Never Gonna Give You Up")
    s2 = make("dQw4w9WgXcQ", "Never gonna give you up - REMASTERED")
    assert s1 != s2
    assert s1.startswith("dQw4w9WgXcQ-")
    assert s2.startswith("dQw4w9WgXcQ-")


def test_different_videos_produce_different_slugs_even_with_same_title() -> None:
    s1 = make("aaaaaaaaaaa", "intro to topics")
    s2 = make("bbbbbbbbbbb", "intro to topics")
    assert s1 != s2
    assert s1.startswith("aaaaaaaaaaa-")
    assert s2.startswith("bbbbbbbbbbb-")


# ---------- sanitization ----------


def test_lowercases_title() -> None:
    s = make("xyz", "MIXED Case Title")
    assert s == "xyz-mixed-case-title"


def test_strips_punctuation() -> None:
    s = make("xyz", "Hello, World! It's #1")
    # Commas, exclam, apostrophe, hash all gone; word boundaries become dashes.
    assert s == "xyz-hello-world-it-s-1"


def test_collapses_runs_of_separators() -> None:
    s = make("xyz", "a   b---c___d")
    assert s == "xyz-a-b-c-d"


def test_strips_leading_trailing_separators() -> None:
    s = make("xyz", "---trim me---")
    assert s == "xyz-trim-me"


def test_truncates_long_titles() -> None:
    long_title = "word " * 50
    s = make("xyz", long_title)
    # Slug body (after id-) should be at most 60 chars per the conservative cap.
    body = s.removeprefix("xyz-")
    assert len(body) <= 60
    # Truncation must not leave a trailing dash.
    assert not body.endswith("-")


def test_unicode_diacritics_normalized() -> None:
    """Unicode letters (accented Latin) should fold to ASCII equivalents."""
    s = make("xyz", "Café Résumé")
    assert s == "xyz-cafe-resume"


def test_non_latin_script_falls_back_gracefully() -> None:
    """Pure non-Latin titles produce id-only slugs, not empty bodies."""
    s = make("xyz", "中文标题")
    # Either id-only OR transliterated; either way, must start with the id and
    # never produce a trailing dash or empty body.
    assert s.startswith("xyz")
    assert not s.endswith("-")


def test_empty_title_falls_back_to_id_only() -> None:
    assert make("xyz", "") == "xyz"


def test_whitespace_only_title_falls_back_to_id_only() -> None:
    assert make("xyz", "   \t\n  ") == "xyz"


def test_punctuation_only_title_falls_back_to_id_only() -> None:
    assert make("xyz", "!!!---???") == "xyz"


# ---------- input validation ----------


def test_empty_video_id_raises() -> None:
    with pytest.raises(ValueError):
        make("", "any title")


def test_whitespace_video_id_raises() -> None:
    with pytest.raises(ValueError):
        make("   ", "any title")


# ---------- filesystem-safety ----------


def test_slug_is_filesystem_safe() -> None:
    """Output contains only chars that are safe across Win/Mac/Linux filesystems."""
    s = make("xyz", 'Title with "quotes" / slashes \\ pipes | colons : asterisks * ?')
    # Allowed: lowercase ASCII letters, digits, dash. Underscore not used here.
    safe_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    bad = [c for c in s if c not in safe_chars]
    assert not bad, f"unsafe chars in slug: {bad!r}"
