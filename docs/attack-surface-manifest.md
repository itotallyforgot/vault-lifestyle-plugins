# Attack-surface manifest

Per-tool security manifest for every entry point in this monorepo. Inspired by
the [MCP-ASD](https://github.com/hoodoer/MCP-ASD) model: each tool/action lists
inputs, auth assumptions, side effects, filesystem and network access, trust
boundaries, lethal-trifecta exposure, a safe test payload, and at least one
misuse/abuse case.

This is a durable artifact. New tools MUST be added here before merge — see
[`auditing-a-new-tool.md`](./auditing-a-new-tool.md) for the audit checklist
and the staleness gate that fails CI when a new entry point ships without a
manifest section.

## Scope

What counts as a "tool" for this manifest:

- A CLI entry point declared in a `pyproject.toml` `[project.scripts]` table.
- A Typer subcommand on a registered CLI app (`@app.command(...)`).
- An importable function exposed to other code that performs I/O, side
  effects, or trust-boundary work (network call, vault write, credential
  read, OAuth dance, subprocess fork, etc.).
- An HTTP route or MCP-server tool, if/when this repo ever exposes one.
  (Today: none.)

What is intentionally OUT of scope:

- Pure functions with no I/O (`youtube/src/vault_yt/slug.py:make`,
  `youtube/src/vault_yt/resolver.py:choose_transcript_source`,
  `lib/frontmatter_schema.py:validate_frontmatter` as data-validation only).
  These get audited when they grow side effects.
- Test code under `*/tests/`.

## Cross-cutting trust model

- The vault on disk is **trusted output** (we write to it). Inputs that reach
  it (transcripts, frontmatter values, slugs) cross a trust boundary.
- Caller-supplied URLs are **untrusted input** — anyone on the user's
  machine that can launch `vault-yt` can point it at anything.
- yt-dlp performs the actual network egress for all YouTube paths. We
  inherit yt-dlp's transport defaults and trust its parsers (see misuse
  cases). yt-dlp is upper-pinned (`<2027.0.0`) to bound supply-chain blast
  radius. See `[[ai-model-supply-chain-risk]]`.
- Whisper runs locally only. No outbound model inference calls.
- Spotify OAuth uses PKCE — no client secret in this codebase.
- Browser cookies, refresh tokens, and OAuth access tokens are
  **account secrets**. They live outside the repo and outside the vault.
  See `[[non-human-identity-management]]`.
- Lethal trifecta ([[lethal-trifecta]]): a tool composes the trifecta when
  one call touches **private data**, **untrusted input**, and an
  **uncontrolled exfil vector** in the same trust scope. Tools that compose
  fewer than three legs are not lethal-trifecta-exposed even if individually
  sensitive. See `[[agentic-attack-surface]]` for broader framing.

## Risk legend

- **P0** — direct credential / private-data exfil path, or vault-write with
  untrusted content under attacker-controlled location.
- **P1** — credential/private-data handling, or filesystem write outside
  user-confirmed paths.
- **P2** — outbound network egress driven by untrusted input.
- **P3** — parse-only / read-only / no auth.

---

## vault-yt (plugin: youtube)

Console script registered in `youtube/pyproject.toml` as
`vault-yt = "vault_yt.cli:main"`. Single Typer app with multiple flag-routed
modes. Each mode is treated as its own tool below — the flag table in
`youtube/src/vault_yt/cli.py:command` routes to the corresponding internal
handler.

### vault-yt single-URL ingest (plugin: youtube)

