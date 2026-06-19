"""vault-spotify CLI entrypoint (Typer).

Slice 1 ships the `auth` subcommand only. `recent` exits cleanly as a
deferred feature until Slice 4 fills it in.
"""

from __future__ import annotations

import typer

from vault_spotify.auth import (
    MissingClientIdError,
    SpotifyAuthError,
    resolve_client_id,
    run_auth_dance,
)

app = typer.Typer(
    name="vault-spotify",
    help="Spotify listening-history ingester for second-brain vaults.",
    no_args_is_help=True,
)


@app.command()
def auth(
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="Spotify CLIENT_ID. Overrides $SPOTIFY_CLIENT_ID and the config file.",
    ),
) -> None:
    """One-time OAuth browser dance; persist tokens for recurring use.

    Resolves CLIENT_ID from `--client-id` → `$SPOTIFY_CLIENT_ID` →
    `~/.config/vault-lifestyle-plugins/spotify.toml`, then opens the
    default browser to https://accounts.spotify.com/authorize for the
    PKCE flow. Tokens persist to the XDG-data-home location (or
    `$VAULT_SPOTIFY_TOKEN_CACHE` override).

    Exit codes:
        0: success.
        6: CLIENT_ID setup needed OR OAuth flow failed.
    """
    try:
        cid = resolve_client_id(client_id)
    except MissingClientIdError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=6) from e

    typer.echo(
        f"Starting Spotify OAuth dance (CLIENT_ID={cid[:8]}...). A browser window will open."
    )
    try:
        run_auth_dance(client_id=cid)
    except SpotifyAuthError as e:
        typer.echo(f"OAuth dance failed: {e}", err=True)
        raise typer.Exit(code=6) from e

    typer.echo("Tokens persisted. `vault-spotify recent` becomes available in Slice 4.")


@app.command()
def recent(
    vault: str | None = typer.Option(None, "--vault", help="Vault path."),
    limit: int = typer.Option(50, "--limit", help="Max tracks (Spotify caps at 50)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing per-event files."),
    verbose: bool = typer.Option(False, "--verbose", help="Per-step logging."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing."),
) -> None:
    """Deferred: fetch recently-played tracks in Slice 4.

    Exit codes:
        7: command is intentionally unavailable until Slice 4.

    IMPLEMENTER NOTE (see docs/adr/0005-bulk-enumerators-count-verified-fail-
    closed.md): when this is built it becomes a bulk enumerator
    and is bound by ADR-0005. The Spotify recently-played endpoint
    (/me/player/recently-played) is cursor-paginated (`next`/`cursors.before`,
    max 50 per page) and reports NO `total`, so completeness cannot be checked
    against a count the way the YouTube exporter checks `playlist_count`. The
    fail-closed contract still applies: follow `next` until it is absent, treat
    any HTTP/auth error mid-walk as an incomplete enumeration that raises
    (never an empty-as-success), and record `complete` in the run manifest. The
    `--limit 50` default above is a per-request page size, NOT a stop condition;
    do not let it cap the walk (that is exactly the self-truncation ADR-0005
    forbids). A playlist-style endpoint with a `total` would assert
    `fetched == total` instead.
    """
    typer.echo(
        "vault-spotify recent is not available yet; it ships in Slice 4. "
        "Slice 1 only includes `vault-spotify auth`.",
        err=True,
    )
    raise typer.Exit(code=7)


def main() -> None:
    """Console-script entrypoint registered in pyproject.toml."""
    app()


if __name__ == "__main__":
    main()
