"""Tests for vault_yt.whisper_fallback.

Whisper module mocked at the `import whisper` boundary via sys.modules so
the optional `[whisper]` extra isn't required for the unit suite. The
`@pytest.mark.whisper` test exercises the live path and is skipped by
default (opt-in via `pytest -m whisper`).
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vault_yt.whisper_fallback import (
    ALLOWED_MODELS,
    COMPRESSION_RATIO_THRESHOLD,
    DEFAULT_MODEL,
    LOGPROB_THRESHOLD,
    NO_SPEECH_THRESHOLD,
    WhisperFallbackError,
    WhisperModelTooLargeError,
    WhisperTranscriptionError,
    WhisperUnavailableError,
    assess_segments,
    transcribe_audio,
)


def _make_audio(tmp_path: Path) -> Path:
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"fake audio bytes")
    return audio


def _install_fake_whisper(
    monkeypatch: pytest.MonkeyPatch, transcribe_text: str = "hello"
) -> MagicMock:
    """Inject a fake `whisper` module into sys.modules, return the model mock."""
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {"text": transcribe_text}
    fake_whisper.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    return fake_whisper


# ---------- model validation ----------


def test_default_model_is_base():
    assert DEFAULT_MODEL == "base"
    assert "base" in ALLOWED_MODELS


def test_allowed_models_capped_at_small():
    """Spec: cap at small. medium / large / large-v3 NOT in the allowlist."""
    assert "medium" not in ALLOWED_MODELS
    assert "large" not in ALLOWED_MODELS
    assert ALLOWED_MODELS[-1] == "small"


def test_too_large_model_raises(tmp_path: Path):
    audio = _make_audio(tmp_path)
    with pytest.raises(WhisperModelTooLargeError, match="exceeds the cap"):
        transcribe_audio(audio, model="medium")


def test_unknown_model_raises(tmp_path: Path):
    audio = _make_audio(tmp_path)
    with pytest.raises(WhisperModelTooLargeError):
        transcribe_audio(audio, model="not-a-real-model")


# ---------- file-existence guard ----------


def test_missing_audio_file_raises(tmp_path: Path):
    ghost = tmp_path / "ghost.m4a"
    with pytest.raises(FileNotFoundError, match="audio file does not exist"):
        transcribe_audio(ghost)


def test_audio_path_must_be_file_not_dir(tmp_path: Path):
    """A directory at `audio_path` should raise FileNotFoundError, not crash inside whisper."""
    with pytest.raises(FileNotFoundError):
        transcribe_audio(tmp_path)


# ---------- import guard ----------


def _patch_whisper_import_error(monkeypatch: pytest.MonkeyPatch, exc: BaseException):
    """Force `import whisper` to raise `exc` regardless of installed packages."""
    monkeypatch.delitem(sys.modules, "whisper", raising=False)
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "whisper":
            raise exc
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_whisper_unavailable_raises_on_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If openai-whisper isn't installed, surface a clear error before transcribing."""
    audio = _make_audio(tmp_path)
    _patch_whisper_import_error(monkeypatch, ImportError("No module named 'whisper'"))

    with pytest.raises(WhisperUnavailableError, match="unavailable"):
        transcribe_audio(audio)


def test_whisper_unavailable_raises_on_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real-world: torch/cudnn dlopen failures raise OSError, not ImportError.
    Treat them the same — whisper effectively unavailable from the CLI's view."""
    audio = _make_audio(tmp_path)
    _patch_whisper_import_error(
        monkeypatch, OSError("dlopen failed: libcudnn.so.8: cannot open shared object file")
    )

    with pytest.raises(WhisperUnavailableError, match="unavailable"):
        transcribe_audio(audio)


# ---------- successful transcribe path (mocked whisper) ----------


def test_transcribe_uses_default_model_when_unspecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audio = _make_audio(tmp_path)
    fake_whisper = _install_fake_whisper(monkeypatch, "result text")

    transcribe_audio(audio)

    fake_whisper.load_model.assert_called_once_with(DEFAULT_MODEL)