| Field | Value |
|---|---|
| Entry point | `youtube/src/vault_yt/cli.py:command` → `_ingest_url` (default mode when positional `URL` is set). |
| Direction | ingest |
| Inputs | `url: str` (untrusted; user-supplied); `--vault PATH` or `$VAULT_PATH` or config TOML (semi-trusted local config); `--whisper-model {tiny,base,small}`; `--transcript-language str`; `--force`, `--force-whisper`, `--dry-run`, `--verbose` flags. |
| Auth assumptions | None. Public-API path: yt-dlp uses no caller credentials. |
| Side effects | Writes `<vault>/raw/<slug>.md` (atomic via `lib/raw_writer.py:write_raw_file`); creates parent dirs of the raw path; creates a temp directory under `tempfile.gettempdir()` and downloads audio there if Whisper fallback fires; the temp dir is removed on exit. |
| Filesystem access | Reads: config TOML at `~/.config/vault-lifestyle-plugins/config.toml`; the vault root for path-shape checks; existing raw page if a slug collision is detected. Writes: `<vault>/raw/<slug>.md`. Temp: a per-run `tempfile.TemporaryDirectory()` for Whisper audio. The Whisper model cache lives under `~/.cache/whisper/` (managed by openai-whisper). |
| Network access | yt-dlp egress to YouTube (`*.youtube.com`, `*.googlevideo.com`, etc.) for metadata, VTT captions, and (when Whisper is used) audio. One automatic retry on `ExtractorError(kind="network")` with a 5s sleep (`cli.py:_with_network_retry`). yt-dlp enforces a 500 MiB audio cap (`MAX_AUDIO_FILESIZE_BYTES`) and an 8-hour duration cap (`MAX_VIDEO_DURATION_SECONDS`) in `extractor.py`. |
| Trust boundary | The user-supplied `url` is untrusted text. `urlparse` rejects non-http(s) schemes (`_looks_like_url`) before yt-dlp sees it. yt-dlp itself parses the URL further; the host check in `inputs._parse_youtube_input` is only enforced on the batch path, not on this single-URL path. The VTT body and metadata title flow into the slug (`slug.make`, which strips to `[a-z0-9-]`) and into the frontmatter (Pydantic-validated). Transcript text flows verbatim into the body of the raw markdown. |
| Lethal-trifecta exposure | **No.** Untrusted-input leg: yes (user URL + remote transcript). Private-data leg: no (no user credentials are read in this mode). Exfil leg: no outbound write — only local disk under `<vault>/raw/`. Two-of-three is not the trifecta; documented for completeness. |
| Safe test payload | `uv --directory youtube run vault-yt "https://youtu.be/dQw4w9WgXcQ" --vault /tmp/test-vault --dry-run` (any public, short, non-livestream video URL; `--dry-run` skips the disk write). |
| Misuse / abuse cases | — Malicious title in YouTube metadata → slug injection: mitigated by `slug._sanitize_title` collapsing everything outside `[a-z0-9-]`. **P3.**<br>— Malicious title → frontmatter YAML injection (e.g. `title: foo\n---\nevil: true`): yaml.safe_dump escapes embedded specials; Pydantic re-validates after parse. **P3.**<br>— Malicious transcript body → markdown/link injection into the vault page: transcripts flow verbatim into the body. Downstream `/vault ingest` is the trust gate for anything content-driven that reaches `wiki/`. **P2.**<br>— Hostile yt-dlp extractor (zero-day in a YouTube extractor or compromised yt-dlp release): yt-dlp is upper-pinned but a supply-chain compromise would bypass the pin if a malicious release lands under the upper bound. See `[[ai-model-supply-chain-risk]]`. **P1.**<br>— Path-traversal via vault arg pointing at a parent dir containing an attacker-controlled `raw/`: `vault_resolver.resolve_vault_path` requires the dir to look like a vault (has `raw/` + `wiki/` or `_templates/`) but does not chroot. **P2** if the user's shell is compromised. |

### vault-yt batch ingest (plugin: youtube)

