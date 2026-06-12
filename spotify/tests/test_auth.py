"""Tests for vault_spotify.auth — spotipy boundary mocked via sys.modules."""

from __future__ import annotations

import builtins
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vault_spotify.auth import (
    DEFAULT_REDIRECT_URI,
    DEFAULT_SCOPES,
    MissingClientIdError,
    MissingTokensError,
    SpotifyAuthError,
    _default_token_cache_path,
    _read_config_client_id,
    load_or_refresh_token,
    resolve_client_id,
    run_auth_dance,
)

# ============================================================
# resolve_client_id — chain precedence
# ============================================================


def test_resolve_arg_takes_precedence(tmp_path: Path) -> None:
    cfg = tmp_path / "spotify.toml"
    cfg.write_text('client_id = "from-config"\n')

    result = resolve_client_id("from-arg", env={"SPOTIFY_CLIENT_ID": "from-env"}, config_path=cfg)

    assert result == "from-arg"


def test_resolve_falls_back_to_env(tmp_path: Path) -> None:
    cfg = tmp_path / "spotify.toml"
    cfg.write_text('client_id = "from-config"\n')

    result = resolve_client_id(None, env={"SPOTIFY_CLIENT_ID": "from-env"}, config_path=cfg)

    assert result == "from-env"


def test_resolve_falls_back_to_config(tmp_path: Path) -> None:
    cfg = tmp_path / "spotify.toml"
    cfg.write_text('client_id = "from-config"\n')

    result = resolve_client_id(None, env={}, config_path=cfg)

    assert result == "from-config"


# ============================================================
# resolve_client_id — failure mode
# ============================================================


def test_resolve_raises_when_nothing_resolves(tmp_path: Path) -> None:
    with pytest.raises(MissingClientIdError) as exc_info:
        resolve_client_id(None, env={}, config_path=tmp_path / "absent.toml")

    assert exc_info.value.kind == "setup_required"
    # The error message should point users at setup instructions.
    assert "developer.spotify.com" in str(exc_info.value)
    assert DEFAULT_REDIRECT_URI in str(exc_info.value)


def test_resolve_strips_whitespace_in_arg() -> None:
    result = resolve_client_id("  spaced  ", env={}, config_path=Path("/nonexistent"))
    assert result == "spaced"


def test_resolve_strips_whitespace_in_env(tmp_path: Path) -> None:
    result = resolve_client_id(
        None,
        env={"SPOTIFY_CLIENT_ID": "  spaced  "},
        config_path=tmp_path / "absent.toml",
    )
    assert result == "spaced"


def test_resolve_treats_empty_arg_as_unset(tmp_path: Path) -> None:
    """Empty-string arg falls through to env, doesn't short-circuit."""
    result = resolve_client_id(
        "",
        env={"SPOTIFY_CLIENT_ID": "from-env"},
        config_path=tmp_path / "absent.toml",
    )
    assert result == "from-env"


def test_resolve_treats_whitespace_arg_as_unset(tmp_path: Path) -> None:
    """Whitespace-only arg falls through to env."""
    result = resolve_client_id(
        "   ",
        env={"SPOTIFY_CLIENT_ID": "from-env"},
        config_path=tmp_path / "absent.toml",
    )
    assert result == "from-env"


def test_resolve_ignores_config_without_client_id_key(tmp_path: Path) -> None:
    cfg = tmp_path / "spotify.toml"
    cfg.write_text("# empty config\nother_key = 1\n")

    with pytest.raises(MissingClientIdError):
        resolve_client_id(None, env={}, config_path=cfg)


def test_resolve_ignores_config_with_empty_client_id(tmp_path: Path) -> None:
    cfg = tmp_path / "spotify.toml"
    cfg.write_text('client_id = ""\n')

    with pytest.raises(MissingClientIdError):
        resolve_client_id(None, env={}, config_path=cfg)


def test_resolve_ignores_config_with_non_string_client_id(tmp_path: Path) -> None:
    """A `client_id = 12345` (TOML int) value falls through, doesn't crash."""
    cfg = tmp_path / "spotify.toml"
    cfg.write_text("client_id = 12345\n")

    with pytest.raises(MissingClientIdError):
        resolve_client_id(None, env={}, config_path=cfg)


# ============================================================
# _read_config_client_id (helper)
# ============================================================


def test_read_config_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert _read_config_client_id(tmp_path / "absent.toml") is None


def test_read_config_returns_value(tmp_path: Path) -> None:
    cfg = tmp_path / "spotify.toml"
    cfg.write_text('client_id = "abc123"\n')
    assert _read_config_client_id(cfg) == "abc123"


# ============================================================
# _default_token_cache_path — XDG resolution
# ============================================================


