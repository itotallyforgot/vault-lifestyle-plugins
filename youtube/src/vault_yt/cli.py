"""Typer CLI for the `vault-yt` console script."""

from __future__ import annotations

import logging
import os
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, TypedDict, cast
from urllib.parse import urlparse

import typer
import yaml
from pydantic import ValidationError
from vault_resolver import VaultPathError, resolve_vault_path

from vault_yt.extractor import ExtractorError, download_audio, fetch_captions, fetch_meta
from vault_yt.resolver import choose_transcript_source
from vault_yt.slug import make
from vault_yt.whisper_fallback import (
    DEFAULT_MODEL,
    WhisperFallbackError,
    WhisperModelTooLargeError,
    WhisperTranscriptionError,
    WhisperUnavailableError,
    transcribe_audio,
)
from vault_yt.writer import WriterError, build_raw_md, write

logger = logging.getLogger(__name__)

app = typer.Typer(
    add_completion=False,
    help="vault-yt: fetch a YouTube transcript into a second-brain raw file.",
)


class VideoMeta(TypedDict):
    """Typed boundary for the subset of yt-dlp metadata the CLI orchestrates."""

    id: str
    title: str
    channel: Any
    channel_url: Any
    published_at: Any
    duration_seconds: Any
    captions: list[str]
    caption_kinds: dict[str, Literal["manual", "auto"]]


@app.command("vault-yt")
def command(
    url: Annotated[str, typer.Argument(help="YouTube URL to ingest.")],
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="Target second-brain vault path."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing raw file."),
    ] = False,
    force_whisper: Annotated[
        bool,
        typer.Option("--force-whisper", help="Skip captions and use local Whisper."),
    ] = False,
    whisper_model: Annotated[
        str | None,
        typer.Option(
            "--whisper-model",
            help="Whisper model: tiny, base, or small. Defaults to VAULT_YT_WHISPER_MODEL or base.",
        ),
    ] = None,
    transcript_language: Annotated[
        str,
        typer.Option(
            "--transcript-language",
            help="Caption language and Whisper language hint. Defaults to en.",
        ),
    ] = "en",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Print per-step diagnostics."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Run the pipeline but do not write."),
    ] = False,
) -> None:
    """Fetch a transcript and write `<vault>/raw/<slug>.md`."""
    _configure_logging(verbose)

    if not _looks_like_url(url):
        _fail(2, f"malformed url: {url}")

    try:
        vault_path = resolve_vault_path(vault)
    except VaultPathError as e:
        _fail(3, f"vault error: {e}")

    raw_dir = vault_path / "raw"
    if not raw_dir.is_dir():
        _fail(4, f"raw directory missing: {raw_dir}")
    if not os.access(raw_dir, os.W_OK):
        _fail(4, f"raw directory is not writable: {raw_dir}")

    model = whisper_model or os.environ.get("VAULT_YT_WHISPER_MODEL") or DEFAULT_MODEL

    try:
        raw_meta = _with_network_retry(fetch_meta, url, verbose=verbose)
        meta = _coerce_meta(raw_meta)
    except ExtractorError as e:
        _fail(5, f"yt-dlp error: {e}")
    except ValueError as e:
        _fail(5, f"metadata error: {e}")

    slug = make(meta["id"], meta["title"], _slug_date(meta))
    target = raw_dir / f"{slug}.md"
    source_url = _source_url(meta["id"])

    if target.exists() and not force:
        if _existing_source_url(target) == source_url:
            typer.echo(f"existing: {target}")
            raise typer.Exit(0)
        _fail(9, f"collision: {target} already exists for a different source")

    try:
        transcript, transcript_source = _resolve_transcript(
            url,
            meta,
            model=model,
            force_whisper=force_whisper,
            transcript_language=transcript_language,
            verbose=verbose,
        )
    except ExtractorError as e:
        _fail(5, f"yt-dlp error: {e}")
    except WhisperUnavailableError as e:
        _fail(6, f"whisper unavailable: {e}")
    except (WhisperModelTooLargeError, WhisperTranscriptionError, FileNotFoundError) as e:
        _fail(7, f"whisper error: {e}")
    except WhisperFallbackError as e:
        _fail(7, f"whisper error: {e}")

    if not transcript.strip():
        _fail(8, f"empty transcript from {transcript_source}")

    try:
        content = build_raw_md(meta, transcript, transcript_source=transcript_source)
    except (WriterError, ValidationError) as e:
        _fail(10, f"frontmatter validation bug: {e}")

    if dry_run:
        typer.echo(f"would write: {target}")
        typer.echo("")
        typer.echo(_dry_run_preview(content))
        raise typer.Exit(0)

    try:
        written = write(target, content, force=force)
    except FileExistsError as e:
        _fail(9, f"collision: {e}")
    except OSError as e:
        _fail(4, f"raw write failed: {e}")

    typer.echo(f"written: {written}")


