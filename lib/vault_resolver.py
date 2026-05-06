"""Resolve a vault path: --arg → $VAULT_PATH → user config file.

Used by every ingest-direction integration to find a target vault on disk.
A "vault" here is a second-brain-shaped directory: it has `raw/` and either
`wiki/` or `_templates/` (the latter exists in fresh public-template clones
that haven't yet populated `wiki/`).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "vault-lifestyle-plugins" / "config.toml"


class VaultPathError(ValueError):
    """Raised when a vault path can't be resolved or doesn't look like a vault."""


def _looks_like_vault(p: Path) -> bool:
    """A path looks like a vault if it has `raw/` plus `wiki/` or `_templates/`."""
    if not (p / "raw").is_dir():
        return False
    return (p / "wiki").is_dir() or (p / "_templates").is_dir()


def _read_config_path(config_path: Path) -> Path | None:
    """Read `vault_path` from the umbrella config file. None if absent."""
    if not config_path.is_file():
        return None
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    raw = data.get("vault_path")
    if raw is None:
        return None
    return Path(raw).expanduser()


def resolve_vault_path(
    arg: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Path:
    """Resolve a vault path in priority order: arg → $VAULT_PATH → config file.

    Validates that the resolved path looks like a vault (has `raw/` plus
    `wiki/` or `_templates/`).

    Args:
        arg: explicit path from a `--vault` CLI flag, if provided.
        env: environment dict (for testing); defaults to os.environ.
        config_path: config file path (for testing); defaults to
            ~/.config/vault-lifestyle-plugins/config.toml.

    Raises:
        VaultPathError: if no path is found, the path doesn't exist, or the
            path doesn't look like a vault.
    """
    if env is None:
        env = os.environ

    candidates: list[tuple[str, Path | None]] = [
        (
            "--vault arg",
            Path(arg).expanduser() if arg is not None else None,
        ),
        (
            "$VAULT_PATH env",
            Path(env["VAULT_PATH"]).expanduser() if env.get("VAULT_PATH") else None,
        ),
        (
            f"config file ({config_path})",
            _read_config_path(config_path),
        ),
    ]

    for source, path in candidates:
        if path is None:
            continue
        if not path.exists():
            raise VaultPathError(f"vault path from {source} does not exist: {path}")
        if not path.is_dir():
            raise VaultPathError(f"vault path from {source} is not a directory: {path}")
        resolved = path.resolve()
        if not _looks_like_vault(resolved):
            raise VaultPathError(
                f"path from {source} does not look like a vault "
                f"(missing `raw/` plus `wiki/` or `_templates/`): {resolved}"
            )
        return resolved

    raise VaultPathError(
        "no vault path resolved — pass --vault, set $VAULT_PATH, or add "
        f'`vault_path = "..."` to {config_path}'
    )
