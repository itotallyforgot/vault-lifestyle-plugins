"""Typer CLI for the `vault-yt` console script."""

from __future__ import annotations

import logging
import os
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, TypedDict, cast
from urllib.parse import urlparse

import typer
import yaml
from pydantic import ValidationError
from vault_resolver import VaultPathError, resolve_vault_path

from vault_yt.extractor import ExtractorError, download_audio, fetch_captions, fetch_meta
from vault_yt.inputs import InputExpansionError, WorkItem, expand_inputs
from vault_yt.manifest import (
    ManifestError,
    ManifestItem,
    WorkInput,
    default_manifest_path,
    load_manifest,
    new_manifest,
    save_manifest,
    update_item_status,
)
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


@dataclass(frozen=True)
class IngestOutcome:
    """Result of processing one video URL."""

    status: Literal["written", "existing", "dry_run"]
    path: Path
    source_url: str
    title: str | None = None
    transcript_source: str | None = None
    transcript_language: str | None = None


@app.command("vault-yt")
def command(
    url: Annotated[
        str | None,
        typer.Argument(help="YouTube URL to ingest."),
    ] = None,
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
    url_file: Annotated[
        Path | None,
        typer.Option("--url-file", help="Text file containing one YouTube URL per line."),
    ] = None,
    playlist: Annotated[
        str | None,
        typer.Option("--playlist", help="YouTube playlist URL to ingest as a batch."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum pending videos to process this run."),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Stable staging run ID for batch/resume."),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume an existing batch manifest."),
    ] = False,
) -> None:
    """Fetch a transcript and write `<vault>/raw/<slug>.md`."""
    _configure_logging(verbose)

    try:
        vault_path = resolve_vault_path(vault)
    except VaultPathError as e:
        _fail(3, f"vault error: {e}")

    raw_dir = vault_path / "raw"
    if not raw_dir.is_dir():
        _fail(4, f"raw directory missing: {raw_dir}")
    if not os.access(raw_dir, os.W_OK):
        _fail(4, f"raw directory is not writable: {raw_dir}")

    batch_inputs = _batch_inputs(url_file=url_file, playlist=playlist)
    if batch_inputs:
        _run_batch(
            batch_inputs,
            vault_path=vault_path,
            force=force,
            force_whisper=force_whisper,
            whisper_model=whisper_model,
            transcript_language=transcript_language,
            verbose=verbose,
            dry_run=dry_run,
            limit=limit,
            run_id=run_id,
            resume=resume,
        )
        raise typer.Exit(0)

    if url is None:
        _fail(2, "missing url or batch input")

    _ingest_url(
        url,
        vault_path=vault_path,
        force=force,
        force_whisper=force_whisper,
        whisper_model=whisper_model,
        transcript_language=transcript_language,
        verbose=verbose,
        dry_run=dry_run,
    )


def _ingest_url(
    url: str,
    *,
    vault_path: Path,
    force: bool,
    force_whisper: bool,
    whisper_model: str | None,
    transcript_language: str,
    verbose: bool,
    dry_run: bool,
) -> IngestOutcome:
    if not _looks_like_url(url):
        _fail(2, f"malformed url: {url}")

    raw_dir = vault_path / "raw"
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
            return IngestOutcome(
                status="existing",
                path=target,
                source_url=source_url,
                title=meta["title"],
            )
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
        return IngestOutcome(
            status="dry_run",
            path=target,
            source_url=source_url,
            title=meta["title"],
            transcript_source=transcript_source,
            transcript_language=transcript_language,
        )

    try:
        written = write(target, content, force=force)
    except FileExistsError as e:
        _fail(9, f"collision: {e}")
    except OSError as e:
        _fail(4, f"raw write failed: {e}")

    typer.echo(f"written: {written}")
    return IngestOutcome(
        status="written",
        path=written,
        source_url=source_url,
        title=meta["title"],
        transcript_source=transcript_source,
        transcript_language=transcript_language,
    )


