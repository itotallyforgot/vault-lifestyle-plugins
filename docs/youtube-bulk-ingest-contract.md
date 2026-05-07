# YouTube Bulk Ingest Contract

Agent-readable contract for OGR-94.

## Goal

Support prompts like:

> Look at my YouTube playlist for engineering, one by one process each video
> into a staging area. Process the transcripts for each and ingest good
> findings into our vault. Do some amount of verification for each important
> fact you ingest.

This repo owns source capture and handoff. The target `second-brain` vault owns
final knowledge synthesis and `wiki/` writes.

## Supported Inputs

`vault-yt` bulk mode resolves all inputs into ordered video work items:

- Single video URL.
- Playlist URL.
- Text file containing one URL per line.

URL files may include blank lines and comment lines starting with `#`.
Malformed entries must be reported with line numbers.

Duplicate videos are collapsed by YouTube video ID. First-seen order wins.
Additional appearances should be preserved as provenance when practical.

## Work Item Shape

Each resolved video work item should include:

- `video_id`: YouTube video ID.
- `url`: canonical video URL, preferably `https://youtu.be/<id>`.
- `title`: title if known from metadata.
- `position`: first-seen zero-based position in the resolved run.
- `input_kind`: `video`, `playlist`, or `url_file`.
- `input_ref`: original URL or file path.
- `playlist_id`: optional playlist ID.
- `playlist_title`: optional playlist title.
- `playlist_url`: optional playlist URL.
- `playlist_index`: optional item index within the playlist.
- `also_seen`: optional list of later duplicate appearances.

## Staging Manifest

Bulk runs write a manifest under a staging area, outside `wiki/`.

Preferred default:

```text
<vault>/.vault-lifestyle/youtube/runs/<run-id>/manifest.json
```

`run-id` should be stable when resuming an explicit run and unique for new
runs. A timestamp plus short hash is acceptable:

```text
2026-05-07T203000Z-youtube-a1b2c3d4
```

Manifest top-level fields:

- `schema_version`: start at `1`.
- `run_id`.
- `source_kind`: `youtube`.
- `created_at`.
- `updated_at`.
- `vault_path`.
- `inputs`: original input descriptors.
- `options`: transcript language, force, force whisper, whisper model, limit.
- `items`: ordered work item records.
- `summary`: status counts.

Per-item fields:

- `video_id`.
- `url`.
- `title`.
- `status`.
- `raw_path`: vault-relative raw path when written or discovered.
- `source_url`: canonical source URL.
- `transcript_source`: `yt-dlp`, `whisper-tiny`, `whisper-base`, or
  `whisper-small` when known.
- `transcript_language`.
- `candidate_findings_state`: `not_requested`, `pending`, `ready`,
  `failed`, or `accepted_by_vault`.
- `verification_state`: `not_requested`, `pending`, `partial`, `complete`,
  or `blocked`.
- `error`: structured error object when failed.
- `attempts`.
- `started_at`.
- `finished_at`.

Per-item `status` values:

- `pending`: discovered but not processed.
- `processing`: actively being processed.
- `raw_written`: transcript raw page was written.
- `skipped_existing`: matching raw page already existed for the same source.
- `failed`: processing failed and can be retried or inspected.
- `needs_attention`: processing completed but operator review is needed.

Manifest writes should be atomic enough that interruption cannot leave invalid
JSON behind.

## Raw Page Handoff Fields

YouTube raw pages keep the shared required fields:

- `source_url`
- `clipped_at`
- `ingested: false`

YouTube bulk/provenance fields should be added when available:

- `source_kind: youtube`
- `youtube_video_id`
- `canonical_url`
- `published_at`
- `channel`
- `channel_url`
- `transcript_source`
- `transcript_language`
- `bulk_run_id`
- `playlist_id`
- `playlist_title`
- `playlist_url`
- `playlist_index`
- `tags: [youtube]`

The transcript body should remain readable. Timestamp anchors may be included
when available, using a stable line format:

```text
[00:01:23.000 --> 00:01:27.500] Transcript text...
```

Plain transcript output remains valid for single-video ingest.

## Candidate Findings Handoff

Candidate findings are not final knowledge. A candidate finding should include:

- `claim`.
- `source_url`.
- `raw_path`.
- `video_id`.
- `transcript_span`: timestamp range or cue index range.
- `confidence`.
- `verification_status: pending`.
- `notes`.

Candidate findings may live in a raw-page section or manifest sidecar, but
they remain handoff data until vault-side tooling accepts them.

Current implementation stores candidate findings on each manifest item:

- `id`: deterministic per video, `<video_id>-finding-<n>`.
- `claim`.
- `source_url`.
- `raw_path`.
- `video_id`.
- `transcript_span`.
- `confidence`.
- `verification_status`.
- `notes`.
- `evidence`: list of verification evidence records.

## Verification Evidence

Important facts should carry evidence before vault-side ingest accepts them.

Verification evidence records should include:

- `claim`.
- `source_span`.
- `evidence_url` or citation.
- `verifier`.
- `checked_at`.
- `result`: `accepted`, `rejected`, `unresolved`, or `conflicting`.
- `notes`.

This repo may collect and record verification evidence. It must not mark the
claim as wiki knowledge.

Current implementation supports manual evidence attachment through the CLI.
`verification_status` is updated from the latest evidence result, and the item
verification state becomes `pending`, `partial`, or `complete` based on all
candidate findings for that video.

## Example: Single Video

```text
vault-yt "https://youtu.be/dQw4w9WgXcQ" --vault ~/Vault
```

Writes one raw page:

```text
raw/2009-10-25-youtube-dQw4w9WgXcQ-never-gonna-give-you-up.md
```

No manifest is required for the existing single-video command.

## Example: URL File Parcel

```text
vault-yt batch --url-file engineering.txt --limit 5 --vault ~/Vault
```

Creates or resumes a staging manifest, processes up to five pending videos,
writes raw pages, and records per-item status.

## Example: Playlist Parcel

```text
vault-yt batch --playlist "https://www.youtube.com/playlist?list=..." --limit 3 --vault ~/Vault
```

Expands playlist entries, collapses duplicates by video ID, processes three
pending items, and records playlist provenance for each raw page.
