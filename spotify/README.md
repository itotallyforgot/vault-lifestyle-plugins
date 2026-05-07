# vault-spotify — Spotify listening-history ingester

Per-track ingester for Spotify recently-played history. Deposits
`raw/<slug>.md` files compatible with second-brain's `/vault ingest`
pipeline (same shape as the YouTube sibling).

> **MVP — Slice 1 of 5.** This README covers Slice 1 (one-time auth
> setup) only. `vault-spotify recent` ships in Slice 4 (OGR-75); the
> fetcher + writer modules ship in Slices 2 + 3.

## One-time setup (per user)

### 1. Register a Spotify Developer app

1. Go to <https://developer.spotify.com/dashboard>.
2. Create a new app. Any name works (e.g. `vault-spotify`).
3. Set the redirect URI to **exactly** `http://127.0.0.1:8888/callback`.
4. Note the **Client ID** from the app dashboard.

> **Why per-user?** We don't bundle a shared CLIENT_ID. Each user owns
> their own Spotify app, so the tool isn't a single point of failure for
> rate limits or app revocation. CLIENT_ID is public by OAuth design —
> not a secret — so any of the delivery options below is fine.

### 2. Provide CLIENT_ID to vault-spotify

Pick one delivery mechanism (resolution chain — first match wins):

```bash
# Option A: CLI flag (per-invocation)
vault-spotify auth --client-id <your-client-id>

# Option B: env var (recommended for shell users)
export SPOTIFY_CLIENT_ID=<your-client-id>
vault-spotify auth

# Option C: config file (set-once persistence; XDG-standard)
mkdir -p ~/.config/vault-lifestyle-plugins
echo 'client_id = "<your-client-id>"' > ~/.config/vault-lifestyle-plugins/spotify.toml
vault-spotify auth
```

### 3. One-time OAuth dance (per device)

```bash
vault-spotify auth
```

This opens your default browser to <https://accounts.spotify.com/authorize>,
asks you to grant the requested scopes
(`user-read-recently-played`, `user-read-playback-state`), and persists
tokens to one of (resolution chain):

1. `$VAULT_SPOTIFY_TOKEN_CACHE` (full path override)
2. `$XDG_DATA_HOME/vault-lifestyle-plugins/spotify-tokens.json`
3. `~/.local/share/vault-lifestyle-plugins/spotify-tokens.json` (default)

Tokens are NOT vault-synced — they're per-device. Each Mac / PC / Linux
box you use needs its own `vault-spotify auth` invocation.

## Status

| Slice | Module | Issue | Status |
|---|---|---|---|
| 1 | `auth` (CLIENT_ID resolution + OAuth dance) | OGR-72 | **this slice** |
| 2 | `client` + `models` (spotipy wrapper, PlayEvent type) | OGR-73 | next |
| 3 | `slug` + `writer` (raw/<slug>.md per play event) | OGR-74 | follows |
| 4 | `cli` + idempotency (`vault-spotify recent`) | OGR-75 | follows |
| 5 | CI lane + final polish | OGR-76 | follows |

## What's importable today

```python
from vault_spotify.auth import (
    MissingClientIdError,
    MissingTokensError,
    SpotifyAuthError,
    resolve_client_id,    # CLI flag → env → config file → fail
    run_auth_dance,       # one-time browser dance + token persist
    load_or_refresh_token,  # used by Slice 4's `recent` command
)
```

## What's NOT in this slice

- `vault-spotify recent` — Slice 4 (OGR-75). Currently prints a clean
  deferred-feature message and exits with code `7`.
- Spotipy client wrapper + Pydantic models — Slice 2 (OGR-73).
- Slug + writer — Slice 3 (OGR-74).
- CI lane — Slice 5 (OGR-76).
- Cron / bulk-import — post-MVP.

## Troubleshooting

- **"no Spotify CLIENT_ID resolved"** — see one-time setup §2 above.
- **Browser doesn't open during auth** — check `$BROWSER` env, run from
  a desktop session (not headless SSH), or invoke
  `vault-spotify auth --client-id <id>` after opening the URL spotipy
  prints manually.
- **"Spotify OAuth dance failed: ..."** — usually the redirect URI in
  your Spotify app config doesn't match `http://127.0.0.1:8888/callback`.
  Edit the app's redirect URIs in the dashboard, save, retry.
- **Tokens revoked / expired refresh** — re-run `vault-spotify auth`.
  The browser dance refreshes the cache.