def test_default_token_cache_uses_explicit_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VAULT_SPOTIFY_TOKEN_CACHE", str(tmp_path / "explicit-tokens.json"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    result = _default_token_cache_path()

    assert result == tmp_path / "explicit-tokens.json"


def test_default_token_cache_uses_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("VAULT_SPOTIFY_TOKEN_CACHE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    result = _default_token_cache_path()

    assert result == tmp_path / "vault-lifestyle-plugins" / "spotify-tokens.json"


def test_default_token_cache_falls_back_to_home_local_share(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("VAULT_SPOTIFY_TOKEN_CACHE", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = _default_token_cache_path()

    assert (
        result == tmp_path / ".local" / "share" / "vault-lifestyle-plugins" / "spotify-tokens.json"
    )


def test_explicit_env_takes_precedence_over_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """VAULT_SPOTIFY_TOKEN_CACHE wins over XDG_DATA_HOME when both are set."""
    monkeypatch.setenv("VAULT_SPOTIFY_TOKEN_CACHE", str(tmp_path / "explicit.json"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    result = _default_token_cache_path()

    assert result == tmp_path / "explicit.json"


def test_default_token_cache_treats_empty_explicit_env_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty-string VAULT_SPOTIFY_TOKEN_CACHE falls through to XDG (it's
    "defined-but-blank", not a real path)."""
    monkeypatch.setenv("VAULT_SPOTIFY_TOKEN_CACHE", "")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    result = _default_token_cache_path()

    assert result == tmp_path / "vault-lifestyle-plugins" / "spotify-tokens.json"


def test_default_token_cache_treats_empty_xdg_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Empty-string XDG_DATA_HOME falls through to ~/.local/share."""
    monkeypatch.delenv("VAULT_SPOTIFY_TOKEN_CACHE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = _default_token_cache_path()

    assert (
        result == tmp_path / ".local" / "share" / "vault-lifestyle-plugins" / "spotify-tokens.json"
    )


# ============================================================
# run_auth_dance — spotipy boundary
# ============================================================


def _install_fake_spotipy(
    monkeypatch: pytest.MonkeyPatch,
    *,
    get_access_token_returns: str | None = "fake-token",
    get_access_token_raises: BaseException | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Inject a fake `spotipy.oauth2` module into sys.modules.

    Returns (module mock, SpotifyPKCE-instance mock).
    """
    fake_module = MagicMock()
    fake_pkce_instance = MagicMock()
    if get_access_token_raises is not None:
        fake_pkce_instance.get_access_token.side_effect = get_access_token_raises
    else:
        fake_pkce_instance.get_access_token.return_value = get_access_token_returns
    fake_module.SpotifyPKCE = MagicMock(return_value=fake_pkce_instance)
    monkeypatch.setitem(sys.modules, "spotipy.oauth2", fake_module)
    return fake_module, fake_pkce_instance


def test_run_auth_dance_passes_pkce_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module, _ = _install_fake_spotipy(monkeypatch)
    cache = tmp_path / "tokens.json"

    run_auth_dance(client_id="test-id", cache_path=cache)

    fake_module.SpotifyPKCE.assert_called_once()
    kwargs = fake_module.SpotifyPKCE.call_args.kwargs
    assert kwargs["client_id"] == "test-id"
    assert kwargs["redirect_uri"] == DEFAULT_REDIRECT_URI
    # Pin against DEFAULT_SCOPES so a future addition (e.g., a write scope
    # snuck into the constant) fails the test instead of silently shipping.
    assert kwargs["scope"] == " ".join(DEFAULT_SCOPES)
    assert kwargs["cache_path"] == str(cache)
    assert kwargs["open_browser"] is True


def test_default_scopes_are_read_only() -> None:
    """Lock the scope set: read-only access only. A future PR adding a write
    scope (`user-modify-playback-state`, `playlist-modify-private`, etc.)
    must update this test deliberately."""
    assert set(DEFAULT_SCOPES) == {
        "user-read-recently-played",
        "user-read-playback-state",
    }


def test_run_auth_dance_creates_cache_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_spotipy(monkeypatch)
    cache = tmp_path / "deep" / "nested" / "tokens.json"

    run_auth_dance(client_id="test-id", cache_path=cache)

    assert cache.parent.is_dir()


def test_run_auth_dance_restricts_token_cache_to_0600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for L4 / GHSA-pwhh-q4h6-w599: the refresh-token cache must
    not be world-readable. We defensively chmod 0600 even if the spotipy floor
    drifts below 2.25.1. Simulate spotipy writing a world-readable cache, then
    assert run_auth_dance tightened it."""
    cache = tmp_path / "tokens.json"

    def write_world_readable_cache() -> str:
        cache.write_text('{"refresh_token": "secret"}', encoding="utf-8")
        cache.chmod(0o644)  # what a pre-2.25.1 spotipy would leave behind
        return "fake-token"

    fake_module = MagicMock()
    fake_pkce = MagicMock()
    fake_pkce.get_access_token.side_effect = write_world_readable_cache
    fake_module.SpotifyPKCE = MagicMock(return_value=fake_pkce)
    monkeypatch.setitem(sys.modules, "spotipy.oauth2", fake_module)

    run_auth_dance(client_id="test-id", cache_path=cache)

    mode = stat.S_IMODE(cache.stat().st_mode)
    assert mode == 0o600, f"token cache perms are {oct(mode)}, expected 0o600"
    # Explicitly: no group/other access bits.
    assert not mode & (stat.S_IRWXG | stat.S_IRWXO)


def test_run_auth_dance_chmod_is_best_effort_when_cache_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing cache file (spotipy wrote nothing) must not crash auth — the
    defensive chmod swallows OSError and logs instead."""
    _install_fake_spotipy(monkeypatch)  # get_access_token writes no file
    cache = tmp_path / "tokens.json"

    # Should not raise even though `cache` never gets created.
    run_auth_dance(client_id="test-id", cache_path=cache)

    assert not cache.exists()


def test_run_auth_dance_calls_get_access_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, fake_pkce = _install_fake_spotipy(monkeypatch)

    run_auth_dance(client_id="test-id", cache_path=tmp_path / "tokens.json")

    # SpotifyPKCE.get_access_token() takes no kwargs we pass; called bare.
    # If a future refactor passes `as_dict=` (an SpotifyOAuth-only kwarg),
    # the autospec regression test below catches it on real spotipy.
    fake_pkce.get_access_token.assert_called_once_with()


def test_run_auth_dance_kwargs_match_real_spotipy_pkce_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for P0 caught in ISSUE-N review: `as_dict=False` is a
    SpotifyOAuth kwarg, not SpotifyPKCE's. MagicMock-based tests passed
    because MagicMock accepts any kwargs. `create_autospec` against the
    real `SpotifyPKCE` enforces the actual signature — passing a wrong
    kwarg here raises TypeError and fails the test."""
    from unittest.mock import create_autospec

    from spotipy.oauth2 import SpotifyPKCE as RealSpotifyPKCE

    fake_module = MagicMock()
    autospec_class = create_autospec(RealSpotifyPKCE)
    autospec_class.return_value.get_access_token.return_value = "fake-token"
    fake_module.SpotifyPKCE = autospec_class
    monkeypatch.setitem(sys.modules, "spotipy.oauth2", fake_module)

    # If our code drifts to passing an unsupported kwarg to PKCE's methods,
    # autospec raises here.
    run_auth_dance(client_id="test-id", cache_path=tmp_path / "tokens.json")

    autospec_class.return_value.get_access_token.assert_called_once()


def test_run_auth_dance_open_browser_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Headless mode: open_browser=False should reach the SpotifyPKCE constructor."""
    fake_module, _ = _install_fake_spotipy(monkeypatch)

    run_auth_dance(client_id="test-id", cache_path=tmp_path / "tokens.json", open_browser=False)

    assert fake_module.SpotifyPKCE.call_args.kwargs["open_browser"] is False


def test_run_auth_dance_wraps_spotipy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_spotipy(monkeypatch, get_access_token_raises=RuntimeError("user denied"))

    with pytest.raises(SpotifyAuthError, match="OAuth dance failed"):
        run_auth_dance(client_id="test-id", cache_path=tmp_path / "tokens.json")


def _patch_spotipy_import_error(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Force `import spotipy.oauth2` to raise `exc`."""
    monkeypatch.delitem(sys.modules, "spotipy.oauth2", raising=False)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "spotipy.oauth2" or name == "spotipy":
            raise exc
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_run_auth_dance_raises_when_spotipy_unavailable_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ImportError path: spotipy not installed."""
    _patch_spotipy_import_error(monkeypatch, ImportError("No module named spotipy.oauth2"))

    with pytest.raises(SpotifyAuthError, match="spotipy unavailable"):
        run_auth_dance(client_id="test-id", cache_path=tmp_path / "tokens.json")


def test_run_auth_dance_raises_when_spotipy_unavailable_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError path: native deps missing (parity with whisper_fallback)."""
    _patch_spotipy_import_error(monkeypatch, OSError("dlopen failed: libsomething"))

    with pytest.raises(SpotifyAuthError, match="spotipy unavailable"):
        run_auth_dance(client_id="test-id", cache_path=tmp_path / "tokens.json")


def test_run_auth_dance_wraps_unwritable_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the token-cache parent directory can't be created, surface a
    clean SpotifyAuthError instead of letting OSError propagate raw."""
    _install_fake_spotipy(monkeypatch)

    # Simulate mkdir failing (e.g., parent path is a regular file, not a dir).
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"i am a file, not a directory")
    cache = blocker / "subdir" / "tokens.json"  # mkdir(parents=True) on this fails

    with pytest.raises(SpotifyAuthError, match="can't create token cache"):
        run_auth_dance(client_id="test-id", cache_path=cache)


# ============================================================
# load_or_refresh_token
# ============================================================


def test_load_raises_missing_when_no_cache(tmp_path: Path) -> None:
    with pytest.raises(MissingTokensError) as exc_info:
        load_or_refresh_token(client_id="test-id", cache_path=tmp_path / "absent.json")

    assert exc_info.value.kind == "missing"
    assert "vault-spotify auth" in str(exc_info.value)


def test_load_returns_access_token_when_cache_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "tokens.json"
    cache.write_text('{"access_token": "fake"}')
    _install_fake_spotipy(monkeypatch, get_access_token_returns="fresh-access-token")

    result = load_or_refresh_token(client_id="test-id", cache_path=cache)

    assert result == "fresh-access-token"


def test_load_raises_refresh_failed_when_spotipy_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "tokens.json"
    cache.write_text('{"access_token": "fake"}')
    _install_fake_spotipy(monkeypatch, get_access_token_raises=RuntimeError("revoked"))

    with pytest.raises(MissingTokensError) as exc_info:
        load_or_refresh_token(client_id="test-id", cache_path=cache)

    assert exc_info.value.kind == "refresh_failed"
    assert "vault-spotify auth" in str(exc_info.value)


def test_load_raises_refresh_failed_when_token_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "tokens.json"
    cache.write_text('{"access_token": "fake"}')
    _install_fake_spotipy(monkeypatch, get_access_token_returns="")

    with pytest.raises(MissingTokensError) as exc_info:
        load_or_refresh_token(client_id="test-id", cache_path=cache)

    assert exc_info.value.kind == "refresh_failed"


def test_load_raises_refresh_failed_when_token_not_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spotipy may return None or a dict if `as_dict=False` isn't honored;
    treat any non-str result as a refresh failure rather than crashing."""
    cache = tmp_path / "tokens.json"
    cache.write_text('{"access_token": "fake"}')
    _install_fake_spotipy(monkeypatch, get_access_token_returns=None)

    with pytest.raises(MissingTokensError) as exc_info:
        load_or_refresh_token(client_id="test-id", cache_path=cache)

    assert exc_info.value.kind == "refresh_failed"


def test_load_raises_when_spotipy_unavailable_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "tokens.json"
    cache.write_text('{"access_token": "fake"}')
    _patch_spotipy_import_error(monkeypatch, ImportError("No module named spotipy.oauth2"))

    with pytest.raises(SpotifyAuthError, match="spotipy unavailable"):
        load_or_refresh_token(client_id="test-id", cache_path=cache)


def test_load_raises_when_spotipy_unavailable_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "tokens.json"
    cache.write_text('{"access_token": "fake"}')
    _patch_spotipy_import_error(monkeypatch, OSError("dlopen failed: libsomething"))

    with pytest.raises(SpotifyAuthError, match="spotipy unavailable"):
        load_or_refresh_token(client_id="test-id", cache_path=cache)


def test_load_raises_malformed_cache_when_read_text_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spotipy refresh raised AND read_text() raises (binary garbage in cache)
    → classify as malformed_cache, not refresh_failed."""
    cache = tmp_path / "tokens.json"
    cache.write_bytes(b"\x80\xff\xfe\xfd")  # invalid UTF-8
    _install_fake_spotipy(monkeypatch, get_access_token_raises=RuntimeError("refresh fail"))

    with pytest.raises(MissingTokensError) as exc_info:
        load_or_refresh_token(client_id="test-id", cache_path=cache)

    assert exc_info.value.kind == "malformed_cache"
    assert "unreadable" in str(exc_info.value)


# ============================================================
# Exception class semantics
# ============================================================


def test_all_auth_errors_inherit_from_base() -> None:
    """CLI catches `SpotifyAuthError` once and routes via subclass / kind."""
    assert issubclass(MissingClientIdError, SpotifyAuthError)
    assert issubclass(MissingTokensError, SpotifyAuthError)
    assert issubclass(SpotifyAuthError, RuntimeError)


def test_missing_client_id_error_carries_kind() -> None:
    err = MissingClientIdError("boom")
    assert err.kind == "setup_required"
    assert isinstance(err, SpotifyAuthError)


def test_missing_tokens_error_carries_kind() -> None:
    err = MissingTokensError("missing", "boom")
    assert err.kind == "missing"
    assert isinstance(err, SpotifyAuthError)
