# ADR-0003: Per-Integration Auth

## Status

Accepted

## Context

- Some integrations read public sources and need no authentication.
- Private-source and action integrations may need OAuth or service-specific
  credentials.
- A central auth broker would couple unrelated integrations and add repo-wide
  secret-handling risk.

## Decision

Each integration owns its auth flow, local config, and credential storage.

- Public-source integrations use no auth when possible.
- Private-source integrations use OAuth or the service's required local auth.
- Tokens are stored per integration, under ignored paths such as `.tokens/`.
- Credentials, client secrets, and token files must never be committed.

## Consequences

- Integrations stay independently installable and testable.
- Users configure only the services they install.
- Shared auth helpers may be added later only if multiple integrations converge
  on the same proven pattern.
