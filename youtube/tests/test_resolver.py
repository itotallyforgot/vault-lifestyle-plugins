"""Tests for vault_yt.resolver — pure-logic, no mocks needed."""

from __future__ import annotations

from vault_yt.resolver import choose_transcript_source


# ---------- happy paths ----------


def test_caption_kinds_present_returns_captions():
    meta = {"captions": ["en"], "caption_kinds": {"en": "manual"}}
    assert choose_transcript_source(meta, lang="en") == "captions"


def test_auto_only_caption_kinds_returns_captions():
    """Auto-generated captions still satisfy the `captions` decision."""
    meta = {"captions": ["en"], "caption_kinds": {"en": "auto"}}
    assert choose_transcript_source(meta, lang="en") == "captions"


def test_no_captions_returns_whisper():
    meta = {"captions": [], "caption_kinds": {}}
    assert choose_transcript_source(meta, lang="en") == "whisper"


def test_lang_not_present_returns_whisper():
    """Captions exist but in a different language → fall back to Whisper."""
    meta = {"captions": ["fr", "es"], "caption_kinds": {"fr": "manual", "es": "auto"}}
    assert choose_transcript_source(meta, lang="en") == "whisper"


# ---------- force_whisper override ----------


def test_force_whisper_overrides_captions():
    meta = {"captions": ["en"], "caption_kinds": {"en": "manual"}}
    assert (
        choose_transcript_source(meta, lang="en", force_whisper=True) == "whisper"
    )


def test_force_whisper_with_no_captions_returns_whisper():
    meta = {"captions": [], "caption_kinds": {}}
    assert (
        choose_transcript_source(meta, lang="en", force_whisper=True) == "whisper"
    )


# ---------- legacy meta shape (no caption_kinds) ----------


def test_legacy_captions_only_returns_captions():
    """Older callers pass meta without `caption_kinds` — fall back to `captions` list."""
    meta = {"captions": ["en"]}
    assert choose_transcript_source(meta, lang="en") == "captions"


def test_legacy_captions_lang_not_present_returns_whisper():
    meta = {"captions": ["fr"]}
    assert choose_transcript_source(meta, lang="en") == "whisper"


def test_completely_empty_meta_returns_whisper():
    """Defensive: meta missing both fields → whisper, not crash."""
    assert choose_transcript_source({}, lang="en") == "whisper"


def test_meta_with_none_fields_returns_whisper():
    """Defensive: meta with explicit None values → whisper, not crash."""
    meta = {"captions": None, "caption_kinds": None}
    assert choose_transcript_source(meta, lang="en") == "whisper"


# ---------- caption_kinds takes precedence over captions list ----------


def test_caption_kinds_wins_over_legacy_captions_when_both_present():
    """If caption_kinds covers the lang but legacy list doesn't, captions wins."""
    meta = {"captions": [], "caption_kinds": {"en": "manual"}}
    assert choose_transcript_source(meta, lang="en") == "captions"