| Field | Value |
|---|---|
| Entry point | `youtube/src/vault_yt/cli.py:command` → `_run_batch` (triggered by `--url-file` or `--playlist` or `--handoff`). |
| Direction | ingest |
| Inputs | `--url-file PATH` (untrusted local file of URLs, one per line, `#` comments); `--playlist URL` (untrusted; expanded via yt-dlp's flat extract); `--handoff PATH` (JSONL produced by an external trusted-or-untrusted exporter); `--limit N`; `--run-id` (used as a path component); `--resume`; vault + transcript flags as in single-URL mode. |
| Auth assumptions | None for public playlists. Cookie-bearing handoff files (see `--export-playlist`) imply the *creator* of the handoff was authenticated; this consumer is not. |
| Side effects | Writes a JSON staging manifest at `<vault>/.vault-lifestyle/youtube/runs/<run-id>/manifest.json` (atomic via `manifest.save_manifest`); writes one `<vault>/raw/<slug>.md` per video; updates the manifest on every state transition (`pending` → `processing` → `raw_written` / `skipped_existing` / `failed`). |
| Filesystem access | Reads: the url-file or handoff file, the existing manifest if `--resume`. Writes: the manifest, per-video raw pages, and a tempdir per Whisper run. |
| Network access | yt-dlp egress for playlist expansion (one call per `--playlist` URL via `inputs._fetch_playlist_info`, `extract_flat=True`) and per-video metadata + transcript. Same retry policy as single-URL mode. |
| Trust boundary | The url-list file is treated as untrusted text. Each line is reparsed through `inputs._parse_youtube_input`, which enforces an allow-list of hosts (`youtube.com`, `m.youtube.com`, `music.youtube.com`, `youtu.be`). Handoff JSONL is shape-validated by `handoff._validate_shape` against a small allow-list of fields; unknown keys are rejected. `--run-id` is used as a path segment under `.vault-lifestyle/`; it is not sanitized — a malicious caller could pass `../../etc/passwd-style` strings. See misuse case below. |
| Lethal-trifecta exposure | **No** (same composition as single-URL: untrusted-input + local-write only). |
| Safe test payload | A `tests/fixtures/`-style URL-list with two known-public video URLs; run with `--dry-run` to see the expansion count without writing. The repo's own `youtube/tests/test_cli.py::test_url_file_dry_run` exercises this shape. |
| Misuse / abuse cases | — `--run-id "../../../etc/passwd"` → directory traversal under `<vault>/.vault-lifestyle/`: the run-id is interpolated directly into the manifest path via `manifest.default_manifest_path`. The vault root is the realistic write boundary, but a hostile run-id can still place a manifest outside `.vault-lifestyle/`. **P1.**<br>— Handoff JSONL with thousands of records → resource exhaustion: no record-count cap. **P2.**<br>— Handoff record with attacker-chosen `playlist_title` flowing into the raw frontmatter via `cli._raw_provenance`: the value is preserved verbatim into YAML. yaml.safe_dump escapes, Pydantic re-validates, so this is parse-safe. **P3.**<br>— `--url-file` pointed at a 100 MB random-bytes file: read with `Path.read_text(encoding="utf-8")` — utf-8 decode error rejects it. **P3.** |

### vault-yt --export-playlist (plugin: youtube)

| Field | Value |
|---|---|
| Entry point | `youtube/src/vault_yt/cli.py:_export_playlist` → `youtube/src/vault_yt/ytdlp_playlist_exporter.py:export_playlist_handoff`. |
| Direction | ingest (writes a local handoff JSONL; no vault writes). |
| Inputs | `--export-playlist URL` (untrusted YouTube playlist URL); `--output PATH` (caller-chosen local path); `--browser BROWSER[+KEYRING][:PROFILE][::CONTAINER]` OR `--cookies PATH` (Netscape cookie file). |
| Auth assumptions | **Authenticated.** Either reads cookies from a chosen browser via yt-dlp's `cookiesfrombrowser` (which calls into the OS keyring for encrypted cookie DBs) OR reads a Netscape-format cookie file from the caller's disk. These cookies grant access to private playlists tied to the user's YouTube/Google account. |
| Side effects | Writes the JSONL handoff to `--output`. Does NOT write the vault. yt-dlp may briefly hold cookies in memory; they are not persisted by this codebase. |
| Filesystem access | Reads: browser cookie database (via OS keyring) OR the user-supplied cookie file. Writes: the `--output` JSONL path (parent dir created via `write_handoff`). |
| Network access | yt-dlp egress to YouTube playlist endpoint with the user's session cookies attached. |
| Trust boundary | Cookies enter via the `--browser` spec (allow-list validated against `yt_dlp.cookies.SUPPORTED_BROWSERS`) or `--cookies PATH`. Playlist URL is untrusted; passed straight to yt-dlp. The resulting JSONL records carry `playlist_title`, `playlist_url`, `channel`, `channel_url`, etc., which are attacker-controllable-in-theory if the user's playlist contains a video uploaded by a malicious party — but those values flow back into the consumer through the shape-validated handoff schema (`handoff._validate_shape`). |
| Lethal-trifecta exposure | **Yes** (latent). Private-data leg: browser cookies / Google session. Untrusted-input leg: any playlist content authored by third parties (titles, descriptions). Exfil leg: not in this tool by itself, but the handoff file is the bridge — it can carry attacker-controlled strings into a later `vault-yt --handoff` ingest that writes them into the vault. Treat the handoff file as a privileged artifact: do not paste it into prompts, do not commit it, do not store it in the vault. README §"Treat browser cookies and cookie files as account secrets" reflects this. **P0 if mishandled.** |
| Safe test payload | Use a public playlist with no auth: `uv --directory youtube run vault-yt --export-playlist "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf" --output /tmp/handoff.jsonl` (no `--browser` / `--cookies` — exercises the `yt-dlp-public` provider path). |
| Misuse / abuse cases | — Cookie theft via accidental commit: `--output` could be a path inside the repo. The repo's `.gitignore` does not list `.jsonl`, so a committed handoff would leak playlist membership (not auth tokens). Operator discipline + README warning is the only mitigation. **P1.**<br>— Malicious `--browser` spec attempting profile traversal (`firefox:../../`): `parse_browser_spec` regex-matches but profile/container strings are passed verbatim to yt-dlp. yt-dlp's own validation is the inner boundary. **P2.**<br>— `--cookies PATH` pointed at `/dev/zero` or a malicious cookie file: yt-dlp reads it. A crafted cookie file could lie about the origin domain, but yt-dlp filters by request host. **P2.**<br>— Long-lived auth: a handoff file produced today encodes nothing secret, but the user's cookie jar is captured by yt-dlp in-process. Rotating the underlying Google session invalidates cookies; the handoff file itself remains usable for an attacker who only needs the video-id list. **P1.** |

### vault-yt --handoff (plugin: youtube)

| Field | Value |
|---|---|
| Entry point | `youtube/src/vault_yt/cli.py:command` (when `--handoff` is set, joins the batch path via `_handoff_inputs` + `_run_batch`). |
| Direction | ingest |
| Inputs | `--handoff PATH` (JSONL produced by `--export-playlist` OR by a third-party MCP/CLI exporter following `docs/youtube-handoff-adapter-contract.md`). |
| Auth assumptions | None. The handoff file IS the auth boundary — the consumer is unauthenticated, the producer was. |
| Side effects | Same as batch ingest: writes the staging manifest + per-video raw pages. The provenance fields from the handoff (`source_provider`, `playlist_id`, `playlist_title`, `playlist_url`, `playlist_index`) propagate into the raw frontmatter via `cli._raw_provenance`. |
| Filesystem access | Reads: the JSONL file. Writes: same as batch ingest. |
| Network access | Same as batch ingest — yt-dlp egress per video for metadata + transcript. The playlist is NOT re-expanded; the handoff file is the source of truth for which videos to fetch. |
| Trust boundary | Handoff records pass through `handoff._validate_shape` (unknown fields rejected, type-checked, `playlist_index >= 1`). `parse_video_id` enforces that any URL points to a recognized YouTube host. The `source_provider` field is preserved verbatim into the manifest and frontmatter. |
| Lethal-trifecta exposure | **No** for this tool in isolation. With `--export-playlist` upstream, the *pipeline* composes the trifecta (see above). |
| Safe test payload | `youtube/examples/engineering-handoff.jsonl` is a checked-in two-record example. Validate without ingesting: `uv --directory youtube run vault-yt --validate-handoff youtube/examples/engineering-handoff.jsonl`. |
| Misuse / abuse cases | — Handoff with `playlist_title: "<script>alert(1)</script>"` → that text reaches the raw markdown frontmatter and the vault on disk. YAML serialization escapes specials; downstream vault rendering is responsible for HTML-safe output. **P3** here, **P2** at the vault rendering layer.<br>— Handoff with thousands of records → resource exhaustion + cost (yt-dlp egress per video). `--limit` is the only throttle and is opt-in. **P2.** |

### vault-yt --validate-handoff (plugin: youtube)

| Field | Value |
|---|---|
| Entry point | `youtube/src/vault_yt/cli.py:_validate_handoff` → `youtube/src/vault_yt/handoff.py:validate_handoff`. |
| Direction | read-only (parse-only). |
| Inputs | `--validate-handoff PATH` (untrusted JSONL file). |
| Auth assumptions | None. |
| Side effects | None. Prints per-line validation errors to stderr; exits 0/2. |
| Filesystem access | Reads the JSONL file. |
| Network access | None. |
| Trust boundary | Parse-only: shape validation through `handoff._validate_shape`. |
| Lethal-trifecta exposure | No. |
| Safe test payload | `uv --directory youtube run vault-yt --validate-handoff youtube/examples/engineering-handoff.jsonl`. |
| Misuse / abuse cases | — Adversarial JSONL designed to OOM the parser: each line is `json.loads`-decoded individually. Very long lines could pressure memory; no per-line size cap. **P3.** |

### vault-yt --add-finding / --add-evidence / --report (plugin: youtube)

| Field | Value |
|---|---|
| Entry point | `youtube/src/vault_yt/cli.py:_add_finding`, `_add_evidence`, `_print_report` → `youtube/src/vault_yt/manifest.py` mutators. |
| Direction | mixed (read manifest + write manifest). |
| Inputs | `--run-id` (path segment), `--video-id`, `--claim`, `--transcript-span`, `--confidence 0..1`, `--finding-id`, `--evidence-url`, `--verifier`, `--verification-result {accepted,rejected,unresolved,conflicting}`, `--notes`. All user-supplied free-text. |
| Auth assumptions | None. Local manifest mutation only. |
| Side effects | Atomic rewrite of `<vault>/.vault-lifestyle/youtube/runs/<run-id>/manifest.json` via `manifest.save_manifest`. Updates summary counts + per-item state. |
| Filesystem access | Reads + writes the manifest JSON file. No vault `raw/` writes. |
| Network access | None. |
| Trust boundary | Free-text fields flow verbatim into the manifest JSON (`evidence_url`, `claim`, `notes`). `verification_result` is allow-list checked. |
| Lethal-trifecta exposure | No. |
| Safe test payload | The repo's `youtube/tests/test_cli.py::test_add_finding_and_evidence` exercises the round-trip against a tmp vault. |
| Misuse / abuse cases | — `--run-id "../../etc/passwd"` → manifest write outside `.vault-lifestyle/`. Same vector as batch ingest. **P1.**<br>— `--evidence-url` set to a phishing URL → that URL ends up in the manifest and any downstream report. Treat manifest contents as user-provided; do not auto-fetch evidence URLs. **P3** for this tool; **P1** if a future report auto-resolves them. |

### vault-yt importable APIs (plugin: youtube)

The following functions are importable from `vault_yt` and are exercised by
tests + by the CLI. They are listed here because a future caller (a sibling
plug-in, a vault skill, a one-off script) inherits the same trust profile:

- `extractor.fetch_meta(url)`, `fetch_captions(url, lang)`,
  `download_audio(url, dest_dir)` — all egress through yt-dlp. Same network
  and trust profile as single-URL ingest. Inherit caller's auth (none by
  default; cookies if the caller wraps yt-dlp differently).
