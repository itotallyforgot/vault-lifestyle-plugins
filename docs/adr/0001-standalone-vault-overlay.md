# ADR-0001: Standalone Vault Overlay

## Status

Accepted

## Context

- `second-brain` is intended to work as a standalone Obsidian vault.
- Lifestyle integrations add useful automation, but not every adopter wants
  every integration.
- Vault-side skills, maps, and harness config must remain owned by the vault.

## Decision

Keep `vault-lifestyle-plugins` as an optional overlay repo.

- The vault must not depend on this repo.
- Each plug-in is opt-in.
- Plug-in plumbing that exists only for an integration lives in this repo or the
  integration's own package.
- If an integration needs vault-side changes, raise a separate `second-brain`
  issue first.

## Consequences

- The vault remains portable and usable without lifestyle plug-ins.
- Integrations can evolve without forcing vault migrations.
- Cross-repo behavior must be documented at the boundary, not hidden in vault
  internals.
