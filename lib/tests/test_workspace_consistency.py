"""Drift guards for cross-plugin pyproject consistency (L5).

The umbrella has no root pyproject hoisting shared config, so each plugin
copy-pastes its `requires-python` floor and `[tool.ruff.lint] select` set. These
tests lock the current consistency: if a sibling drifts (a different Python
floor, a different ruff rule set), CI fails here instead of the divergence
shipping silently.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Every package dir in the monorepo that ships a pyproject we want kept in sync.
_PACKAGE_DIRS = ("lib", "youtube", "spotify")

# The canonical baseline. Bumping these is a deliberate, all-plugins-at-once act.
_EXPECTED_REQUIRES_PYTHON = ">=3.12"
_EXPECTED_RUFF_SELECT = ["E", "F", "I", "B", "UP", "SIM"]


def _load_pyproject(package_dir: str) -> dict:
    path = _REPO_ROOT / package_dir / "pyproject.toml"
    assert path.is_file(), f"missing pyproject for {package_dir}: {path}"
    return tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("package_dir", _PACKAGE_DIRS)
def test_every_package_pins_requires_python(package_dir: str) -> None:
    data = _load_pyproject(package_dir)
    requires_python = data.get("project", {}).get("requires-python")
    assert requires_python == _EXPECTED_REQUIRES_PYTHON, (
        f"{package_dir}/pyproject.toml requires-python is {requires_python!r}; "
        f"expected {_EXPECTED_REQUIRES_PYTHON!r}. Keep the Python floor consistent "
        "across the workspace (bump all packages together)."
    )


@pytest.mark.parametrize("package_dir", _PACKAGE_DIRS)
def test_every_package_uses_the_same_ruff_select(package_dir: str) -> None:
    data = _load_pyproject(package_dir)
    select = data.get("tool", {}).get("ruff", {}).get("lint", {}).get("select")
    assert select == _EXPECTED_RUFF_SELECT, (
        f"{package_dir}/pyproject.toml [tool.ruff.lint] select is {select!r}; "
        f"expected {_EXPECTED_RUFF_SELECT!r}. Keep the lint rule set consistent "
        "across the workspace."
    )


@pytest.mark.parametrize("package_dir", _PACKAGE_DIRS)
def test_every_package_uses_the_same_ruff_target_version(package_dir: str) -> None:
    """target-version should track the requires-python floor (py312)."""
    data = _load_pyproject(package_dir)
    target = data.get("tool", {}).get("ruff", {}).get("target-version")
    assert target == "py312", (
        f"{package_dir}/pyproject.toml [tool.ruff] target-version is {target!r}; "
        "expected 'py312' to match the requires-python floor."
    )
