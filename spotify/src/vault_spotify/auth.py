"""OAuth + token persistence for vault-spotify.

PKCE-only flow (no client secret). CLIENT_ID resolution chain:

    1. arg passed to caller (e.g. `--client-id` CLI flag)
    2. `$SPOTIFY_CLIENT_ID` env
    3. `~/.config/vault-lifestyle-plugins/spotify.toml` (`client_id = "..."`)
    4. fail with `MissingClientIdError(kind="setup_required")`

Tokens persist to a user-state location (XDG_DATA_HOME-aware):

    1. `$VAULT_SPOTIFY_TOKEN_CACHE` (full path override)
    2. `$XDG_DATA_HOME/vault-lifestyle-plugins/spotify-tokens.json`
    3. `~/.local/share/vault-lifestyle-plugins/spotify-tokens.json` (XDG default)

This is intentionally outside the plugin source tree so installed copies
(via `pip install`) write to a stable user-state location, not into
site-packages. The umbrella's `.gitignore` `.tokens/` rule still keeps
dev-clone tokens out of git when callers point the cache there.

Lazy-imports spotipy so this module loads even when spotipy is missing
(parallels `whisper_fallback`'s import discipline). The CLI's `auth`
subcommand surfaces a clear error if spotipy isn't installed.

Failure modes use a `kind`-discriminator pattern matching the umbrella's
established `ExtractorError` / `WhisperFallbackError` style — Slice 4's
CLI maps cleanly to spec exit codes.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

DEFAULT_CONFIG_PATH = (
    Path.home() / ".config" / "vault-lifestyle-plugins" / "spotify.toml"
)
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_SCOPES: tuple[str, ...] = (
    "user-read-recently-played",
    "user-read-playback-state",
)


# ---- Token cache resolution -----------------------------------------------


def _default_token_cache_path() -> Path:
    """Resolve the default token-cache path via the XDG-aware chain.

    Order:
        1. `$VAULT_SPOTIFY_TOKEN_CACHE` (full path override)
        2. `$XDG_DATA_HOME/vault-lifestyle-plugins/spotify-tokens.json`
        3. `~/.local/share/vault-lifestyle-plugins/spotify-tokens.json`
    """
    explicit = os.environ.get("VAULT_SPOTIFY_TOKEN_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    xdg_data = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data).expanduser() if xdg_data else Path.home() / ".local" / "share"
    return base / "vault-lifestyle-plugins" / "spotify-tokens.json"


# ---- Error classes --------------------------------------------------------


ClientIdErrorKind = Literal["setup_required"]
TokenErrorKind = Literal["missing", "refresh_failed", "malformed_cache"]


class SpotifyAuthError(RuntimeError):
    """Base for all auth-side failures."""


class MissingClientIdError(SpotifyAuthError):
    """No CLIENT_ID resolved through the chain.

    Carries the spec exit-code-mappable `kind="setup_required"`. The
    message includes a copy-pasteable setup snippet for the README's
    one-time-setup walkthrough.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.kind: ClientIdErrorKind = "setup_required"


