# Contributing

Conventions for working on `vault-lifestyle-plugins`.

## Workflow

1. **Read first.** Before touching code, skim:
   - `markdown-vault/internal-notes` — for the YouTube integration's contract.
   - `markdown-vault/internal-notes` — for the slice plan + verify lines.
   - `markdown-vault/_ops/activity-log.md` — for in-flight work across parallel sessions.
   - The relevant Linear issue (OGR-N) for the latest decisions.

2. **Claim before working.** If you have Linear MCP authentication, set yourself as assignee + flip the Linear issue to "In Progress." Otherwise comment on the linked GitHub issue. Append a `claim` block to `activity-log.md` per its conventions.

3. **Branch convention.** `OGR-N-<short-slug>` — e.g. `ISSUE-N-lib-shared-helpers`, `ISSUE-N-whisper-fallback`.

4. **Commit message convention.** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`). Reference Linear ID in subject or trailer:

   ```
   feat(youtube): caption fetch via yt-dlp (ISSUE-N)
   ```

5. **PR title convention.** `[OGR-N] <conventional-commit-subject>`. Linear auto-links + auto-closes OGR-N on merge.

6. **PR template.** `.github/PULL_REQUEST_TEMPLATE.md` autopopulates. Match the slice plan's verify line.

7. **CI must pass.** `gitleaks`, `zizmor`, `harden-runner`, `ruff`, `pytest`. No bypass with `--no-verify`.

8. **Release.** Append a `release` block to `activity-log.md` when your slice merges.

## Layout

```
vault-lifestyle-plugins/
├── README.md
├── CONTRIBUTING.md           ← this file
├── LICENSE
├── .gitignore
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/            ← CI added by Slice 6 (ISSUE-N)
├── lib/                      ← shared utilities (Python; bridge to other runtimes via JSON)
│   ├── pyproject.toml
│   ├── vault_resolver.py     ← Slice 1 / ISSUE-N
│   ├── frontmatter_schema.py ← Slice 1 / ISSUE-N
│   └── schemas/
│       └── raw_frontmatter.json
├── youtube/                  ← first integration (Slices 2-5 / ISSUE-N through ISSUE-N)
│   ├── pyproject.toml
│   ├── README.md
│   ├── src/vault_yt/
│   │   ├── __init__.py
│   │   ├── extractor.py
│   │   ├── resolver.py
│   │   ├── whisper_fallback.py
│   │   ├── slug.py
│   │   ├── writer.py
│   │   └── cli.py
│   └── tests/
└── (future)/                 ← spotify/, gmail/, calendar/, rss/, etc.
```

## Per-integration conventions

Each integration subdir is independently:

- **Versioned** — its own `pyproject.toml` (or `package.json` for Node-based integrations).
- **Documented** — its own `README.md` covering install, use, env vars, troubleshooting.
- **Tested** — its own `tests/` directory with pytest (or equivalent runner).
- **Runtime-free** — no shared global state across integrations; each picks its own toolchain.

Shared code lives in `lib/` only. Per-integration code never imports from a sibling integration.

## Output contract (ingest-direction integrations)

Plug-ins that write to the vault's `raw/` MUST produce frontmatter compatible with markdown-vault's `/vault ingest` skill. See `lib/frontmatter_schema.py` for the Pydantic model + `lib/schemas/raw_frontmatter.json` for the language-agnostic JSON Schema.

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

Vault is sovereign. Plug-ins do not require modifications to markdown-vault's `skills/`, `CLAUDE.md`, or `vault_map.md`. If an integration genuinely needs vault-side changes, raise it as a separate issue against `markdown-vault` first; this repo doesn't drive vault changes.

## Coordination across parallel sessions

This repo is worked on by multiple Claude Code sessions in parallel (PC + Macs). Coordination happens via:

1. **Linear** (`tracker` workspace, team OGR) — live task board with session labels (`session:mac-fresh`, `session:mac-older`, `session:pc`, `session:any`).
2. **GitHub Issues** — code-attached closure trail (this repo's Issues tab).
3. **`markdown-vault/_ops/activity-log.md`** — append-only liveness log shared via Obsidian Sync.

See `markdown-vault/_ops/activity-log.md` for the full conventions.

## Lineage

- [markdown-vault](https://github.com/itotallyforgot/markdown-vault) — the standalone vault this overlays onto.
- [vault-retrieval-engine](https://github.com/itotallyforgot/vault-retrieval-engine) — sister plug-in (retrieval) using the same vault-write contract.
