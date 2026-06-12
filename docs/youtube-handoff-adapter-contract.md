# YouTube Handoff Adapter Contract

This contract is for tools that resolve YouTube videos outside `vault-yt` and
then hand those videos to the local ingest pipeline.

The adapter boundary is intentionally narrow:

```text
YouTube-aware adapter -> handoff JSONL -> vault-yt validation -> vault-yt batch ingest
```

Adapters may be MCP servers, harness tools, local CLIs, browser exporters, or
manual scripts. They may use OAuth, browser cookies, API keys, or an already
authenticated browser session internally. They must not pass credentials to
`vault-yt`.

## Responsibilities

### Adapter Owns

- Authenticated YouTube access, if needed.
- Playlist, channel, search, or saved-list enumeration.
- Pagination and retry behavior for the source system.
- Emitting newline-delimited JSON records in the handoff schema.
- Keeping credential material out of files, logs, prompts, and manifests.

### `vault-yt` Owns

- Validating the handoff file shape before ingest.
- Collapsing duplicate videos by YouTube video ID.
- Preserving all playlist appearances as provenance.
- Fetching transcripts for each selected video.
- Writing raw pages under `<vault>/raw/`.
- Tracking run progress in the staging manifest.
- Reporting pending, written, skipped, failed, and review-needed items.

### Vault-Side Tooling Owns

- Reviewing raw pages and candidate findings.
- Verifying important facts.
- Accepting or rejecting findings as vault knowledge.
- Writing final `wiki/` pages.

## Required Artifact

Adapters write UTF-8 JSONL: one JSON object per line.

```jsonl
{"video_id":"abc123","url":"https://youtu.be/abc123","title":"Example","source_provider":"youtube-mcp","playlist_id":"PLENG","playlist_title":"Engineering","playlist_url":"https://www.youtube.com/playlist?list=PLENG","playlist_index":1}
```

Blank lines and comment lines starting with `#` are allowed. All other lines
must be JSON objects.

The canonical schema is:

```text
youtube/schemas/youtube_handoff.schema.json
```

Validate before ingest:

```bash
uv --directory youtube run vault-yt --validate-handoff /tmp/engineering-handoff.jsonl
```

Expected success:

```text
handoff valid: /tmp/engineering-handoff.jsonl (<n> records)
```

## Record Fields

Each record must include either `video_id` or `url`.

| Field | Required | Type | Notes |
|---|---:|---|---|
| `video_id` | conditional | string | YouTube video ID. Preferred stable identity. |
| `url` | conditional | string URL | Canonical or source YouTube video URL. Host-validated against the YouTube allow-list (even when `video_id` is present) and normalized to `https://youtu.be/<video_id>` on read. |
| `title` | no | string | Title observed by the adapter. `vault-yt` may later replace it with fetched metadata. |
| `source_provider` | no | string | Adapter name, such as `youtube-mcp`, `yt-dlp-browser`, `yt-dlp-cookies`, `claude-code-youtube`, or `manual-export`. |
| `playlist_id` | no | string | YouTube playlist ID, when the source is playlist-like. |
| `playlist_title` | no | string | Human-readable playlist title. |
| `playlist_url` | no | string URL | Source playlist URL. |
| `playlist_index` | no | integer | One-based position within the source playlist. Must be `>= 1`. |
| `channel` | no | string | Channel name if already known. |
| `channel_url` | no | string URL | Channel URL if already known. |

Unknown fields are rejected. Keep adapter-specific metadata in adapter logs, not
in the handoff file, until the schema explicitly supports it.

## Security Rules

Handoff files may reveal private playlist membership. Treat them as private
metadata.

Adapters must never emit:

- OAuth access tokens.
- OAuth refresh tokens.
- Browser cookies.
- Netscape cookie-file content.
- API keys.
- Authorization headers.
- Session IDs.
- Local browser profile paths that reveal machine-specific secrets.
- Private notes unrelated to playlist provenance.

