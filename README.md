# vault-lifestyle-plugins

Lifestyle integration plug-ins for [second-brain](https://github.com/itotallyforgot/second-brain): automate ingestion of insights from daily-use services and later act on toil for you.

## What this is

A monorepo of independently-shippable plug-ins that overlay onto a second-brain-shaped vault. Each plug-in:

- Lives in its own subdirectory with its own runtime (Python, Node, etc.) and dep manifest
- Reads from external services and writes to the vault's `raw/` (ingest direction)
- OR acts on external services on the user's behalf (action direction; e.g. email triage, calendar updates)
- Shares vault-write helpers + frontmatter validation via the umbrella `lib/`
- Is opt-in: install only the plug-ins you want

## Roadmap

| Plug-in | Direction | Runtime | Status |
|---|---|---|---|
| `youtube/` | Ingest (transcript) | Python | **MVP in progress:** on-demand CLI tracer |
| `spotify/` | Ingest (listening history) | Python | Planned |
| `gmail/` | Action (spam triage, label) | TBD (Python or Node) | Planned |
| `calendar/` | Action (event management) | TBD | Planned |
| `rss/` | Ingest (generic feed) | Python | Planned |
| `whatsapp/`, `instagram/`, `facebook/` | Mixed | TBD | Stretch |

## Design rules

- **Plug-in for a standalone vault.** second-brain depends on no plug-ins; this repo overlays onto a target vault when installed. The vault works without us; we add capability.
- **Per-integration runtime freedom.** YouTube uses Python (yt-dlp). A future Gmail agent might use Node (better SDK). Each subdir picks its own toolchain.
- **Output convention.** Every ingest plug-in writes a vault-compatible file under `raw/` with frontmatter compatible with second-brain's `/vault ingest` skill (`ingested: false`, `clipped_at`, source URL field, etc.). The shared `lib/` package codifies the contract.
- **No vault writes outside `raw/`.** Plug-ins ingest sources; the vault's own `/vault ingest` skill is the only writer for `wiki/`. Action-direction plug-ins (email, calendar) DO NOT touch the vault; they act on external services.
- **Auth handled per integration.** Public sources (YouTube videos, RSS) need none. Personal data (Spotify history, Gmail) goes through OAuth via the integration's local config. No central auth broker; each plug-in owns its own credentials.

## Install

Pick the integrations you want. Each has its own install / config story documented in its subdirectory's README. The umbrella has no top-level install; just `git clone` to get the source.

## Architecture

```
vault-lifestyle-plugins/
├── README.md             ← this file
├── LICENSE
├── .gitignore
├── lib/                  ← shared utilities (Python; bridge to other runtimes via JSON)
│   └── vault_write/      ← raw/ writer + frontmatter validator
├── youtube/              ← Python, yt-dlp + Whisper, on-demand CLI
│   ├── pyproject.toml
│   ├── README.md
│   └── src/
├── spotify/              ← (planned)
├── gmail/                ← (planned)
└── ...                   ← additional integrations as siblings
```

Each integration is independently:

- Runnable (`uv --directory youtube run vault-yt <url>`)
- Versioned (its own `pyproject.toml` / `package.json`)
- Documented (its own README with install + use)
- Tested (its own test suite under `youtube/tests/`)

## Lineage

Companion to:

- [second-brain](https://github.com/itotallyforgot/second-brain): the standalone vault this overlays onto.
- [vault-retrieval-engine](https://github.com/itotallyforgot/vault-retrieval-engine): sister plug-in that adds local retrieval (graph + vector). Independent install.

Per `second-brain/_ops/2026-05-04-portfolio-split-migration.md`, this repo is one of the optional plug-ins layered on top of the standalone vault.