def _run_batch(
    inputs: list[str | Path],
    *,
    vault_path: Path,
    force: bool,
    force_whisper: bool,
    whisper_model: str | None,
    transcript_language: str,
    verbose: bool,
    dry_run: bool,
    limit: int | None,
    run_id: str | None,
    resume: bool,
) -> None:
    try:
        work_items = expand_inputs(inputs)
    except InputExpansionError as e:
        _fail(2, f"input expansion error: {e}")

    selected_run_id = run_id or _default_run_id()
    manifest_path = default_manifest_path(vault_path, selected_run_id)

    if dry_run:
        typer.echo(f"would process: {len(work_items)} videos")
        typer.echo(f"would write manifest: {manifest_path}")
        raise typer.Exit(0)

    if resume and manifest_path.exists():
        manifest = load_manifest(manifest_path)
    else:
        manifest = new_manifest(
            run_id=selected_run_id,
            vault_path=vault_path,
            inputs=[_work_input(value) for value in inputs],
            options={
                "force": force,
                "force_whisper": force_whisper,
                "whisper_model": whisper_model,
                "transcript_language": transcript_language,
                "limit": limit,
            },
            items=[_manifest_item(index, item) for index, item in enumerate(work_items)],
        )
        save_manifest(manifest_path, manifest)

    pending = [item for item in manifest.items if item.status == "pending"]
    to_process = pending[:limit] if limit is not None else pending
    written = 0
    skipped = 0
    failed = 0

    for item in to_process:
        manifest = update_item_status(manifest, item.video_id, "processing")
        save_manifest(manifest_path, manifest)
        try:
            outcome = _ingest_url(
                item.url,
                vault_path=vault_path,
                force=force,
                force_whisper=force_whisper,
                whisper_model=whisper_model,
                transcript_language=transcript_language,
                verbose=verbose,
                dry_run=False,
            )
        except typer.Exit as e:
            failed += 1
            manifest = update_item_status(
                manifest,
                item.video_id,
                "failed",
                error=ManifestError(
                    kind=f"exit_{e.exit_code}",
                    message=f"vault-yt exited with code {e.exit_code}",
                    retryable=e.exit_code == 5,
                ),
            )
            save_manifest(manifest_path, manifest)
            continue

        status: Literal["raw_written", "skipped_existing"]
        if outcome.status == "existing":
            skipped += 1
            status = "skipped_existing"
        else:
            written += 1
            status = "raw_written"
        manifest = update_item_status(
            manifest,
            item.video_id,
            status,
            title=outcome.title,
            raw_path=str(outcome.path.relative_to(vault_path)),
            transcript_source=outcome.transcript_source,
            transcript_language=outcome.transcript_language,
        )
        save_manifest(manifest_path, manifest)

    remaining = sum(1 for item in manifest.items if item.status == "pending")
    typer.echo(f"batch run: {manifest.run_id}")
    typer.echo(f"manifest: {manifest_path}")
    typer.echo(f"written: {written}")
    typer.echo(f"skipped_existing: {skipped}")
    typer.echo(f"failed: {failed}")
    typer.echo(f"pending: {remaining}")

    if failed:
        raise typer.Exit(1)


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


def _batch_inputs(*, url_file: Path | None, playlist: str | None) -> list[str | Path]:
    values: list[str | Path] = []
    if url_file is not None:
        values.append(url_file)
    if playlist is not None:
        values.append(playlist)
    return values


def _work_input(value: str | Path) -> WorkInput:
    if isinstance(value, Path):
        return WorkInput(kind="url_file", ref=str(value))
    return WorkInput(kind="playlist" if "list=" in value else "video", ref=value)


def _manifest_item(position: int, item: WorkItem) -> ManifestItem:
    return ManifestItem(
        video_id=item.video_id,
        url=item.url,
        title=None,
        position=position,
        source_url=item.url,
    )


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ-youtube")


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
