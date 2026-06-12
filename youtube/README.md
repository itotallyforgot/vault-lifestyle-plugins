# vault-yt: YouTube Transcript Ingester

`vault-yt` takes a YouTube URL, gets a transcript, and writes one
vault-compatible file under `<vault>/raw/`. The existing `/vault ingest`
flow picks that raw file up later.

The package prefers yt-dlp captions. When captions are unavailable or
empty, it falls back to local Whisper. Use `--force-whisper` to skip
captions. Captions and Whisper language hinting default to English; pass
`--transcript-language` to request another language.

## Install

Requires Python >= 3.12.

From the repo root, with uv:

```bash
uv --directory youtube sync --extra whisper
uv --directory youtube run vault-yt --help
```

For captions-only use:

```bash
uv --directory youtube sync
uv --directory youtube run vault-yt --help
```

With pip in an active virtual environment:

```bash
pip install -e ./lib -e "./youtube[whisper]"
```

Omit `[whisper]` for captions-only installs.

## Use

Pass the vault path explicitly:

```bash
uv --directory youtube run vault-yt "https://youtu.be/<id>" --vault /path/to/markdown-vault
```

Request captions or Whisper transcripts in another language:

```bash
uv --directory youtube run vault-yt "https://youtu.be/<id>" --vault /path/to/markdown-vault --transcript-language fr
```

Or set `VAULT_PATH`:

```bash
export VAULT_PATH=/path/to/markdown-vault
uv --directory youtube run vault-yt "https://youtu.be/<id>"
```

The CLI writes:

```text
<vault>/raw/<yyyy-mm-dd>-youtube-<youtube-id>-<sanitized-title>.md
```

The date prefix uses YouTube's published date when available. If YouTube
does not provide one, `vault-yt` falls back to the ingest date.

Re-running the same URL is idempotent. If the matching raw file already
exists, the command prints `existing: <path>` and exits without rewriting.
Use `--force` to overwrite.

Bulk ingest runs use a staging manifest rather than writing directly to
`wiki/`. The default manifest location is:

```text
<vault>/.vault-lifestyle/youtube/runs/<run-id>/manifest.json
```

The manifest records per-video status, raw file paths, transcript source,
errors, and downstream finding/verification handoff state. The vault's own
ingest flow remains responsible for accepting findings into `wiki/`.

## Flags

```text
vault-yt URL
  --vault PATH
  --force
  --force-whisper
  --whisper-model tiny|base|small
  --transcript-language LANG
  --verbose
  --dry-run
  --url-file PATH
  --playlist URL
  --handoff PATH
  --validate-handoff PATH
  --export-playlist URL
  --output PATH
  --browser BROWSER[+KEYRING][:PROFILE][::CONTAINER]
  --cookies PATH
  --limit N
  --run-id ID
  --resume
```

`--whisper-model` defaults to `VAULT_YT_WHISPER_MODEL`, then `base`.
Models larger than `small` are rejected by design.

`--transcript-language` defaults to `en`. The selected language is used
for caption selection and as the Whisper language hint.

`--dry-run` resolves the vault, fetches the transcript, builds the raw
content, and prints the target path plus the start of the file without
writing.

For batch parcels, omit the positional `URL` and pass `--url-file` or
`--playlist`:

```bash
uv --directory youtube run vault-yt --url-file engineering.txt --limit 5 --vault /path/to/markdown-vault
uv --directory youtube run vault-yt --playlist "https://www.youtube.com/playlist?list=<id>" --limit 3 --vault /path/to/markdown-vault
```

Authenticated/private playlist access should stay outside the core ingest path.
Use an external handoff JSONL file when another trusted tool, MCP, CLI, or
browser-cookie exporter has already resolved the playlist into video work
items:

```jsonl
{"video_id":"abc123","url":"https://youtu.be/abc123","title":"Example","source_provider":"youtube-mcp","playlist_title":"Engineering","playlist_index":1}
```

Then process it through the same staging manifest pipeline:

```bash
uv --directory youtube run vault-yt --handoff engineering.jsonl --run-id engineering-001 --limit 5 --vault /path/to/markdown-vault
```

Validate a handoff file without a vault:

```bash
uv --directory youtube run vault-yt --validate-handoff engineering.jsonl
```

