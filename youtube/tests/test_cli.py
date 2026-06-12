"""Tests for the vault-yt CLI entrypoint."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from vault_yt import cli as cli_module
from vault_yt.extractor import ExtractorError
from vault_yt.manifest import (
    ManifestItem,
    add_candidate_finding,
    default_manifest_path,
    load_manifest,
    new_manifest,
    save_manifest,
)
from vault_yt.slug import make
from vault_yt.whisper_fallback import TranscriptResult, WhisperUnavailableError

runner = CliRunner()


def _whisper(text: str, quality: str = "ok") -> TranscriptResult:
    """Build a stub `transcribe_audio` return value for CLI tests."""
    return TranscriptResult(text=text, quality=quality)  # type: ignore[arg-type]


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "raw").mkdir(parents=True)
    (vault / "wiki").mkdir()
    return vault


def _meta(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "abc123",
        "title": "Video Title",
        "channel": "Example Channel",
        "channel_url": "https://www.youtube.com/@example",
        "published_at": date(2026, 5, 5),
        "duration_seconds": 123,
        "captions": ["en"],
        "caption_kinds": {"en": "manual"},
    }
    base.update(overrides)
    return base


def _raw_path(vault: Path, meta: dict[str, Any]) -> Path:
    return vault / "raw" / f"{make(meta['id'], meta['title'], meta['published_at'])}.md"


def _install_caption_path(monkeypatch, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = meta or _meta()
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: selected)
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": "caption text")
    return selected


def test_help_imports_cleanly() -> None:
    result = runner.invoke(cli_module.app, ["--help"])

    assert result.exit_code == 0
    assert "vault-yt" in result.output


def test_captions_path_writes_raw_file(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _install_caption_path(monkeypatch)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault)],
    )

    path = _raw_path(vault, meta)
    assert result.exit_code == 0
    assert f"written: {path}" in result.output
    assert path.exists()
    text = path.read_text()
    assert "transcript_source: yt-dlp" in text
    assert "caption text" in text


def test_transcript_language_selects_non_english_captions(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=["fr"], caption_kinds={"fr": "manual"})
    seen: dict[str, str | None] = {"lang": None}
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)

    def fetch_captions(url, lang="en"):
        seen["lang"] = lang
        return "texte de sous-titres"

    def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("audio download should not run when requested captions exist")

    monkeypatch.setattr(cli_module, "fetch_captions", fetch_captions)
    monkeypatch.setattr(cli_module, "download_audio", fail_if_called)

    result = runner.invoke(
        cli_module.app,
        [
            "https://youtu.be/abc123",
            "--vault",
            str(vault),
            "--transcript-language",
            "fr",
        ],
    )

    assert result.exit_code == 0
    assert seen["lang"] == "fr"
    assert "texte de sous-titres" in _raw_path(vault, meta).read_text()


def test_whisper_path_writes_raw_file(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="base", language=None, verbose=False: _whisper("whisper text"),
    )

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault)],
    )

    path = _raw_path(vault, meta)
    assert result.exit_code == 0
    assert path.exists()
    text = path.read_text()
    assert "transcript_source: whisper-base" in text
    assert "whisper text" in text


def test_suspect_whisper_transcript_stamps_frontmatter(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="base", language=None, verbose=False: _whisper(
            "la la la", quality="suspect"
        ),
    )

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(vault)])

    assert result.exit_code == 0
    text = _raw_path(vault, meta).read_text()
    assert "transcript_quality: suspect" in text


def test_clean_whisper_transcript_omits_quality_frontmatter(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="base", language=None, verbose=False: _whisper("clean text"),
    )

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "transcript_quality" not in _raw_path(vault, meta).read_text()


def test_whisper_tiny_model_writes_raw_file(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="tiny", language=None, verbose=False: _whisper("tiny whisper text"),
    )

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault), "--whisper-model", "tiny"],
    )

    assert result.exit_code == 0
    assert "transcript_source: whisper-tiny" in _raw_path(vault, meta).read_text()


def test_whisper_model_env_is_used(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    seen: dict[str, str | None] = {"model": None}
    monkeypatch.setenv("VAULT_YT_WHISPER_MODEL", "tiny")
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")

    def transcribe(audio, model="base", language=None, verbose=False):
        seen["model"] = model
        return _whisper("env whisper text")

    monkeypatch.setattr(cli_module, "transcribe_audio", transcribe)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault)],
    )

    assert result.exit_code == 0
    assert seen["model"] == "tiny"
    assert "transcript_source: whisper-tiny" in _raw_path(vault, meta).read_text()


def test_dry_run_prints_target_without_writing(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _install_caption_path(monkeypatch)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault), "--dry-run"],
    )

    path = _raw_path(vault, meta)
    assert result.exit_code == 0
    assert f"would write: {path}" in result.output
    assert "caption text" in result.output
    assert not path.exists()


def test_existing_matching_file_is_noop_without_force(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta()
    path = _raw_path(vault, meta)
    path.write_text("---\nsource_url: https://youtu.be/abc123\n---\n\nold")

    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)

    def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("transcript fetch should not run on idempotent no-op")

    monkeypatch.setattr(cli_module, "fetch_captions", fail_if_called)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault)],
    )

    assert result.exit_code == 0
    assert f"existing: {path}" in result.output
    assert path.read_text().endswith("old")


def test_existing_file_with_force_overwrites(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _install_caption_path(monkeypatch)
    path = _raw_path(vault, meta)
    path.write_text("---\nsource_url: https://youtu.be/abc123\n---\n\nold")

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault), "--force"],
    )

    assert result.exit_code == 0
    assert "written:" in result.output
    assert "caption text" in path.read_text()


def test_existing_mismatched_file_is_collision(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta()
    path = _raw_path(vault, meta)
    path.write_text("---\nsource_url: https://youtu.be/different\n---\n\nold")
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault)],
    )

    assert result.exit_code == 9
    assert "collision:" in result.output


def test_invalid_url_exits_2(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    result = runner.invoke(cli_module.app, ["not-a-url", "--vault", str(vault)])

    assert result.exit_code == 2
    assert "malformed url" in result.output


def test_unresolvable_vault_exits_3(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(missing)])

    assert result.exit_code == 3
    assert "vault error" in result.output


def test_whisper_unavailable_exits_6(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")

    def unavailable(*args, **kwargs):
        raise WhisperUnavailableError("no whisper")

    monkeypatch.setattr(cli_module, "transcribe_audio", unavailable)

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(vault)])

    assert result.exit_code == 6
    assert "whisper unavailable" in result.output


def test_empty_transcript_exits_8(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: _meta())
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": "")
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="base", language=None, verbose=False: _whisper(""),
    )

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(vault)])

    assert result.exit_code == 8
    assert "empty transcript from whisper-base" in result.output


def test_empty_captions_fall_back_to_whisper(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta()
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": "")
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="base", language=None, verbose=False: _whisper(
            "whisper after empty captions"
        ),
    )

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(vault)])

    assert result.exit_code == 0
    assert "whisper after empty captions" in _raw_path(vault, meta).read_text()


def test_network_error_retries_once(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    calls = {"count": 0}

    def flaky_meta(url: str) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ExtractorError("network", "temporary failure")
        return _meta()

    monkeypatch.setattr(cli_module, "fetch_meta", flaky_meta)
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": "caption text")
    monkeypatch.setattr(cli_module.time, "sleep", lambda seconds: None)

    result = runner.invoke(cli_module.app, ["https://youtu.be/abc123", "--vault", str(vault)])

    assert result.exit_code == 0
    assert calls["count"] == 2


def test_force_whisper_skips_caption_fetch(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta()
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="base", language=None, verbose=False: _whisper("whisper text"),
    )

    def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("caption fetch should not run when force whisper is set")

    monkeypatch.setattr(cli_module, "fetch_captions", fail_if_called)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault), "--force-whisper"],
    )

    assert result.exit_code == 0
    assert "whisper text" in _raw_path(vault, meta).read_text()


def test_force_whisper_passes_transcript_language_hint(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=["fr"], caption_kinds={"fr": "manual"})
    seen: dict[str, str | None] = {"language": None}
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")

    def transcribe(audio, model="base", language=None, verbose=False):
        seen["language"] = language
        return _whisper("texte whisper")

    monkeypatch.setattr(cli_module, "transcribe_audio", transcribe)

    result = runner.invoke(
        cli_module.app,
        [
            "https://youtu.be/abc123",
            "--vault",
            str(vault),
            "--force-whisper",
            "--transcript-language",
            "fr",
        ],
    )

    assert result.exit_code == 0
    assert seen["language"] == "fr"
    assert "texte whisper" in _raw_path(vault, meta).read_text()


def test_verbose_flag_passes_through_to_whisper(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    seen: dict[str, bool | None] = {"verbose": None}
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")

    def transcribe(audio, model="base", language=None, verbose=False):
        seen["verbose"] = verbose
        return _whisper("whisper text")

    monkeypatch.setattr(cli_module, "transcribe_audio", transcribe)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault), "--verbose"],
    )

    assert result.exit_code == 0
    assert seen["verbose"] is True


def test_url_file_batch_processes_limited_items_and_writes_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "https://youtu.be/abc123\nhttps://youtu.be/def456\n",
        encoding="utf-8",
    )
    metas = {
        "https://youtu.be/abc123": _meta(id="abc123", title="Alpha"),
        "https://youtu.be/def456": _meta(id="def456", title="Beta"),
    }
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: metas[url])
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": f"caption for {url}")

    result = runner.invoke(
        cli_module.app,
        [
            "--url-file",
            str(url_file),
            "--limit",
            "1",
            "--run-id",
            "run-123",
            "--vault",
            str(vault),
        ],
    )

    manifest = load_manifest(default_manifest_path(vault, "run-123"))
    assert result.exit_code == 0
    assert "batch run: run-123" in result.output
    assert "written: 1" in result.output
    assert "pending: 1" in result.output
    assert [item.video_id for item in manifest.items] == ["abc123", "def456"]
    assert manifest.items[0].status == "raw_written"
    assert manifest.items[0].title == "Alpha"
    assert manifest.items[0].raw_path == "raw/2026-05-05-youtube-abc123-alpha.md"
    assert manifest.items[1].status == "pending"
    assert (vault / manifest.items[0].raw_path).exists()


def test_traversing_run_id_is_rejected_before_any_write(tmp_path: Path, monkeypatch) -> None:
    """A hostile --run-id must exit 2 and not escape the vault staging area."""
    vault = _vault(tmp_path)
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://youtu.be/abc123\n", encoding="utf-8")
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: _meta())
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": "caption text")

    result = runner.invoke(
        cli_module.app,
        [
            "--url-file",
            str(url_file),
            "--run-id",
            "../../../../tmp/evil",
            "--vault",
            str(vault),
        ],
    )

    assert result.exit_code == 2
    assert "invalid --run-id" in result.output
    assert not (tmp_path / "tmp" / "evil").exists()


def test_non_youtube_single_url_is_rejected(tmp_path: Path, monkeypatch) -> None:
    """Single-URL mode must enforce the YouTube host allow-list, not just scheme."""
    vault = _vault(tmp_path)

    def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("yt-dlp must not be reached for a non-YouTube host")

    monkeypatch.setattr(cli_module, "fetch_meta", fail_if_called)

    result = runner.invoke(
        cli_module.app,
        ["https://evil.example/watch?v=abc123", "--vault", str(vault)],
    )

    assert result.exit_code == 2
    assert "unsupported YouTube url" in result.output


def test_handoff_batch_processes_items_and_preserves_discovered_titles(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    handoff = tmp_path / "engineering.jsonl"
    handoff.write_text(
        '{"video_id":"abc123","title":"Handoff Alpha","source_provider":"youtube-mcp",'
        '"playlist_id":"PLENG","playlist_title":"Engineering","playlist_url":"https://youtube.com/playlist?list=PLENG","playlist_index":1}\n'
        '{"video_id":"def456","title":"Handoff Beta","source_provider":"youtube-mcp",'
        '"playlist_id":"PLENG","playlist_title":"Engineering","playlist_url":"https://youtube.com/playlist?list=PLENG","playlist_index":2}\n',
        encoding="utf-8",
    )
    metas = {
        "https://youtu.be/abc123": _meta(id="abc123", title="Fetched Alpha"),
        "https://youtu.be/def456": _meta(id="def456", title="Fetched Beta"),
    }
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: metas[url])
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": f"caption for {url}")

    result = runner.invoke(
        cli_module.app,
        [
            "--handoff",
            str(handoff),
            "--limit",
            "1",
            "--run-id",
            "run-123",
            "--vault",
            str(vault),
        ],
    )

    manifest = load_manifest(default_manifest_path(vault, "run-123"))
    assert result.exit_code == 0
    assert manifest.inputs[0].kind == "handoff"
    assert [item.video_id for item in manifest.items] == ["abc123", "def456"]
    assert manifest.items[0].title == "Fetched Alpha"
    assert manifest.items[0].source_provider == "youtube-mcp"
    assert manifest.items[0].playlist_id == "PLENG"
    assert manifest.items[0].playlist_title == "Engineering"
    assert manifest.items[0].playlist_url == "https://youtube.com/playlist?list=PLENG"
    assert manifest.items[0].playlist_index == 1
    assert manifest.items[0].appearances[0]["source_provider"] == "youtube-mcp"
    assert manifest.items[1].title == "Handoff Beta"
    assert manifest.items[1].status == "pending"

    raw_text = (vault / manifest.items[0].raw_path).read_text()
    assert "youtube_video_id: abc123" in raw_text
    assert "canonical_url: https://youtu.be/abc123" in raw_text
    assert "bulk_run_id: run-123" in raw_text
    assert "source_provider: youtube-mcp" in raw_text
    assert "playlist_id: PLENG" in raw_text
    assert "playlist_title: Engineering" in raw_text
    assert "playlist_index: 1" in raw_text


def test_batch_dedupes_across_url_file_and_handoff(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://youtu.be/abc123\n", encoding="utf-8")
    handoff = tmp_path / "engineering.jsonl"
    handoff.write_text(
        '{"video_id":"abc123","title":"Handoff Alpha","source_provider":"youtube-mcp"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: _meta(id="abc123", title="Alpha"))
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": "caption")

    result = runner.invoke(
        cli_module.app,
        [
            "--url-file",
            str(url_file),
            "--handoff",
            str(handoff),
            "--run-id",
            "run-123",
            "--vault",
            str(vault),
        ],
    )

    manifest = load_manifest(default_manifest_path(vault, "run-123"))
    assert result.exit_code == 0
    assert [item.video_id for item in manifest.items] == ["abc123"]
    assert manifest.summary == {"raw_written": 1}


def test_export_playlist_writes_handoff_without_ingesting(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    output = tmp_path / "engineering.jsonl"
    seen: dict[str, object] = {}

    def export_playlist_handoff(
        playlist_url, output_path, *, browser=None, cookies=None, verbose=False
    ):
        seen["playlist_url"] = playlist_url
        seen["output_path"] = output_path
        seen["browser"] = browser
        seen["cookies"] = cookies
        seen["verbose"] = verbose
        output_path.write_text('{"video_id":"abc123"}\n', encoding="utf-8")
        return output_path

    monkeypatch.setattr(cli_module, "export_playlist_handoff", export_playlist_handoff)
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: (_ for _ in ()).throw(AssertionError))

    result = runner.invoke(
        cli_module.app,
        [
            "--export-playlist",
            "https://www.youtube.com/playlist?list=PLENG",
            "--browser",
            "firefox:default",
            "--output",
            str(output),
            "--vault",
            str(vault),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert f"handoff written: {output}" in result.output
    assert seen == {
        "playlist_url": "https://www.youtube.com/playlist?list=PLENG",
        "output_path": output,
        "browser": "firefox:default",
        "cookies": None,
        "verbose": True,
    }
    assert output.exists()


def test_export_playlist_does_not_require_vault(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "engineering.jsonl"

    def export_playlist_handoff(
        playlist_url, output_path, *, browser=None, cookies=None, verbose=False
    ):
        output_path.write_text('{"video_id":"abc123"}\n', encoding="utf-8")
        return output_path

    monkeypatch.delenv("VAULT_PATH", raising=False)
    monkeypatch.setattr(cli_module, "export_playlist_handoff", export_playlist_handoff)

    result = runner.invoke(
        cli_module.app,
        [
            "--export-playlist",
            "https://www.youtube.com/playlist?list=PLENG",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert f"handoff written: {output}" in result.output


def test_validate_handoff_does_not_require_vault(tmp_path: Path, monkeypatch) -> None:
    handoff = tmp_path / "engineering.jsonl"
    handoff.write_text('{"video_id":"abc123","title":"Alpha"}\n', encoding="utf-8")
    monkeypatch.delenv("VAULT_PATH", raising=False)

    result = runner.invoke(cli_module.app, ["--validate-handoff", str(handoff)])

    assert result.exit_code == 0
    assert "handoff valid:" in result.output
    assert "1 records" in result.output


def test_validate_handoff_reports_errors_without_vault(tmp_path: Path, monkeypatch) -> None:
    handoff = tmp_path / "bad.jsonl"
    handoff.write_text('{"title":"No ID"}\n', encoding="utf-8")
    monkeypatch.delenv("VAULT_PATH", raising=False)

    result = runner.invoke(cli_module.app, ["--validate-handoff", str(handoff)])

    assert result.exit_code == 2
    assert "handoff invalid:" in result.output
    assert "bad.jsonl:1" in result.output


def test_batch_resume_skips_completed_manifest_items(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "https://youtu.be/abc123\nhttps://youtu.be/def456\n",
        encoding="utf-8",
    )
    metas = {
        "https://youtu.be/abc123": _meta(id="abc123", title="Alpha"),
        "https://youtu.be/def456": _meta(id="def456", title="Beta"),
    }
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: metas[url])
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": f"caption for {url}")

    first = runner.invoke(
        cli_module.app,
        [
            "--url-file",
            str(url_file),
            "--limit",
            "1",
            "--run-id",
            "run-123",
            "--vault",
            str(vault),
        ],
    )
    second = runner.invoke(
        cli_module.app,
        [
            "--url-file",
            str(url_file),
            "--limit",
            "1",
            "--run-id",
            "run-123",
            "--resume",
            "--vault",
            str(vault),
        ],
    )

    manifest = load_manifest(default_manifest_path(vault, "run-123"))
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert manifest.summary == {"raw_written": 2}
    assert "written: 1" in second.output


def test_batch_records_item_failure_and_continues(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "https://youtu.be/abc123\nhttps://youtu.be/def456\n",
        encoding="utf-8",
    )

    def fetch_meta(url: str) -> dict[str, Any]:
        if url.endswith("abc123"):
            raise ExtractorError("network", "temporary badness")
        return _meta(id="def456", title="Beta")

    monkeypatch.setattr(cli_module, "fetch_meta", fetch_meta)
    monkeypatch.setattr(cli_module, "fetch_captions", lambda url, lang="en": f"caption for {url}")
    monkeypatch.setattr(cli_module.time, "sleep", lambda seconds: None)

    result = runner.invoke(
        cli_module.app,
        [
            "--url-file",
            str(url_file),
            "--run-id",
            "run-123",
            "--vault",
            str(vault),
        ],
    )

    manifest = load_manifest(default_manifest_path(vault, "run-123"))
    assert result.exit_code == 1
    assert manifest.summary == {"failed": 1, "raw_written": 1}
    assert manifest.items[0].status == "failed"
    assert manifest.items[0].error is not None
    assert manifest.items[0].error.retryable is True
    assert manifest.items[1].status == "raw_written"


def test_batch_dry_run_expands_inputs_without_processing(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://youtu.be/abc123\n", encoding="utf-8")
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: (_ for _ in ()).throw(AssertionError))

    result = runner.invoke(
        cli_module.app,
        ["--url-file", str(url_file), "--dry-run", "--vault", str(vault)],
    )

    assert result.exit_code == 0
    assert "would process: 1 videos" in result.output
    assert not (vault / ".vault-lifestyle").exists()


def test_report_prints_existing_manifest_summary(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    manifest = new_manifest(
        run_id="run-123",
        vault_path=vault,
        inputs=[],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="Alpha",
                position=0,
                status="raw_written",
                raw_path="raw/alpha.md",
            )
        ],
    )
    save_manifest(default_manifest_path(vault, "run-123"), manifest)

    result = runner.invoke(
        cli_module.app,
        ["--report", "--run-id", "run-123", "--vault", str(vault)],
    )

    assert result.exit_code == 0
    assert "run: run-123" in result.output
    assert "raw_written: 1" in result.output
    assert "raw/alpha.md" in result.output


def test_add_finding_updates_manifest(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    manifest = new_manifest(
        run_id="run-123",
        vault_path=vault,
        inputs=[],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="Alpha",
                position=0,
                status="raw_written",
                raw_path="raw/alpha.md",
                source_url="https://youtu.be/abc123",
            )
        ],
    )
    save_manifest(default_manifest_path(vault, "run-123"), manifest)

    result = runner.invoke(
        cli_module.app,
        [
            "--add-finding",
            "--run-id",
            "run-123",
            "--video-id",
            "abc123",
            "--claim",
            "Rust ownership prevents data races.",
            "--transcript-span",
            "cue:1-2",
            "--confidence",
            "0.8",
            "--vault",
            str(vault),
        ],
    )

    updated = load_manifest(default_manifest_path(vault, "run-123"))
    assert result.exit_code == 0
    assert "added finding: abc123-finding-1" in result.output
    assert updated.items[0].candidate_findings[0].claim == "Rust ownership prevents data races."
    assert updated.items[0].candidate_findings_state == "ready"


def test_add_evidence_updates_manifest(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    manifest = new_manifest(
        run_id="run-123",
        vault_path=vault,
        inputs=[],
        options={},
        items=[
            ManifestItem(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="Alpha",
                position=0,
            )
        ],
    )
    manifest = add_candidate_finding(
        manifest,
        "abc123",
        claim="Rust ownership prevents data races.",
        transcript_span="cue:1-2",
    )
    save_manifest(default_manifest_path(vault, "run-123"), manifest)

    result = runner.invoke(
        cli_module.app,
        [
            "--add-evidence",
            "--run-id",
            "run-123",
            "--video-id",
            "abc123",
            "--finding-id",
            "abc123-finding-1",
            "--evidence-url",
            "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
            "--verifier",
            "Alex",
            "--verification-result",
            "accepted",
            "--vault",
            str(vault),
        ],
    )

    updated = load_manifest(default_manifest_path(vault, "run-123"))
    assert result.exit_code == 0
    assert "added evidence: abc123-finding-1 accepted" in result.output
    assert updated.items[0].verification_state == "complete"
    assert updated.items[0].candidate_findings[0].verification_status == "accepted"
