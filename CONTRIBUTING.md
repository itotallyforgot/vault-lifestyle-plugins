# Contributing

Conventions for working on `vault-lifestyle-plugins`.

## Workflow

1. **Read first.** Before touching code, skim `CONTEXT.md` and any relevant
   ADRs in `docs/adr/` for the decisions behind the area you're changing.
2. **Track it in an issue.** Open or claim a GitHub issue describing the change
   before you start, so work isn't duplicated.
3. **Branch convention.** `<type>/<short-slug>` — e.g. `feat/whisper-fallback`,
   `fix/caption-glob`.
4. **Commit message convention.** [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`), scoped to the
   integration where useful:

   ```
   feat(youtube): caption fetch via yt-dlp
   ```

5. **PR title.** Use the Conventional Commit subject. The PR template
   (`.github/PULL_REQUEST_TEMPLATE.md`) autopopulates — fill in the verify line
   with the actual command and observed output.
6. **CI must pass.** `gitleaks`, `zizmor`, `harden-runner`, `ruff`, `pytest`.
   No bypass with `--no-verify`.

## Local setup

### Set up pre-commit hooks (required)

This repo enforces secret scanning (gitleaks), formatting (ruff-format), and lint (ruff) in CI. The same checks run locally via [pre-commit](https://pre-commit.com/) — but only if you install the git hooks once after cloning. Without this step, the local gate is silent and the first time a violation is caught is in CI, after your commit (and any leaked secret) is already in git history.

Install once per clone:

```bash
pip install pre-commit              # or: pipx install pre-commit / brew install pre-commit
pre-commit install                  # registers .git/hooks/pre-commit
pre-commit install --install-hooks  # pre-fetch hook deps (optional, faster first run)
```

After this, `git commit` runs gitleaks + ruff + ruff-format + the standard hygiene hooks (trailing whitespace, EOF, merge-conflict markers, private-key detection) against your staged changes. Commits that fail the hooks are blocked locally. Hook config lives in `.pre-commit-config.yaml`.

To run all hooks against the whole tree on demand (useful before opening a PR):

```bash
pre-commit run --all-files
```

**Why this matters.** Gitleaks catching a credential at the pre-commit stage prevents it from ever landing in your local git history. Catching it in CI means the secret is already in a pushed commit and must be rotated, not just removed. Always rotate any credential that touched git, even if force-pushed away.

## Layout

```
vault-lifestyle-plugins/
├── README.md
├── CONTRIBUTING.md           ← this file
├── CONTEXT.md
├── LICENSE
├── .gitignore
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/            ← CI
├── docs/                     ← contracts, ADRs, runbooks
├── lib/                      ← shared utilities (Python; bridge to other runtimes via JSON)
│   ├── pyproject.toml
│   ├── vault_resolver.py
│   ├── frontmatter_schema.py
│   └── schemas/
│       └── raw_frontmatter.json
├── youtube/                  ← YouTube transcript integration
│   ├── pyproject.toml
│   ├── README.md
│   ├── src/vault_yt/
│   └── tests/
├── spotify/                  ← Spotify listening-history integration
└── (future)/                 ← gmail/, calendar/, rss/, etc.
```

## Per-integration conventions

Each integration subdir is independently:

- **Versioned** — its own `pyproject.toml` (or `package.json` for Node-based integrations).
- **Documented** — its own `README.md` covering install, use, env vars, troubleshooting.
- **Tested** — its own `tests/` directory with pytest (or equivalent runner).
- **Runtime-free** — no shared global state across integrations; each picks its own toolchain.

Shared code lives in `lib/` only. Per-integration code never imports from a sibling integration.

## Output contract (ingest-direction integrations)

Plug-ins that write to the vault's `raw/` MUST produce frontmatter compatible with the vault's `/vault ingest` skill. See `lib/frontmatter_schema.py` for the Pydantic model + `lib/schemas/raw_frontmatter.json` for the language-agnostic JSON Schema.

Required minimum frontmatter:
- `source_url` (or `url`) — the source URL
- `clipped_at` — ISO 8601 timestamp
- `ingested: false` — gates `/vault ingest` for new files

Optional but encouraged:
- `source_kind` (e.g. `youtube`, `spotify-track`, `rss-item`)
- `tags` (always include the integration name, e.g. `[youtube]`)
- Any source-specific metadata (channel, author, published_at, duration_seconds, transcript_source, etc.)

## Auth conventions

- Public-source plug-ins (YouTube videos, public RSS, public web): no auth required.
- Private-source plug-ins (Spotify history, Gmail, personal YouTube subscriptions): OAuth. Each plug-in owns its own credential storage. Tokens go to `.tokens/` per-integration; never to repo. `.gitignore` excludes `*token*.json`, `credentials*.json`, `client_secret*.json`, and `.tokens/`.

## Standalone-vault rule

Vault is sovereign. Plug-ins do not require modifications to the vault's `skills/`, `CLAUDE.md`, or `vault_map.md`. If an integration genuinely needs vault-side changes, raise it as a separate issue against the vault repo first; this repo doesn't drive vault changes.

## Lineage

- The standalone vault this overlays onto (bring your own — see the root [README](README.md#install)).
- [vault-retrieval-engine](https://github.com/itotallyforgot/vault-retrieval-engine) — sister plug-in (retrieval) using the same vault-write contract.
