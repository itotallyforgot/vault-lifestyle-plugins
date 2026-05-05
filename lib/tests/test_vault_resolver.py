"""Tests for vault_resolver.resolve_vault_path + helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from vault_resolver import (
    VaultPathError,
    _looks_like_vault,
    resolve_vault_path,
)


def _make_vault(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    return root


def _make_template_vault(root: Path) -> Path:
    """Vault shape with `_templates/` instead of `wiki/` (fresh public clone)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir()
    (root / "_templates").mkdir()
    return root


# ---------- _looks_like_vault ----------


def test_looks_like_vault_accepts_raw_plus_wiki(tmp_path: Path) -> None:
    assert _looks_like_vault(_make_vault(tmp_path / "v"))


def test_looks_like_vault_accepts_raw_plus_templates(tmp_path: Path) -> None:
    assert _looks_like_vault(_make_template_vault(tmp_path / "v"))


def test_looks_like_vault_rejects_missing_raw(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    assert not _looks_like_vault(tmp_path)


def test_looks_like_vault_rejects_raw_only(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    assert not _looks_like_vault(tmp_path)


# ---------- resolve_vault_path: precedence ----------


def test_resolve_arg_takes_precedence_over_env_and_config(tmp_path: Path) -> None:
    arg_v = _make_vault(tmp_path / "arg")
    env_v = _make_vault(tmp_path / "env")
    cfg_v = _make_vault(tmp_path / "cfg")
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f'vault_path = "{cfg_v}"\n')

    resolved = resolve_vault_path(
        arg_v,
        env={"VAULT_PATH": str(env_v)},
        config_path=cfg,
    )
    assert resolved == arg_v.resolve()


def test_resolve_falls_back_to_env_when_no_arg(tmp_path: Path) -> None:
    env_v = _make_vault(tmp_path / "env")
    resolved = resolve_vault_path(
        None,
        env={"VAULT_PATH": str(env_v)},
        config_path=tmp_path / "absent.toml",
    )
    assert resolved == env_v.resolve()


def test_resolve_falls_back_to_config_when_no_arg_or_env(tmp_path: Path) -> None:
    cfg_v = _make_vault(tmp_path / "cfg")
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f'vault_path = "{cfg_v}"\n')
    resolved = resolve_vault_path(None, env={}, config_path=cfg)
    assert resolved == cfg_v.resolve()


def test_resolve_template_vault_works(tmp_path: Path) -> None:
    v = _make_template_vault(tmp_path / "v")
    resolved = resolve_vault_path(v, env={}, config_path=tmp_path / "absent.toml")
    assert resolved == v.resolve()


# ---------- resolve_vault_path: failures ----------


def test_resolve_raises_when_nothing_provided(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError, match="no vault path resolved"):
        resolve_vault_path(None, env={}, config_path=tmp_path / "absent.toml")


def test_resolve_raises_when_arg_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError, match="does not exist"):
        resolve_vault_path(tmp_path / "ghost", env={}, config_path=tmp_path / "absent.toml")


def test_resolve_raises_when_arg_is_not_a_dir(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("hi")
    with pytest.raises(VaultPathError, match="not a directory"):
        resolve_vault_path(f, env={}, config_path=tmp_path / "absent.toml")


def test_resolve_raises_when_path_is_not_a_vault(tmp_path: Path) -> None:
    not_a_vault = tmp_path / "junk"
    not_a_vault.mkdir()
    with pytest.raises(VaultPathError, match="does not look like a vault"):
        resolve_vault_path(
            not_a_vault, env={}, config_path=tmp_path / "absent.toml"
        )


def test_resolve_raises_when_env_path_invalid(tmp_path: Path) -> None:
    with pytest.raises(VaultPathError, match="does not exist"):
        resolve_vault_path(
            None,
            env={"VAULT_PATH": str(tmp_path / "ghost")},
            config_path=tmp_path / "absent.toml",
        )


# ---------- resolve_vault_path: input shapes ----------


def test_resolve_accepts_string_arg(tmp_path: Path) -> None:
    v = _make_vault(tmp_path / "v")
    resolved = resolve_vault_path(str(v), env={}, config_path=tmp_path / "absent.toml")
    assert resolved == v.resolve()


def test_resolve_accepts_path_arg(tmp_path: Path) -> None:
    v = _make_vault(tmp_path / "v")
    resolved = resolve_vault_path(v, env={}, config_path=tmp_path / "absent.toml")
    assert resolved == v.resolve()


def test_resolve_expands_user_in_arg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    v = _make_vault(tmp_path / "vault")
    resolved = resolve_vault_path("~/vault", env={}, config_path=tmp_path / "absent.toml")
    assert resolved == v.resolve()


def test_resolve_expands_user_in_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    v = _make_vault(tmp_path / "vault")
    resolved = resolve_vault_path(
        None, env={"VAULT_PATH": "~/vault"}, config_path=tmp_path / "absent.toml"
    )
    assert resolved == v.resolve()


def test_config_with_no_vault_path_key_is_ignored(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.toml"
    cfg.write_text("# no vault_path key\nother = 1\n")
    with pytest.raises(VaultPathError, match="no vault path resolved"):
        resolve_vault_path(None, env={}, config_path=cfg)
