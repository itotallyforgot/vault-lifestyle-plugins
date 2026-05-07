# Architecture Decision Records

Short decision records for `vault-lifestyle-plugins`.

## When To Record A Decision

Write an ADR when a choice changes repo boundaries, vault interaction, auth,
data ownership, integration runtime, shared library contracts, or anything
future agents are likely to otherwise re-litigate.

Do not write ADRs for obvious implementation details or one-off local fixes.

## Format

- Number files sequentially: `0001-short-title.md`.
- Keep status explicit: `Accepted`, `Superseded`, or `Deprecated`.
- Prefer bullets over narrative.
- Link a superseding ADR instead of deleting old context.

## Index

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-standalone-vault-overlay.md) | Accepted | This repo overlays optional plug-ins onto a standalone vault. |
| [0002](0002-raw-ingest-writes-only.md) | Accepted | Ingest plug-ins write raw source pages only; wiki writes stay vault-owned. |
| [0003](0003-per-integration-auth.md) | Accepted | Each integration owns its auth and credentials. |
