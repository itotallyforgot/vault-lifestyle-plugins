"""Tests for the vault-yt CLI entrypoint."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from vault_yt import cli as cli_module
from vault_yt.extractor import ExtractorError
from vault_yt.slug import make
from vault_yt.whisper_fallback import WhisperUnavailableError

runner = CliRunner()


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
    return vault / "raw" / f"{make(meta['id'], meta['title'])}.md"


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
        lambda audio, model="base", language=None, verbose=False: "whisper text",
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


def test_whisper_tiny_model_writes_raw_file(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    meta = _meta(captions=[], caption_kinds={})
    monkeypatch.setattr(cli_module, "fetch_meta", lambda url: meta)
    monkeypatch.setattr(cli_module, "download_audio", lambda url, dest_dir: dest_dir / "audio.m4a")
    monkeypatch.setattr(
        cli_module,
        "transcribe_audio",
        lambda audio, model="tiny", language=None, verbose=False: "tiny whisper text",
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
        return "env whisper text"

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
        lambda audio, model="base", language=None, verbose=False: "",
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
        lambda audio, model="base", language=None, verbose=False: "whisper after empty captions",
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
        lambda audio, model="base", language=None, verbose=False: "whisper text",
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
        return "texte whisper"

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
        return "whisper text"

    monkeypatch.setattr(cli_module, "transcribe_audio", transcribe)

    result = runner.invoke(
        cli_module.app,
        ["https://youtu.be/abc123", "--vault", str(vault), "--verbose"],
    )

    assert result.exit_code == 0
    assert seen["verbose"] is True
