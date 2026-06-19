# ADR-0005: Bulk Enumerators Are Count-Verified and Fail Closed

## Status

Accepted

## Context

A bulk enumerator is any tool that resolves a remote collection (a YouTube
playlist, a Spotify listening history, a channel, a saved list) into a local
set of work items. These tools share a failure mode that is dangerous
*because the result looks clean*:

- **Failure masquerading as empty.** The YouTube exporter ran yt-dlp with
  `ignoreerrors: "only_download"`, so a failed/private resolve raised nothing,
  produced zero entries, wrote an empty handoff, and the CLI printed
  `handoff written` and exited `0`. An empty result is indistinguishable from
  an empty collection unless the count is checked. `0 new` could silently mean
  `export failed` — the original defect this ADR exists to prevent.
- **Silent pagination truncation.** A partial enumeration just looks like
  "fewer items." YouTube returns playlists in date-added-ascending order, so
  the **newest additions live at the tail** — a truncated fetch drops exactly
  the items a "what's new?" diff is hunting, then reports "nothing new."

Both produce a confident, clean-looking result that is wrong. This bites the
playlist-diff workflow (`docs/youtube-playlist-diff-runbook.md`) directly and
would bite any future enumerator (`vault-spotify recent`, a channel importer)
the same way.

## Decision

**A bulk enumerator must verify its output against the source's authoritative
total and fail closed. Empty or partial is never reported as success.**

Concretely, every enumerator must:

1. **Verify against the authoritative total.** Capture the count the source
   itself reports (yt-dlp `playlist_count`; a REST `total` field) and require
   the number of items paged to equal it. Do not infer completeness from the
   result alone. For YouTube, use `playlist_count`, never `n_entries` (which is
   `None` in flat-extract mode).
2. **Never self-truncate a full enumeration.** A full export must not pass
   `--limit` / `playlistend` / a page cap as a stop condition. Per-request page
   size (e.g. Spotify's 50-item max) is not a stop condition; follow pagination
   to exhaustion.
3. **Fail closed on any incomplete or failed resolve.** A failed/empty resolve,
   a missing authoritative count, or a paged-total that does not match the
   authoritative total must raise and exit non-zero — never write an
   empty/partial artifact and exit `0`.
4. **Record the counts so downstream can assert.** Emit `expected_count`,
   `actual_count`, and `complete` alongside the artifact (a sidecar, the run
   manifest) so the next stage can re-check rather than trust.
5. **Dedupe by canonical id.** Within one source and across a multi-source
   sweep, dedupe by the stable id (YouTube 11-char `video_id`, Spotify track
   URI). `actual_count` (resolved items) may be below the enumerated total when
   members are deleted/private; that gap is expected and must NOT trip the
   completeness gate, which compares **enumerated items** to the authoritative
   total.

### Instances

- **`vault-yt --export-playlist`** (`youtube/src/vault_yt/ytdlp_playlist_exporter.py`).
  Captures `playlist_count`; raises `PlaylistEnumerationError` on failed
  resolve, missing count, or `enumerated != playlist_count`; writes a
  `<output>.meta.json` sidecar with `expected_count` / `enumerated_count` /
  `actual_count` / `complete`. The CLI exits `11` (enumeration incomplete) and
  never prints `handoff written` on failure. This ADR is the rule that fix
  enforces.
- **`vault-spotify recent`** (deferred). Not yet built; bound by this
  ADR in advance. The recently-played endpoint is cursor-paginated with **no
  `total`**, so completeness is "follow `next` to exhaustion and raise on any
  mid-walk error," not a count equality. The `--limit 50` default is a page
  size, not a stop condition. See the implementer note in
  `spotify/src/vault_spotify/cli.py`.

## Consequences

- An empty/partial result from a bulk enumerator is now an error, not a silent
  "nothing found." Operators can distinguish "genuinely empty" from "the export
  failed."
- The completeness check is the enumerator's job, not the operator's. The
  manual count check in the playlist-diff runbook (step 2) becomes a
  belt-and-suspenders cross-check rather than the only guard.
- The handoff-adapter contract's "fail closed" clause now binds the built-in
  exporter, not only third-party adapters (see
  `docs/youtube-handoff-adapter-contract.md`).
- `docs/auditing-a-new-tool.md` gains a standing audit question: "does this
  tool fail closed on an incomplete enumeration, or can it report empty as
  success?"
- A genuinely empty collection (authoritative count `0`, zero items) is
  complete and is reported normally — the gate is `enumerated == total`, which
  `0 == 0` satisfies.

### Residual limitations (documented, not defended in code)

- **Authoritative count is itself source-derived.** For YouTube, `playlist_count`
  is scraped from the playlist page header, independently of pagination, so it
  normally catches truncation. In the narrow case where the header count is
  unparseable *and* the paged walk is truncated, yt-dlp can fall back to the
  exhausted walk length, making `enumerated == playlist_count` trivially true and
  letting a truncated export pass. Likelihood is low (the header count is almost
  always present). The manual completeness cross-check in
  `docs/youtube-playlist-diff-runbook.md` (step 2 — compare `wc -l` to the
  `Downloading item N of M` total) remains the belt-and-suspenders for the
  highest-stakes sweeps.
- **A complete enumeration can resolve to zero usable videos** when every member
  is private/deleted (`expected_count > 0`, `actual_count == 0`). This is a valid
  empty export, not a failure; the CLI surfaces it with a warning so it is not
  mistaken for healthy output.
