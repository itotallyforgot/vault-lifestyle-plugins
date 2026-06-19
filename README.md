# vault-lifestyle-plugins

Lifestyle integration plug-ins for [markdown-vault](https://github.com/itotallyforgot/markdown-vault): automate ingestion of insights from daily-use services and later act on toil for you.

## What this is

A monorepo of independently-shippable plug-ins that overlay onto a markdown-vault-shaped vault. Each plug-in:

- Lives in its own subdirectory with its own runtime (Python, Node, etc.) and dep manifest
- Reads from external services and writes to the vault's `raw/` (ingest direction)
- OR acts on external services on the user's behalf (action direction; e.g. email triage, calendar updates)
- Shares vault-write helpers + frontmatter validation via the umbrella `lib/`
- Is opt-in: install only the plug-ins you want

## Roadmap

| Plug-in | Direction | Runtime | Status |
|---|---|---|---|
| `youtube/` | Ingest (transcript) | Python | **MVP shipped** — `vault-yt <url>` writes a transcript page to `<vault>/raw/`. Captions via yt-dlp; Whisper fallback when captions are absent. |
| `spotify/` | Ingest (listening history) | Python | Planned |
| `gmail/` | Action (spam triage, label) | TBD (Python or Node) | Planned |
| `calendar/` | Action (event management) | TBD | Planned |
| `rss/` | Ingest (generic feed) | Python | Planned |
| `whatsapp/`, `instagram/`, `facebook/` | Mixed | TBD | Stretch |

## Design rules

- **Plug-in for a standalone vault.** markdown-vault depends on no plug-ins; this repo overlays onto a target vault when installed. The vault works without us; we add capability.
- **Per-integration runtime freedom.** YouTube uses Python (yt-dlp). A future Gmail agent might use Node (better SDK). Each subdir picks its own toolchain.
- **Output convention.** Every ingest plug-in writes `raw/<slug>.md` with frontmatter compatible with markdown-vault's `/vault ingest` skill (`source_url`, `clipped_at`, `ingested: false` are required; rich optional fields preserved as source-page metadata). Slug shape is per-plug-in (e.g. YouTube uses `<yyyy-mm-dd>-youtube-<video_id>-<sanitized-title>`). The shared `lib/frontmatter_schema.py` Pydantic model + `lib/schemas/raw_frontmatter.json` JSON Schema codify the contract.
- **No vault writes outside `raw/`.** Plug-ins ingest sources; the vault's own `/vault ingest` skill is the only writer for `wiki/`. Action-direction plug-ins (email, calendar) DO NOT touch the vault — they act on external services.
- **Auth handled per integration.** Public sources (YouTube videos, RSS) need none. Personal data (Spotify history, Gmail) goes through OAuth via the integration's local config. No central auth broker; each plug-in owns its own credentials.

## Install

Pick the integrations you want. Each has its own install / config story documented in its subdirectory's README. The umbrella has no top-level install; just `git clone` to get the source.

If you're contributing, run `pre-commit install` after cloning so gitleaks + ruff run on every local commit — see [CONTRIBUTING.md → Local setup](CONTRIBUTING.md#local-setup).

## Architecture

```
vault-lifestyle-plugins/
├── README.md                     ← this file
├── LICENSE                        (MIT)
├── CONTRIBUTING.md
├── .gitignore
├── .github/                       ← CI: gitleaks, zizmor, ruff, pytest, scorecard, dependabot
├── lib/                           ← shared utilities (Python)
│   ├── pyproject.toml
│   ├── vault_resolver.py          ← --vault → $VAULT_PATH → ~/.config/...toml
│   ├── frontmatter_schema.py      ← Pydantic model for raw/ frontmatter
│   └── schemas/
│       └── raw_frontmatter.json   ← JSON-schema mirror for non-Python siblings
├── youtube/                       ← Python, yt-dlp + Whisper, on-demand CLI (vault-yt)
│   ├── pyproject.toml
│   ├── README.md
│   ├── src/vault_yt/
│   └── tests/
├── spotify/                       ← (planned)
├── gmail/                         ← (planned)
└── ...                            ← additional integrations as siblings
```

Each integration is independently:

- Runnable (`vault-yt <url>` for the YouTube plug-in once installed; from a checkout, `uv --directory youtube run vault-yt <url>`)
- Versioned (its own `pyproject.toml` / `package.json`)
- Documented (its own README with install + use)
- Tested (its own test suite under `youtube/tests/`)

## Lineage

Companion to:

- [markdown-vault](https://github.com/itotallyforgot/markdown-vault): the standalone vault this overlays onto.
- [vault-retrieval-engine](https://github.com/itotallyforgot/vault-retrieval-engine): sister plug-in that adds local retrieval (graph + vector). Independent install.

This repo is one of the optional plug-ins layered on top of the standalone vault.