The record schema is documented in
`youtube/schemas/youtube_handoff.schema.json`, with a checked example in
`youtube/examples/engineering-handoff.jsonl`.

Adapter authors should follow the MCP/CLI/browser handoff contract in
`docs/youtube-handoff-adapter-contract.md`.

For local, explicit cookie/browser export, `vault-yt` can ask yt-dlp to resolve
the playlist and write the handoff file without ingesting transcripts:

```bash
uv --directory youtube run vault-yt --export-playlist "https://www.youtube.com/playlist?list=<id>" \
  --browser "firefox" --output engineering.jsonl
```

`--browser` accepts yt-dlp-style browser specs:
`BROWSER[+KEYRING][:PROFILE][::CONTAINER]`, such as `firefox`,
`chrome:Default`, or `brave:Profile 1::youtube`. You can also pass a
Netscape-format cookie file:

```bash
uv --directory youtube run vault-yt --export-playlist "https://www.youtube.com/playlist?list=<id>" \
  --cookies /path/to/cookies.txt --output engineering.jsonl
```

Treat browser cookies and cookie files as account secrets. Do not commit them,
paste them into prompts, or store them in the vault. The handoff file contains
private playlist membership metadata, but not auth credentials.

For an end-to-end operator flow, see
`docs/youtube-private-playlist-runbook.md`.

Use `--run-id` to make the staging manifest name stable and `--resume` to
continue a previous run. `--dry-run` expands the inputs and prints how many
videos would be processed without fetching transcripts or writing a manifest.

Candidate findings and verification evidence are manifest handoff data. They
do not write `wiki/`; vault-side ingest decides what becomes accepted
knowledge.

Attach a candidate finding:

```bash
uv --directory youtube run vault-yt --add-finding --run-id eng-001 --video-id <id> \
  --claim "Important claim" --transcript-span "00:01:00.000 --> 00:01:08.000" \
  --confidence 0.8 --vault /path/to/markdown-vault
```

Attach verification evidence:

```bash
uv --directory youtube run vault-yt --add-evidence --run-id eng-001 \
  --video-id <id> --finding-id <id>-finding-1 \
  --evidence-url "https://example.com/source" --verifier "Alex" \
  --verification-result accepted --vault /path/to/markdown-vault
```

Print an operator report:

```bash
uv --directory youtube run vault-yt --report --run-id eng-001 --vault /path/to/markdown-vault
```

## Output

The generated frontmatter includes the fields the vault expects:

```yaml
source_url: "https://youtu.be/<id>"
source_kind: youtube
clipped_at: "YYYY-MM-DDTHH:MM:SSZ"
transcript_source: yt-dlp-manual
ingested: false
ingested_at: null
wiki_page: null
tags: [youtube]
```

Batch/handoff runs add provenance when available:

```yaml
youtube_video_id: "<id>"
canonical_url: "https://youtu.be/<id>"
bulk_run_id: "engineering-001"
source_provider: youtube-mcp
playlist_id: PL...
playlist_title: Engineering
playlist_url: "https://www.youtube.com/playlist?list=..."
playlist_index: 1
```

Caption output uses `transcript_source: yt-dlp-manual` for human-authored
subtitles or `yt-dlp-auto` for auto-generated ones. Whisper output uses
`transcript_source: whisper-base`, `whisper-tiny`, or `whisper-small`.

## Exit Codes

| Code | Meaning |
|---:|---|
| 0 | Success, dry run, or idempotent no-op |
| 2 | Malformed URL |
| 3 | Vault path could not be resolved |
| 4 | `<vault>/raw/` is missing or not writable |
| 5 | yt-dlp extraction failed after one retry for network failures |
| 6 | Whisper is needed but unavailable |
| 7 | Whisper model load or transcription failed |
| 8 | Final transcript is empty |
| 9 | Slug collision with a different `source_url` |
| 10 | Generated frontmatter failed validation |

## Troubleshooting

No captions and no Whisper:

```bash
uv --directory youtube sync --extra whisper
```

Whisper model download is slow on a new machine. After the model is
cached, later runs reuse the local cache.

VRAM pressure on a gaming PC: keep the default `base` model, or use
`--whisper-model tiny`. The CLI will not run `medium` or larger models.

Mac to PC flow: run `vault-yt` on the Mac against the local synced vault.
Obsidian Sync can move the raw file to the PC. The vault's own ingest and
indexing flow stays separate.