class MissingTokensError(SpotifyAuthError):
    """Tokens are absent, can't be refreshed, or are corrupted.

    `kind` distinguishes the recovery action:
    - `missing`: run `vault-spotify auth` (initial setup).
    - `refresh_failed`: re-auth (refresh token revoked or expired).
    - `malformed_cache`: cache file unreadable; re-auth or delete cache.
    """

    def __init__(self, kind: TokenErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: TokenErrorKind = kind


# ---- CLIENT_ID resolution -------------------------------------------------


def _read_config_client_id(config_path: Path) -> str | None:
    """Read `client_id` from a TOML config file. Returns None if absent/empty."""
    if not config_path.is_file():
        return None
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    raw = data.get("client_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def resolve_client_id(
    arg: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> str:
    """Resolve a Spotify CLIENT_ID via the documented chain.

    Args:
        arg: explicit value from a `--client-id` CLI flag, if provided.
        env: environment dict (for testing); defaults to `os.environ`.
        config_path: config file path (for testing); defaults to
            `~/.config/vault-lifestyle-plugins/spotify.toml`.

    Returns the resolved CLIENT_ID (whitespace-stripped).

    Raises:
        MissingClientIdError: nothing in the chain resolved. The message
            includes setup instructions paired with the README walkthrough.
    """
    if env is None:
        env = os.environ

    if arg and arg.strip():
        return arg.strip()

    env_id = env.get("SPOTIFY_CLIENT_ID")
    if env_id and env_id.strip():
        return env_id.strip()

    cfg_id = _read_config_client_id(config_path)
    if cfg_id:
        return cfg_id

    raise MissingClientIdError(
        "no Spotify CLIENT_ID resolved. Provide one of:\n"
        "  --client-id <id>                                       (CLI flag)\n"
        "  export SPOTIFY_CLIENT_ID=<id>                          (env var)\n"
        f"  echo 'client_id = \"<id>\"' > {config_path}            (config file)\n"
        "\n"
        "Register a Spotify Developer app at\n"
        "  https://developer.spotify.com/dashboard\n"
        f"and set its redirect URI to {DEFAULT_REDIRECT_URI}."
    )


# ---- Auth dance + token persistence ---------------------------------------


def run_auth_dance(
    *,
    client_id: str,
    cache_path: Path | None = None,
    open_browser: bool = True,
) -> None:
    """Perform the OAuth-with-PKCE browser dance and persist tokens.

    Args:
        client_id: resolved Spotify CLIENT_ID (caller validates upstream).
        cache_path: where tokens persist. Defaults to `_default_token_cache_path()`.
        open_browser: whether spotipy should auto-open the browser. False for
            headless / test scenarios.

    Raises:
        SpotifyAuthError: spotipy isn't installed OR raised during the auth flow.
    """
    cache_path = cache_path or _default_token_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SpotifyAuthError(
            f"can't create token cache directory at {cache_path.parent}: {e}"
        ) from e

    # Catch (ImportError, OSError) — parity with whisper_fallback's lazy
    # import. spotipy is pure Python today, but the broader catch covers a
    # future C-extension dep + matches the umbrella's established discipline.
    try:
        from spotipy.oauth2 import SpotifyPKCE  # type: ignore[import-untyped]
    except (ImportError, OSError) as e:
        raise SpotifyAuthError(
            f"spotipy unavailable: {e}. Run `uv sync` from the spotify/ subdir."
        ) from e

    pkce = SpotifyPKCE(
        client_id=client_id,
        redirect_uri=DEFAULT_REDIRECT_URI,
        scope=" ".join(DEFAULT_SCOPES),
        cache_path=str(cache_path),
        open_browser=open_browser,
    )

    # `get_access_token` blocks until the user completes the browser flow
    # (spotipy spins up a localhost server on the redirect URI's port).
    # SpotifyPKCE.get_access_token() returns the access-token string
    # directly — no `as_dict` parameter (that's SpotifyOAuth's API, not PKCE's).
    try:
        pkce.get_access_token()
    except Exception as e:
        raise SpotifyAuthError(f"Spotify OAuth dance failed: {e}") from e


def load_or_refresh_token(
    *,
    client_id: str,
    cache_path: Path | None = None,
) -> str:
    """Read cached tokens; refresh access token if needed; return access token.

    Args:
        client_id: resolved Spotify CLIENT_ID (must match the one used during
            the original auth dance — refresh tokens are bound to the app).
        cache_path: token-cache location. Defaults to `_default_token_cache_path()`.

    Returns the current valid access token.

    Raises:
        MissingTokensError(kind="missing"): no cache file at `cache_path`.
        MissingTokensError(kind="refresh_failed"): refresh attempt failed
            (token revoked, network issue, or app deleted from dashboard).
        MissingTokensError(kind="malformed_cache"): cache file unreadable.
        SpotifyAuthError: spotipy isn't installed.
    """
    cache_path = cache_path or _default_token_cache_path()

    if not cache_path.is_file():
        raise MissingTokensError(
            "missing",
            f"no Spotify tokens at {cache_path}. "
            "Run `vault-spotify auth` to perform the one-time browser dance.",
        )

    try:
        from spotipy.oauth2 import SpotifyPKCE  # type: ignore[import-untyped]
    except (ImportError, OSError) as e:
        raise SpotifyAuthError(
            f"spotipy unavailable: {e}. Run `uv sync` from the spotify/ subdir."
        ) from e

    pkce = SpotifyPKCE(
        client_id=client_id,
        redirect_uri=DEFAULT_REDIRECT_URI,
        scope=" ".join(DEFAULT_SCOPES),
        cache_path=str(cache_path),
        open_browser=False,
    )

    # SpotifyPKCE.get_access_token() returns the access-token string
    # directly — no `as_dict` parameter (that's SpotifyOAuth's API, not PKCE's).
    try:
        token = pkce.get_access_token()
    except Exception as e:
        # Distinguish refresh failure from a corrupt cache. If the file
        # can be read, the failure is upstream (spotipy refresh path);
        # if not, the cache itself is the problem.
        try:
            cache_path.read_text()
            raise MissingTokensError(
                "refresh_failed",
                f"refresh failed: {e}. Run `vault-spotify auth` to re-auth.",
            ) from e
        except (OSError, UnicodeDecodeError):
            raise MissingTokensError(
                "malformed_cache",
                f"cache unreadable at {cache_path}: {e}",
            ) from e

    if not isinstance(token, str) or not token:
        raise MissingTokensError(
            "refresh_failed",
            "spotipy returned an empty / invalid access token; "
            "re-run `vault-spotify auth`.",
        )

    return token
