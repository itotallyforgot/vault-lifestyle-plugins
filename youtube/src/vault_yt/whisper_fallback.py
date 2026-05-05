"""Local Whisper transcription — fallback when YouTube captions are absent.

Lazy-imports `openai-whisper` (the optional `[whisper]` extra). When the
extra isn't installed, raises `WhisperUnavailableError` instead of crashing
the import of this module — keeps the rest of `vault_yt` importable on
captions-only installs.

Failure modes use a `kind`-discriminator pattern matching `extractor.ExtractorError`,
so the CLI (Slice 5 / ISSUE-N) can map cleanly to the spec's exit codes:

| spec exit | failure mode                          | exception                                       |
|-----------|---------------------------------------|-------------------------------------------------|
| 6         | whisper extra not installed           | WhisperUnavailableError                         |
| 7         | whisper model download/load failed    | WhisperTranscriptionError(kind="model_load")    |
| 7         | transcribe call raised at runtime     | WhisperTranscriptionError(kind="transcribe")    |
| 8         | transcript empty                      | (returned as `""`; CLI maps empty → exit 8)     |
| —         | requested model exceeds spec cap      | WhisperModelTooLargeError                       |
| —         | audio file missing                    | FileNotFoundError                               |
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "base"
# Per spec: absolute cap, no user override. Larger models break the
# gaming/dev-loop VRAM budget; lifting the cap requires an explicit spec
# revision, not an env var. (Reviewer flagged this; locked deliberately.)
ALLOWED_MODELS: tuple[str, ...] = ("tiny", "base", "small")


WhisperTranscriptionKind = Literal["model_load", "transcribe"]


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
) -> str:
    """Transcribe `audio_path` via local Whisper. Returns plain text.

    Args:
        audio_path: input audio file (typically m4a from `extractor.download_audio`).
            Accepts `str` for caller convenience; coerced to `Path`.
        model: Whisper model name. Default `"base"` (~1 GB VRAM, CPU-OK).
            Capped at `"small"` per spec (absolute cap; no user override).
            Raises `WhisperModelTooLargeError` for anything larger.
        language: ISO 639-1 hint to skip Whisper's auto-detect. None = auto.
            TODO(slice 5 / ISSUE-N): wire `--language` CLI flag through.

    Returns:
        Transcript text, stripped. Empty string when whisper produces no text
        (CLI maps empty → exit 8).

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

    # Lazy import — keeps the module importable when [whisper] extra is
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
            verbose=False,
        )
    except Exception as e:
        raise WhisperTranscriptionError(
            "transcribe", f"whisper.transcribe({audio_path}) failed: {e}"
        ) from e

    text = result.get("text", "")
    if not isinstance(text, str):
        return ""
    return text.strip()
