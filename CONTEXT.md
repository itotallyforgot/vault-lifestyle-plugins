# Repo Context

Agent-readable domain map for `vault-lifestyle-plugins`.

## Purpose

This repo holds optional lifestyle integration plug-ins for a `second-brain`
vault. The target vault remains standalone; these plug-ins overlay capability
onto it when installed.

## Domain Language

| Term | Meaning |
|---|---|
| vault | A `second-brain`-shaped Obsidian knowledge vault. It owns `raw/`, `wiki/`, vault skills, and vault-side processing rules. |
| standalone vault | The rule that `second-brain` must work without this repo or any other plug-in installed. |
| plug-in | An independently installable repo or subproject that adds capability to a target vault. |
| integration | One service-specific plug-in directory, such as `youtube/`, `spotify/`, `gmail/`, or `rss/`. |
| ingest plug-in | An integration that reads an external source and writes a source page into the vault's `raw/`. |
| action plug-in | An integration that acts on an external service for the user, such as email triage or calendar updates. Action plug-ins do not write vault content. |
| raw ingest | The ingest-direction write path: create `raw/<slug>.md` with frontmatter compatible with the vault's `/vault ingest` skill and `ingested: false`. |
| shared lib | The umbrella `lib/` package with shared vault helpers and frontmatter validation. It is shared infrastructure, not an integration runtime. |
| per-integration runtime | Each integration owns its toolchain, dependencies, tests, docs, and credential handling. Python, Node, or another runtime may be chosen per integration. |

## Boundaries

- `second-brain` is sovereign. This repo does not require changes to
  `second-brain` skills, maps, or harness config.
- Ingest integrations write only to the target vault's `raw/`.
- The target vault's `/vault ingest` skill is the writer for `wiki/`.
- Action integrations act on external services and do not touch the vault.
- Shared code belongs in `lib/`. Integration code must not import from sibling
  integrations.
- Credentials are owned per integration and stay out of git.

## Decision Log

Architectural decisions live in `docs/adr/`.

Start with:

- `docs/adr/0001-standalone-vault-overlay.md`
- `docs/adr/0002-raw-ingest-writes-only.md`
- `docs/adr/0003-per-integration-auth.md`