def main() -> None:
    """Console-script entrypoint."""
    app()


def _resolve_transcript(
    url: str,
    meta: VideoMeta,
    *,
    model: str,
    force_whisper: bool,
    transcript_language: str,
    verbose: bool,
) -> tuple[str, str]:
    source = choose_transcript_source(meta, lang=transcript_language, force_whisper=force_whisper)

    if source == "captions":
        _debug(verbose, "fetching captions")
        transcript = _with_network_retry(fetch_captions, url, transcript_language, verbose=verbose)
        if transcript and transcript.strip():
            return transcript, "yt-dlp"
        _debug(verbose, "captions empty, falling back to whisper")

    _debug(verbose, f"using whisper model {model}")
    with tempfile.TemporaryDirectory() as td:
        audio_path = _with_network_retry(download_audio, url, Path(td), verbose=verbose)
        transcript = transcribe_audio(
            audio_path,
            model=model,
            language=transcript_language,
            verbose=verbose,
        )
    return transcript, f"whisper-{model}"


def _with_network_retry[T](
    fn: Callable[..., T],
    *args: object,
    verbose: bool,
    **kwargs: object,
) -> T:
    for attempt in range(2):
        try:
            return fn(*args, **kwargs)
        except ExtractorError as e:
            if e.kind == "network" and attempt == 0:
                _debug(verbose, f"network failure, retrying once: {e}")
                time.sleep(5)
                continue
            raise
    raise AssertionError("unreachable retry state")


def _coerce_meta(raw: Mapping[str, Any]) -> VideoMeta:
    video_id = raw.get("id")
    title = raw.get("title")
    if not isinstance(video_id, str) or not video_id.strip():
        raise ValueError("metadata missing non-empty id")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("metadata missing non-empty title")

    captions_raw = raw.get("captions") or []
    if not isinstance(captions_raw, list) or not all(isinstance(x, str) for x in captions_raw):
        raise ValueError("metadata captions must be list[str]")

    kinds_raw = raw.get("caption_kinds") or {}
    if not isinstance(kinds_raw, Mapping):
        raise ValueError("metadata caption_kinds must be a mapping")
    caption_kinds: dict[str, Literal["manual", "auto"]] = {}
    for key, value in kinds_raw.items():
        if not isinstance(key, str) or value not in {"manual", "auto"}:
            raise ValueError("metadata caption_kinds values must be 'manual' or 'auto'")
        caption_kinds[key] = cast(Literal["manual", "auto"], value)

    return {
        "id": video_id.strip(),
        "title": title.strip(),
        "channel": raw.get("channel"),
        "channel_url": raw.get("channel_url"),
        "published_at": raw.get("published_at"),
        "duration_seconds": raw.get("duration_seconds"),
        "captions": captions_raw,
        "caption_kinds": caption_kinds,
    }


def _existing_source_url(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return None
    data = yaml.safe_load(text[4:end]) or {}
    if not isinstance(data, dict):
        return None
    source_url = data.get("source_url")
    return source_url if isinstance(source_url, str) else None


def _source_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def _slug_date(meta: VideoMeta) -> date:
    published_at = meta["published_at"]
    if isinstance(published_at, datetime):
        return published_at.date()
    if isinstance(published_at, date):
        return published_at
    return datetime.now(UTC).date()


def _dry_run_preview(content: str, body_chars: int = 200) -> str:
    if not content.startswith("---\n"):
        return content[:body_chars]
    try:
        end = content.index("\n---\n", 4) + len("\n---\n")
    except ValueError:
        return content[:body_chars]
    frontmatter = content[:end]
    body = content[end:].lstrip("\n")
    return f"{frontmatter}\n{body[:body_chars]}"


def _looks_like_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _configure_logging(verbose: bool) -> None:
    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _debug(verbose: bool, message: str) -> None:
    if verbose:
        typer.echo(message, err=True)
        logger.info(message)


def _fail(code: int, message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    if code == 1:
        traceback.print_exc()
    raise typer.Exit(code)