- `whisper_fallback.transcribe_audio(audio_path, model)` — local-only,
  no network. Reads the audio file; loads a Whisper model from
  `~/.cache/whisper/`.
- `inputs.expand_input(value)`, `expand_inputs(values)`,
  `parse_video_id(url)` — parse-only.
- `handoff.read_handoff(path)`, `write_handoff(path, records)`,
  `validate_handoff(path)` — parse-only / local-write-only.
- `manifest.new_manifest`, `save_manifest`, `load_manifest`,
  `update_item_status`, `add_candidate_finding`, `add_verification_evidence`,
  `render_run_report` — local manifest JSON I/O.
- `ytdlp_playlist_exporter.export_playlist_handoff(...)` — see the
  `--export-playlist` tool above; same auth and network profile.
- `writer.build_raw_md(meta, transcript, transcript_source, ...)` and
  `write(path, content, force=False)` — frontmatter assembly + atomic write
  through `lib/raw_writer.py`.

These do not need separate manifest rows unless a future caller composes
them in a way that changes the trust profile. The audit checklist covers
the "did this composition change the profile?" gate.

---

## vault-spotify (plugin: spotify)

Console script registered in `spotify/pyproject.toml` as
`vault-spotify = "vault_spotify.cli:main"`. Slice 1 of 5 — currently only
the `auth` subcommand is functional; `recent` exits with code 7
intentionally until OGR-75.

