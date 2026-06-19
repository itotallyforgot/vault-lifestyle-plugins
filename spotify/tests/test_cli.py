"""Tests for vault_spotify.cli."""

from __future__ import annotations

from typer.testing import CliRunner

from vault_spotify.cli import app


def test_recent_exits_cleanly_while_deferred() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["recent"])

    assert result.exit_code == 7
    assert "vault-spotify recent is not available yet" in result.output
    assert "Slice 4" in result.output
    assert "NotImplementedError" not in result.output
    assert "Traceback" not in result.output
