# ADR-0004: YouTube Bulk Staging Handoff

## Status

Accepted

## Context

- `vault-yt` currently captures one YouTube video transcript into `raw/`.
- Desired workflows include playlists and URL batches processed in small,
  resumable parcels.
- Desired downstream behavior includes candidate findings and fact
  verification before knowledge enters `wiki/`.
- ADR-0002 keeps `wiki/` writes owned by the target vault's `/vault ingest`
  flow, not by plug-ins.

## Decision

YouTube bulk ingest uses a two-part handoff:

- `vault-yt` expands inputs, captures transcripts, writes `raw/` source pages,
  and maintains a staging manifest for each run.
- The target vault consumes raw pages and manifest handoff data through
  vault-side ingest/review flows before any candidate finding becomes wiki
  knowledge.

The staging manifest is operational state, not vault knowledge. It records run
progress, per-video status, raw paths, source URLs, errors, candidate finding
state, and verification evidence state.

Candidate findings and verification evidence are handoff data. They may be
embedded in raw pages or referenced by a manifest sidecar, but this repo does
not mark them as accepted vault knowledge and does not write `wiki/`.

## Consequences

- Playlist and batch ingestion can resume after interruption.
- Operators can process large inputs in small parcels without losing audit
  state.
- Source capture, candidate finding extraction, verification, and wiki writes
  remain distinguishable.
- The manifest schema becomes a shared contract between `vault-yt` and
  vault-side ingest tooling.
- Future integrations can copy the staging-manifest pattern without weakening
  ADR-0002.