`vault-yt` manifests and raw pages must preserve source provenance without
becoming credential stores. If an adapter needs sensitive state for retries, it
must keep that state outside the vault and outside this repo.

## Adapter Styles

### MCP Adapter

Use this style when the operator's harness already has a YouTube-aware MCP
server.

Minimum behavior:

- Accept a playlist/list identifier from the operator.
- Resolve all videos the authenticated user can see.
- Write a local JSONL handoff file.
- Return the handoff file path and record count to the operator.

Recommended `source_provider`:

```text
youtube-mcp
```

The MCP server should not send credentials through prompts. It should expose a
file artifact or structured tool result containing only handoff records.

### Local CLI Adapter

Use this style when an operator already has a trusted command-line exporter.

Minimum behavior:

- Write JSONL to a path supplied by the operator.
- Exit non-zero if playlist enumeration is incomplete.
- Print only a summary to stdout.

Recommended `source_provider` examples:

```text
yt-dlp-browser
yt-dlp-cookies
custom-youtube-cli
```

The built-in exporter follows this style:

```bash
uv --directory youtube run vault-yt \
  --export-playlist "https://www.youtube.com/playlist?list=<playlist-id>" \
  --browser "firefox" \
  --output /tmp/engineering-handoff.jsonl
```

### Browser Export Adapter

Use this style when playlist membership is easiest to obtain from an already
authenticated browser.

Minimum behavior:

- Run locally in the operator's browser context.
- Extract visible playlist entries and stable video IDs.
- Save JSONL locally.
- Avoid copying cookies or local storage into the JSONL output.

Recommended `source_provider`:

```text
browser-export
```

### Manual Adapter

Use this style for small hand-curated parcels.

Minimum behavior:

- Write records by hand or from a short script.
- Validate before ingest.
- Use a clear `source_provider`, such as `manual-export`.

Manual handoffs are valid as long as they follow the same schema.

## Operator Flow

1. Use the adapter to write a handoff file outside the vault.
2. Validate the handoff file.
3. Process a small parcel with `--limit`.
4. Resume with the same `--run-id`.
5. Review the run report before adding findings or evidence.

```bash
uv --directory youtube run vault-yt \
  --handoff /tmp/engineering-handoff.jsonl \
  --run-id engineering-$(date +%Y-%m-%d) \
  --limit 3 \
  --vault /path/to/Second-Brain
```

```bash
uv --directory youtube run vault-yt \
  --report \
  --run-id engineering-YYYY-MM-DD \
  --vault /path/to/Second-Brain
```

## Failure Semantics

Adapters should fail closed. If they cannot enumerate a playlist completely,
they should not emit a partial file unless the output clearly represents an
operator-approved parcel.

`vault-yt --validate-handoff` fails if:

- A line is malformed JSON.
- A non-comment line is not a JSON object.
- A record omits both `video_id` and a parseable YouTube `url`.
- A record carries a `url` whose host is not in the YouTube allow-list
  (`youtube.com`, `m.youtube.com`, `music.youtube.com`, `youtu.be`). The `url`
  is validated through `inputs._parse_youtube_input` **even when a `video_id`
  is also present**, so a record cannot smuggle a non-YouTube url past the
  ingest leg.
- A field has the wrong type.
- `playlist_index` is below `1`.
- A record contains an unknown field.

Batch ingest can still fail later if transcript extraction fails for a valid
video. Those failures belong in the staging manifest and can be retried with
`--resume`.

## Compatibility Notes

- Record ordering matters. Adapters should emit source order.
- Duplicate videos are allowed. First-seen order wins; later appearances are
  preserved in manifest provenance.
- The handoff file is an input artifact, not a vault document.
- `vault-yt` does not require adapter authors to use the built-in exporter.
- Adding a new optional field requires updating the schema, parser, docs, and
  tests together.
