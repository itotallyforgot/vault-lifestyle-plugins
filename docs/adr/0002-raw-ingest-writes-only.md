# ADR-0002: Raw Ingest Writes Only

## Status

Accepted

## Context

- The vault separates immutable source material in `raw/` from AI-maintained
  knowledge in `wiki/`.
- The vault's `/vault ingest` skill owns source-to-wiki processing.
- Integration plug-ins collect source material from external services.

## Decision

Ingest-direction plug-ins write only `raw/<slug>.md` source pages in the target
vault.

Required minimum frontmatter:

- `source_url`
- `clipped_at`
- `ingested: false`

The shared `lib/` frontmatter model and JSON Schema define the raw-page
contract for integrations.

Action-direction plug-ins do not write vault content. They act on external
services.

## Consequences

- Source capture and knowledge synthesis stay separate.
- Integrations cannot bypass vault ingestion rules.
- Non-Python integrations should use the JSON Schema contract instead of
  re-deriving the raw frontmatter shape.