def test_transcribe_passes_explicit_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = _make_audio(tmp_path)
    fake_whisper = _install_fake_whisper(monkeypatch)

    transcribe_audio(audio, model="small")

    fake_whisper.load_model.assert_called_once_with("small")


def test_transcribe_returns_stripped_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = _make_audio(tmp_path)
    _install_fake_whisper(monkeypatch, "  hello world  \n")

    result = transcribe_audio(audio)

    assert result.text == "hello world"


def test_transcribe_returns_empty_string_when_text_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audio = _make_audio(tmp_path)
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {}  # no `text` key
    fake_whisper.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    result = transcribe_audio(audio)

    assert result.text == ""


def test_transcribe_returns_empty_string_when_text_not_str(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audio = _make_audio(tmp_path)
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {"text": None}
    fake_whisper.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    result = transcribe_audio(audio)

    assert result.text == ""


def test_transcribe_passes_language_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = _make_audio(tmp_path)
    fake_whisper = _install_fake_whisper(monkeypatch)
    fake_model = fake_whisper.load_model.return_value

    transcribe_audio(audio, language="en")

    args, kwargs = fake_model.transcribe.call_args
    assert args[0] == str(audio)
    assert kwargs["language"] == "en"
    assert kwargs["verbose"] is False


def test_transcribe_passes_none_language_for_autodetect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audio = _make_audio(tmp_path)
    fake_whisper = _install_fake_whisper(monkeypatch)
    fake_model = fake_whisper.load_model.return_value

    transcribe_audio(audio)  # no language → None

    _, kwargs = fake_model.transcribe.call_args
    assert kwargs["language"] is None


def test_audio_path_accepts_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Caller convenience: `audio_path: Path | str` — string inputs are coerced."""
    audio = _make_audio(tmp_path)
    _install_fake_whisper(monkeypatch, "ok")

    result = transcribe_audio(str(audio))  # str, not Path

    assert result.text == "ok"


# ---------- transcription failure modes (kind discriminator) ----------


def test_model_load_failure_raises_transcription_error_with_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """whisper.load_model raising → WhisperTranscriptionError(kind='model_load')."""
    audio = _make_audio(tmp_path)
    fake_whisper = MagicMock()
    fake_whisper.load_model.side_effect = RuntimeError("checkpoint download failed")
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    with pytest.raises(WhisperTranscriptionError) as exc_info:
        transcribe_audio(audio)

    assert exc_info.value.kind == "model_load"
    assert "load_model" in str(exc_info.value)


def test_transcribe_failure_raises_transcription_error_with_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """whisper_model.transcribe raising → WhisperTranscriptionError(kind='transcribe')."""
    audio = _make_audio(tmp_path)
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.side_effect = RuntimeError("CUDA OOM mid-pass")
    fake_whisper.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    with pytest.raises(WhisperTranscriptionError) as exc_info:
        transcribe_audio(audio)

    assert exc_info.value.kind == "transcribe"
    assert "transcribe" in str(exc_info.value)


# ---------- exception hierarchy (Slice 5 CLI catches single base) ----------


def test_all_whisper_exceptions_inherit_from_fallback_error_base():
    """The CLI catches `WhisperFallbackError` once and routes via `kind`/type."""
    assert issubclass(WhisperUnavailableError, WhisperFallbackError)
    assert issubclass(WhisperModelTooLargeError, WhisperFallbackError)
    assert issubclass(WhisperTranscriptionError, WhisperFallbackError)


def test_whisper_transcription_error_carries_kind_attribute():
    """Constructed instance exposes `.kind` for CLI discrimination."""
    err = WhisperTranscriptionError("model_load", "boom")
    assert err.kind == "model_load"
    assert isinstance(err, WhisperFallbackError)
    assert isinstance(err, RuntimeError)


# ---------- live path (opt-in) ----------


@pytest.mark.whisper
def test_live_transcribe_with_real_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Live transcribe — skipped unless `pytest -m whisper` is invoked AND
    openai-whisper is installed AND the `base` model is pre-cached."""
    # Belt-and-suspenders: drop any fake `whisper` left behind by unit tests
    # in the same pytest run (monkeypatch cleanup is reliable but xdist /
    # local-dev workflows can pollute sys.modules across collection passes).
    monkeypatch.delitem(sys.modules, "whisper", raising=False)
    pytest.importorskip("whisper")
    # Generate a 1-second silence wav as a deterministic input.
    import struct
    import wave

    audio = tmp_path / "silence.wav"
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<" + "h" * 16000, *([0] * 16000)))

    result = transcribe_audio(audio, model="base", language="en")

    # Silence may return "" or filler — just assert shape.
    assert isinstance(result.text, str)


# ---------- transcript quality heuristics (L2) ----------


def _good_segment() -> dict[str, float]:
    return {"compression_ratio": 1.5, "avg_logprob": -0.3, "no_speech_prob": 0.05}


def test_assess_segments_clean_transcript_is_ok():
    verdict, reasons = assess_segments([_good_segment(), _good_segment()])

    assert verdict == "ok"
    assert reasons == ()


def test_assess_segments_empty_is_ok():
    """No segments (older whisper / minimal result) must not false-positive."""
    verdict, reasons = assess_segments([])

    assert verdict == "ok"
    assert reasons == ()


def test_assess_segments_flags_high_compression_ratio():
    bad = {**_good_segment(), "compression_ratio": COMPRESSION_RATIO_THRESHOLD + 0.5}

    verdict, reasons = assess_segments([_good_segment(), bad])

    assert verdict == "suspect"
    assert any("compression_ratio" in r for r in reasons)


def test_assess_segments_flags_low_avg_logprob():
    bad = {**_good_segment(), "avg_logprob": LOGPROB_THRESHOLD - 0.5}

    verdict, reasons = assess_segments([bad])

    assert verdict == "suspect"
    assert any("avg_logprob" in r for r in reasons)


def test_assess_segments_flags_high_no_speech_prob():
    bad = {**_good_segment(), "no_speech_prob": NO_SPEECH_THRESHOLD + 0.2}

    verdict, reasons = assess_segments([bad])

    assert verdict == "suspect"
    assert any("no_speech_prob" in r for r in reasons)


def test_assess_segments_ignores_non_numeric_and_missing_fields():
    """Missing or non-numeric signals are skipped, not treated as bad."""
    weird = {"compression_ratio": None, "avg_logprob": "nan"}

    verdict, reasons = assess_segments([weird, {}])

    assert verdict == "ok"
    assert reasons == ()


def test_assess_segments_at_threshold_is_not_suspect():
    """Heuristics are strict inequalities — exactly at the threshold is OK."""
    edge = {
        "compression_ratio": COMPRESSION_RATIO_THRESHOLD,
        "avg_logprob": LOGPROB_THRESHOLD,
        "no_speech_prob": NO_SPEECH_THRESHOLD,
    }

    verdict, _ = assess_segments([edge])

    assert verdict == "ok"


def test_transcribe_marks_suspect_when_segments_trip_heuristics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A hallucinated transcript should come back quality='suspect' AND warn on stderr."""
    audio = _make_audio(tmp_path)
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {
        "text": "la la la la la la la",
        "segments": [
            {
                "compression_ratio": 3.1,
                "avg_logprob": -1.4,
                "no_speech_prob": 0.8,
            }
        ],
    }
    fake_whisper.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    result = transcribe_audio(audio)

    assert result.quality == "suspect"
    assert result.text == "la la la la la la la"
    assert result.suspect_reasons  # non-empty
    captured = capsys.readouterr()
    assert "suspect" in captured.err
    assert "hallucinated" in captured.err


def test_transcribe_clean_segments_stay_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    audio = _make_audio(tmp_path)
    fake_whisper = MagicMock()
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {
        "text": "a genuine sentence of real speech",
        "segments": [_good_segment()],
    }
    fake_whisper.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    result = transcribe_audio(audio)

    assert result.quality == "ok"
    assert result.suspect_reasons == ()
    assert "suspect" not in capsys.readouterr().err
