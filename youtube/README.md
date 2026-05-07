# vault-yt: YouTube Transcript Ingester

`vault-yt` takes a YouTube URL, gets a transcript, and writes one
vault-compatible file under `<vault>/raw/`. The existing `/vault ingest`
flow picks that raw file up later.

The package prefers yt-dlp captions. When captions are unavailable or
empty, it falls back to local Whisper. Use `--force-whisper` to skip
captions. Captions and Whisper language hinting default to English; pass
`--transcript-language` to request another language.

## Install

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
<vault>/raw/<youtube-id>-<sanitized-title>.md
```

Re-running the same URL is idempotent. If the matching raw file already
exists, the command prints `existing: <path>` and exits without rewriting.
Use `--force` to overwrite.

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
```

`--whisper-model` defaults to `VAULT_YT_WHISPER_MODEL`, then `base`.
Models larger than `small` are rejected by design.

`--transcript-language` defaults to `en`. The selected language is used
for caption selection and as the Whisper language hint.

`--dry-run` resolves the vault, fetches the transcript, builds the raw
content, and prints the target path plus the start of the file without
writing.

## Output

The generated frontmatter includes the fields the vault expects:

```yaml
source_url: "https://youtu.be/<id>"
source_kind: youtube
clipped_at: "YYYY-MM-DDTHH:MM:SSZ"
transcript_source: yt-dlp
ingested: false
ingested_at: null
wiki_page: null
tags: [youtube]
```

Whisper output uses `transcript_source: whisper-base`,
`whisper-tiny`, or `whisper-small`.

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
