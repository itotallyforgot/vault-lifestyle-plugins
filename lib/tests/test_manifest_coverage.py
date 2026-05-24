"""Staleness check for ``docs/attack-surface-manifest.md``.

Asserts that every console script declared in any ``pyproject.toml``
``[project.scripts]`` table in the monorepo appears as a heading in the
attack-surface manifest. This is the automated floor — internal Typer
subcommands and importable APIs still rely on the human auditor following
``docs/auditing-a-new-tool.md``.

Lives under ``lib/tests/`` because ``lib`` is the shared package whose
pytest job in CI is the canonical home for cross-plugin checks. The test
walks the repo root regardless of where pytest is invoked from.

Fails with a directive message naming the missing scripts so a contributor
who adds a new ``[project.scripts]`` entry without a manifest section sees
exactly what to add.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs" / "attack-surface-manifest.md"


def _discover_console_scripts() -> dict[str, Path]:
    """Walk pyproject.toml files in the monorepo and return script names.

    Returns a mapping of console-script name -> pyproject path so the
    failure message can point the contributor at the right manifest.
    """
    scripts: dict[str, Path] = {}
    for pyproject in REPO_ROOT.glob("*/pyproject.toml"):
        if any(part in {".venv", "node_modules"} for part in pyproject.parts):
            continue
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        table = (data.get("project") or {}).get("scripts") or {}
        for name in table:
            scripts[name] = pyproject
    return scripts


def _manifest_headings() -> list[str]:
    """Return all markdown headings in the manifest (any depth)."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    return [match.group("title").strip() for match in _HEADING_RE.finditer(text)]


_HEADING_RE = re.compile(r"^(?P<hashes>#+)\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _heading_mentions_script(heading: str, script: str) -> bool:
    """A heading mentions a script if the script name appears as a
    whitespace-bounded token in the heading. This avoids matching
    `vault-yt` as a substring of `vault-ytX` while still matching
    `vault-yt batch ingest` and `vault-yt --export-playlist`.
    """
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(script)}(?![A-Za-z0-9_])", heading))


def test_manifest_exists() -> None:
    assert MANIFEST_PATH.is_file(), (
        f"attack-surface manifest missing at {MANIFEST_PATH}. "
        "See docs/auditing-a-new-tool.md for the contract."
    )


def test_every_console_script_has_a_manifest_section() -> None:
    """Each ``[project.scripts]`` entry must appear as a heading in the manifest."""
    scripts = _discover_console_scripts()
    assert scripts, (
        "no console scripts discovered under the repo root; the staleness "
        "check is meaningless. Did the test get moved out of lib/tests/ "
        "without updating REPO_ROOT?"
    )

    headings = _manifest_headings()
    missing: list[tuple[str, Path]] = []
    for script_name, pyproject in scripts.items():
        if not any(_heading_mentions_script(h, script_name) for h in headings):
            missing.append((script_name, pyproject))

    if missing:
        lines = [
            "attack-surface manifest is stale — these console scripts have no section in",
            f"  {MANIFEST_PATH.relative_to(REPO_ROOT)}:",
            "",
        ]
        for script_name, pyproject in missing:
            lines.append(f"  - {script_name!r} declared in {pyproject.relative_to(REPO_ROOT)}")
        lines.append("")
        lines.append(
            "Add a manifest section per docs/auditing-a-new-tool.md, then re-run this test."
        )
        raise AssertionError("\n".join(lines))
