"""Local Whisper transcription: fallback when YouTube captions are absent.

Lazy-imports `openai-whisper` (the optional `[whisper]` extra). When the
extra isn't installed, raises `WhisperUnavailableError` instead of crashing
the import of this module; keeps the rest of `vault_yt` importable on
captions-only installs.

Failure modes use a `kind`-discriminator pattern matching `extractor.ExtractorError`,
so the CLI (Slice 5 / ISSUE-N) can map cleanly to the spec's exit codes:

| spec exit | failure mode                          | exception                                       |
|-----------|---------------------------------------|-------------------------------------------------|
| 6         | whisper extra not installed           | WhisperUnavailableError                         |
| 7         | whisper model download/load failed    | WhisperTranscriptionError(kind="model_load")    |
| 7         | transcribe call raised at runtime     | WhisperTranscriptionError(kind="transcribe")    |
| 8         | transcript empty                      | (TranscriptResult.text == ""; CLI maps → exit 8)|
| n/a       | requested model exceeds spec cap      | WhisperModelTooLargeError                       |
| n/a       | audio file missing                    | FileNotFoundError                               |

`transcribe_audio` returns a `TranscriptResult` (text + quality verdict). A
segment that trips a standard hallucination heuristic
(`compression_ratio`/`avg_logprob`/`no_speech_prob`) marks the result
`quality="suspect"`, emits a stderr warning, and lets the CLI stamp
`transcript_quality: suspect` into the raw frontmatter for `/vault ingest` to
gate on.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "base"
# Per spec: absolute cap, no user override. Larger models break the
# gaming/dev-loop VRAM budget; lifting the cap requires an explicit spec
# revision, not an env var. (Reviewer flagged this; locked deliberately.)
ALLOWED_MODELS: tuple[str, ...] = ("tiny", "base", "small")

# Standard Whisper hallucination heuristics (mirrors openai-whisper's own
# `DecodingOptions` failure thresholds). A segment that trips any of these is
# a strong signal of fabricated / low-confidence text — small/base models
# hallucinate confidently on music, silence, and non-speech audio.
COMPRESSION_RATIO_THRESHOLD = 2.4  # repetitive/looping text inflates this
LOGPROB_THRESHOLD = -1.0  # below this, the model is guessing
NO_SPEECH_THRESHOLD = 0.6  # high → segment is probably not speech at all

TranscriptQuality = Literal["ok", "suspect"]
WhisperTranscriptionKind = Literal["model_load", "transcribe"]


@dataclass(frozen=True)
class TranscriptResult:
    """A Whisper transcript plus a coarse quality verdict.

    `quality == "suspect"` means at least one segment tripped a standard
    hallucination heuristic. The CLI stamps `transcript_quality: suspect`
    into the raw frontmatter so `/vault ingest` can gate on it instead of
    silently accepting a fabricated transcript.
    """

    text: str
    quality: TranscriptQuality = "ok"
    suspect_reasons: tuple[str, ...] = field(default_factory=tuple)


def assess_segments(segments: Sequence[Any]) -> tuple[TranscriptQuality, tuple[str, ...]]:
    """Classify Whisper segments as `ok` or `suspect` via standard heuristics.

    Pure function — no I/O. Accepts the `result["segments"]` list of dicts (or
    any mapping-like objects exposing `compression_ratio`, `avg_logprob`, and
    `no_speech_prob`). Missing/non-numeric fields are skipped, not assumed bad,
    so older Whisper versions that omit a key never false-positive.

    Returns `(verdict, reasons)`. `reasons` is a deduped, ordered tuple of
    short human-readable strings for the stderr warning.
    """
    reasons: list[str] = []

    def _num(seg: Any, key: str) -> float | None:
        value = seg.get(key) if hasattr(seg, "get") else getattr(seg, key, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    saw_high_compression = False
    saw_low_logprob = False
    saw_no_speech = False
    for seg in segments:
        compression_ratio = _num(seg, "compression_ratio")
        if compression_ratio is not None and compression_ratio > COMPRESSION_RATIO_THRESHOLD:
            saw_high_compression = True

        avg_logprob = _num(seg, "avg_logprob")
        if avg_logprob is not None and avg_logprob < LOGPROB_THRESHOLD:
            saw_low_logprob = True

        no_speech_prob = _num(seg, "no_speech_prob")
        if no_speech_prob is not None and no_speech_prob > NO_SPEECH_THRESHOLD:
            saw_no_speech = True

    if saw_high_compression:
        reasons.append(f"compression_ratio > {COMPRESSION_RATIO_THRESHOLD} (repetitive text)")
    if saw_low_logprob:
        reasons.append(f"avg_logprob < {LOGPROB_THRESHOLD} (low confidence)")
    if saw_no_speech:
        reasons.append(f"no_speech_prob > {NO_SPEECH_THRESHOLD} (likely non-speech)")

    verdict: TranscriptQuality = "suspect" if reasons else "ok"
    return verdict, tuple(reasons)


class WhisperFallbackError(RuntimeError):
    """Base for all whisper-fallback failures.

    The Slice-5 CLI catches this single base to route any whisper-side
    failure to the right exit code via the subclass's `kind` (when present).
    """


class WhisperUnavailableError(WhisperFallbackError):
    """openai-whisper is not installed (`[whisper]` extra) OR fails to load
    its native deps (e.g., libcudnn missing). Maps to spec exit 6."""


class WhisperModelTooLargeError(WhisperFallbackError):
    """Requested model is outside the spec-pinned allowlist."""


class WhisperTranscriptionError(WhisperFallbackError):
    """Whisper raised during model load or transcription. Maps to spec exit 7.

    `kind` distinguishes load-time failures (model download / GPU init) from
    runtime failures (corrupt audio / OOM mid-transcribe). Both map to exit
    7 today, but the discriminator lets the CLI emit clearer error messages
    and lets retry policy diverge in future.
    """

    def __init__(self, kind: WhisperTranscriptionKind, message: str) -> None:
        super().__init__(message)
        self.kind: WhisperTranscriptionKind = kind


def transcribe_audio(
    audio_path: Path | str,
    *,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    verbose: bool = False,
) -> TranscriptResult:
    """Transcribe `audio_path` via local Whisper.

    Args:
        audio_path: input audio file (typically m4a from `extractor.download_audio`).
            Accepts `str` for caller convenience; coerced to `Path`.
        model: Whisper model name. Default `"base"` (~1 GB VRAM, CPU-OK).
            Capped at `"small"` per spec (absolute cap; no user override).
            Raises `WhisperModelTooLargeError` for anything larger.
        language: ISO 639-1 hint to skip Whisper's auto-detect. None = auto.
        verbose: pass through to Whisper's transcribe call.

    Returns:
        A `TranscriptResult`: stripped transcript text plus a quality verdict
        derived from Whisper's per-segment confidence signals. `text` is the
        empty string when whisper produces no text (CLI maps empty → exit 8).
        `quality == "suspect"` when any segment trips a hallucination
        heuristic; a warning is also emitted to stderr so a non-gating caller
        still sees it.

    Raises:
        WhisperModelTooLargeError: `model` not in `ALLOWED_MODELS`.
        FileNotFoundError: `audio_path` doesn't exist or isn't a file.
        WhisperUnavailableError: `openai-whisper` not installed or its native
            deps failed to load.
        WhisperTranscriptionError: model load or transcribe call raised.
    """
    if model not in ALLOWED_MODELS:
        raise WhisperModelTooLargeError(
            f"model {model!r} exceeds the cap. Allowed: {ALLOWED_MODELS}"
        )

    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"audio file does not exist: {audio_path}")

    # Lazy import keeps the module importable when [whisper] extra is
    # absent. Catch both ImportError (missing package) and OSError
    # (missing native deps like libcudnn) since either makes whisper
    # effectively unavailable from the CLI's perspective (spec exit 6).
    try:
        import whisper  # type: ignore[import-untyped]
    except (ImportError, OSError) as e:
        raise WhisperUnavailableError(
            f"openai-whisper unavailable: {e}. "
            "Install via `uv sync --extra whisper` or `pip install openai-whisper`."
        ) from e

    logger.info("Loading Whisper model %r", model)
    try:
        whisper_model = whisper.load_model(model)
    except Exception as e:
        raise WhisperTranscriptionError(
            "model_load", f"whisper.load_model({model!r}) failed: {e}"
        ) from e

    logger.info("Transcribing %s", audio_path)
    try:
        result = whisper_model.transcribe(
            str(audio_path),
            language=language,
            verbose=verbose,
        )
    except Exception as e:
        raise WhisperTranscriptionError(
            "transcribe", f"whisper.transcribe({audio_path}) failed: {e}"
        ) from e

    raw_text = result.get("text", "")
    text = raw_text.strip() if isinstance(raw_text, str) else ""

    raw_segments = result.get("segments") or []
    segments = raw_segments if isinstance(raw_segments, Sequence) else []
    quality, reasons = assess_segments(segments)
    if quality == "suspect":
        logger.warning("whisper transcript flagged suspect: %s", "; ".join(reasons))
        print(
            f"warning: whisper transcript may be hallucinated ({'; '.join(reasons)}). "
            "Frontmatter stamped transcript_quality: suspect.",
            file=sys.stderr,
        )
    return TranscriptResult(text=text, quality=quality, suspect_reasons=reasons)