### vault-spotify auth (plugin: spotify)

| Field | Value |
|---|---|
| Entry point | `spotify/src/vault_spotify/cli.py:auth` → `vault_spotify/auth.py:run_auth_dance`. |
| Direction | act (initiates an OAuth dance with Spotify on the user's behalf). |
| Inputs | `--client-id <id>` OR `$SPOTIFY_CLIENT_ID` env OR `client_id = "..."` in `~/.config/vault-lifestyle-plugins/spotify.toml`. CLIENT_ID is public-by-OAuth-design (not a secret). |
| Auth assumptions | OAuth 2.0 with PKCE. **No client secret in this codebase.** User opens the browser, grants the requested scopes (`user-read-recently-played`, `user-read-playback-state`), and the local redirect server captures the auth code. spotipy handles the PKCE code-verifier. |
| Side effects | Spins up a localhost server on `127.0.0.1:8888` (via spotipy) to receive the OAuth redirect; opens the user's default browser to `https://accounts.spotify.com/authorize`; on success, persists access + refresh tokens as JSON at the resolved cache path. |
| Filesystem access | Reads: `~/.config/vault-lifestyle-plugins/spotify.toml` (CLIENT_ID config). Writes: the token cache. The cache path resolution chain is `$VAULT_SPOTIFY_TOKEN_CACHE` → `$XDG_DATA_HOME/vault-lifestyle-plugins/spotify-tokens.json` → `~/.local/share/vault-lifestyle-plugins/spotify-tokens.json`. The cache file contains the refresh token (long-lived) and the access token (short-lived). Parent dirs are created via `Path.mkdir(parents=True, exist_ok=True)`. **The token cache is chmodded to `0600`** after the dance: spotipy `>= 2.25.1` does this itself (GHSA-pwhh-q4h6-w599), and `auth.run_auth_dance` re-asserts `0600` defensively via `_restrict_cache_permissions` regardless of the installed spotipy. The pinned floor is `spotipy>=2.25.1` so a pip install can't pull a pre-chmod release. |
| Network access | Outbound to `accounts.spotify.com` for the OAuth dance (browser-initiated). Inbound on `127.0.0.1:8888/callback` for the redirect (loopback-only). Refresh requests later: `accounts.spotify.com/api/token`. |
| Trust boundary | CLIENT_ID is not secret. The redirect URI is hard-coded to `http://127.0.0.1:8888/callback`; if a malicious local process binds 8888 first, spotipy will fail to bind (collision) — not silently take over. The token cache is the high-value artifact. The local loopback callback is exposed only to local processes; loopback OAuth flows are vulnerable to local-port-snooping by another process on the same machine in the brief window between auth-code receipt and exchange. |
| Lethal-trifecta exposure | **Latent.** Private-data leg: yes (tokens grant `user-read-recently-played` access). Untrusted-input leg: not in this tool today (auth is interactive + browser-driven). Exfil leg: outbound to spotify.com only. The trifecta would form if a *future* tool both reads listening history AND ingests untrusted external prompts AND has an open egress channel — that future tool is the audit target. **P1** today on token-handling alone. |
| Safe test payload | The CLI itself has a `--client-id` flag; in tests, `run_auth_dance(client_id="dummy", open_browser=False)` runs the auth setup without launching a browser (spotipy will time out waiting for the redirect, which is fine for test isolation). See `spotify/tests/test_auth.py`. |
| Misuse / abuse cases | — Token cache readable by other local users on a shared box: default umask is typically 0022 → 0644 file perms. Refresh token leaks if the box is multi-user. **Mitigated (L4):** `auth.run_auth_dance` chmods the cache to `0600` after the dance (`_restrict_cache_permissions`), spotipy `>= 2.25.1` does the same (GHSA-pwhh-q4h6-w599), and the dependency floor is pinned to `>=2.25.1` so a pip install cannot pull a pre-chmod release.<br>— Loopback OAuth interception: another local process binding 8888 before spotipy does → auth code intercepted. Today spotipy fails on collision (no silent steal), but no mitigation against pre-existing same-process malware. **P2.**<br>— Malicious `--client-id` from a phished setup doc → user grants scopes to an attacker-controlled app → attacker holds the refresh token. CLIENT_ID is public, but binding the user's session to an attacker's app is the real harm. **P1.** Mitigation: README §"Per-user Spotify app" makes the user create their own app; phishing risk is on the human-trust layer, not this code.<br>— Tokens persist forever until manually revoked. No expiry on the refresh token itself. **P2.** |

### vault-spotify recent (plugin: spotify)

| Field | Value |
|---|---|
| Entry point | `spotify/src/vault_spotify/cli.py:recent`. **Deferred — exits with code 7.** |
| Direction | (planned: ingest) |
| Inputs | (planned) `--vault`, `--limit`, `--force`, `--verbose`, `--dry-run`. |
| Auth assumptions | (planned) Reads the token cache via `vault_spotify.auth.load_or_refresh_token`. |
| Side effects | **None today.** Print + exit 7. |
| Filesystem access | None today. |
| Network access | None today. |
| Trust boundary | n/a today. |
| Lethal-trifecta exposure | n/a today. **Re-audit before OGR-75 ships.** That slice will introduce the private-data leg + a per-event vault write that composes most of the trifecta — see the audit checklist's "composing previously isolated tools" gate. |
| Safe test payload | `uv --directory spotify run vault-spotify recent` (returns exit 7 with the deferred-feature message). |
| Misuse / abuse cases | None today. Listed here so the manifest stays current as the feature lands. |

### vault-spotify importable APIs (plugin: spotify)

- `auth.resolve_client_id(arg=None, env=..., config_path=...)` — config
  read; no network, no writes.
- `auth.run_auth_dance(client_id, cache_path=None, open_browser=True)` —
  see `vault-spotify auth` row above.
- `auth.load_or_refresh_token(client_id, cache_path=None)` — reads the
  token cache, refreshes via `accounts.spotify.com/api/token` if needed,
  returns an access-token string. Same network + filesystem profile as
  the auth dance, minus the browser interaction.

---

## lib/ (shared utilities)

No CLI entry points. No console scripts. No `[project.scripts]` block. The
package exposes importable functions consumed by integration plug-ins.

### lib/vault_resolver.resolve_vault_path

| Field | Value |
|---|---|
| Entry point | `lib/vault_resolver.py:resolve_vault_path`. |
| Direction | read-only utility. |
| Inputs | `arg: Path | str | None`, optional `env` mapping (default `os.environ`), optional `config_path` (default `~/.config/vault-lifestyle-plugins/config.toml`). |
| Auth assumptions | None. |
| Side effects | None. Read-only directory introspection. |
| Filesystem access | Reads: the TOML config file (if present); the candidate vault directory (existence + `raw/` + `wiki/` or `_templates/` checks). |
| Network access | None. |
| Trust boundary | Caller-supplied path. `Path.resolve()` follows symlinks. No chroot. |
| Lethal-trifecta exposure | No. |
| Safe test payload | `lib/tests/test_vault_resolver.py` covers the three resolution branches against tmp paths. |
| Misuse / abuse cases | — Symlinked vault pointing at the user's home: `resolve_vault_path` accepts any dir with the right shape, so writes go wherever the symlink resolves. **P2.** Mitigation: callers (e.g. `cli.py`) check `os.access(raw_dir, os.W_OK)` and rely on the user's shell to scope the `--vault` arg.<br>— TOML config injection: `tomllib.load` is parse-only; non-string `vault_path` is ignored. **P3.** |

### lib/raw_writer (build_raw_markdown + write_raw_file)

| Field | Value |
|---|---|
| Entry point | `lib/raw_writer.py:build_raw_markdown(frontmatter, body)` and `write_raw_file(path, content, force=False)`. |
| Direction | ingest (the only direct vault-write helper in this codebase). |
| Inputs | `frontmatter: Mapping[str, Any]` (caller-built dict); `body: str` (caller-built transcript or content); `path: Path` (caller-chosen destination); `force: bool`. |
| Auth assumptions | None. |
| Side effects | Validates frontmatter against `frontmatter_schema.Frontmatter` (Pydantic). Atomically writes the markdown via `tempfile.mkstemp` + `tmp_path.replace(path)`. Creates parent dirs. Refuses writes outside a `raw/` parent: `_ensure_raw_destination` enforces `path.parent.name == "raw"`. |
| Filesystem access | Writes: the destination path. Creates: a sibling temp file in the same dir (for atomic replace). |
| Network access | None. |
| Trust boundary | Frontmatter values flow through Pydantic; YAML is serialized via `yaml.safe_dump` (no `!!python/object` etc). Body text is written verbatim. |
| Lethal-trifecta exposure | No (no untrusted-input leg by itself; no exfil). |
| Safe test payload | `lib/tests/test_raw_writer.py` covers the happy path + collision + validation failure. |
| Misuse / abuse cases | — Caller composes a body containing markdown image refs pointing at attacker servers → vault page renders an HTTP-tracked image when viewed in Obsidian. **P2.** Mitigation: downstream `/vault ingest` is the trust gate for body content; not this layer.<br>— Caller bypasses `_ensure_raw_destination` by passing a path whose parent is named `raw/` but is symlinked outside the vault: the helper does not call `resolve()` on the parent. **P2.** |

### lib/frontmatter_schema.validate_frontmatter

| Field | Value |
|---|---|
| Entry point | `lib/frontmatter_schema.py:validate_frontmatter(d)`. |
| Direction | pure validation. |
| Inputs | A dict to validate. |
| Auth assumptions | None. |
| Side effects | None. Raises `pydantic.ValidationError` on bad input. |
| Filesystem access | None. |
| Network access | None. |
| Trust boundary | Defensive — this is the gate, not a tool that crosses one. |
| Lethal-trifecta exposure | No. |
| Safe test payload | `lib/tests/test_frontmatter_schema.py`. |
| Misuse / abuse cases | None directly. Bypass risk: callers that build frontmatter dicts and serialize them without calling `validate_frontmatter` first lose the contract. `raw_writer.build_raw_markdown` enforces validation centrally. |

---

## MCP server surface

**None today.** This repo does not expose an MCP server. The `source_provider`
field in handoff JSONL can carry a string like `youtube-mcp`, but that is
metadata about *who produced the handoff* — not a tool exposed by this repo.

If a future slice ships an MCP server (e.g. exposing `vault-yt` as an MCP
tool to other agents), add a manifest section here using the standard
contract and re-evaluate the lethal-trifecta composition: MCP exposure
explicitly broadens the "untrusted input" surface to any model the server
talks to. See `[[agentic-attack-surface]]`.

---

## Staleness check

This manifest is gated by `tests/test_manifest_coverage.py`. It discovers
every `[project.scripts]` entry in the monorepo and asserts each script has
a heading under one of the recognized plug-in sections in this file.
Pytest fails when a new console script ships without a manifest section.

Run locally:

```bash
uv --directory lib run pytest tests/test_manifest_coverage.py
```

The how-to-audit doc has the full invocation, including how to add a new
tool to the manifest without tripping the check.

## Related vault topics

- `[[lethal-trifecta]]` — the trifecta framing used throughout.
- `[[agentic-attack-surface]]` — broader MCP/agent attack-surface model.
- `[[non-human-identity-management]]` — OAuth refresh-token lifecycle.
- `[[ai-model-supply-chain-risk]]` — yt-dlp / spotipy / whisper pin policy.
