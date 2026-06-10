# YouTube Private Playlist Handoff Runbook

This runbook proves the private-playlist workflow without adding OAuth to
`vault-yt` core.

The boundary is:

```text
authenticated local resolver -> handoff JSONL -> vault-yt batch ingest -> run report
```

`vault-yt` may use yt-dlp browser/cookie access to export playlist membership,
but raw ingest only consumes handoff metadata and video URLs.

For the adapter-author contract behind this flow, see
`docs/youtube-handoff-adapter-contract.md`.

## Safety Rules

- Browser cookies and cookie files are account secrets.
- Do not commit cookie files.
- Do not store cookie files in the vault.
- Do not paste cookies into prompts, logs, manifests, or Linear comments.
- Treat handoff files as private metadata: they can reveal playlist membership,
  but must not contain tokens, cookies, API keys, or refresh tokens.

## 1. Export Playlist Membership

Use a browser profile already authenticated to YouTube:

```bash
uv --directory youtube run vault-yt \
  --export-playlist "https://www.youtube.com/playlist?list=<playlist-id>" \
  --browser "firefox" \
  --output /tmp/engineering-handoff.jsonl
```

Browser specs follow yt-dlp's style:

```text
BROWSER[+KEYRING][:PROFILE][::CONTAINER]
```

Examples:

```bash
--browser "firefox"
--browser "chrome:Default"
--browser "brave:Profile 1::youtube"
--browser "chrome+kwallet:Default"
```

Alternatively, use a Netscape-format cookie file:

```bash
uv --directory youtube run vault-yt \
  --export-playlist "https://www.youtube.com/playlist?list=<playlist-id>" \
  --cookies /path/to/cookies.txt \
  --output /tmp/engineering-handoff.jsonl
```

## 2. Validate The Handoff

```bash
uv --directory youtube run vault-yt \
  --validate-handoff /tmp/engineering-handoff.jsonl
```

Expected success:

```text
handoff valid: /tmp/engineering-handoff.jsonl (<n> records)
```

If validation fails, fix the reported line before ingesting.

## 3. Process A Small Parcel

Start with a small limit:

```bash
uv --directory youtube run vault-yt \
  --handoff /tmp/engineering-handoff.jsonl \
  --run-id engineering-$(date +%Y-%m-%d) \
  --limit 3 \
  --vault /path/to/markdown-vault
```

This writes raw pages under:

```text
<vault>/raw/
```

And records progress under:

```text
<vault>/.vault-lifestyle/youtube/runs/<run-id>/manifest.json
```

## 4. Resume The Run

```bash
uv --directory youtube run vault-yt \
  --handoff /tmp/engineering-handoff.jsonl \
  --run-id engineering-YYYY-MM-DD \
  --resume \
  --limit 10 \
  --vault /path/to/markdown-vault
```

## 5. Review The Run

```bash
uv --directory youtube run vault-yt \
  --report \
  --run-id engineering-YYYY-MM-DD \
  --vault /path/to/markdown-vault
```

Use the report to inspect written, skipped, pending, and failed videos before
adding candidate findings or asking vault-side tooling to process the raw pages.

## Smoke Test Without Private Access

Use the checked-in example handoff file:

```bash
uv --directory youtube run vault-yt \
  --validate-handoff youtube/examples/engineering-handoff.jsonl
```

This confirms schema and parser wiring without touching YouTube, browser
cookies, or a vault.
