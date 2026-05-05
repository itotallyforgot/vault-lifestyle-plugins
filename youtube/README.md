# vault-yt — YouTube transcript ingester

On-demand CLI that takes a YouTube URL, fetches a transcript (captions
first, Whisper fallback), and deposits a vault-compatible
`raw/<slug>.md` for the unchanged `/vault ingest` skill to consume.

> **MVP — Slice 2 of 6.** This README is a stub. Full install + usage
> docs land in Slice 5 (OGR-9) when the CLI is wired up. Today the
> package ships only the `extractor` module — the yt-dlp wrapper that
> later slices build on.

## Status

| Slice | Module | Issue | Status |
|---|---|---|---|
| 2 | `extractor` (yt-dlp meta + captions + audio download) | OGR-6 | **this slice** |
| 3 | `whisper_fallback` + `resolver` | OGR-7 | next |
| 4 | `slug` + `writer` | OGR-8 | follows |
| 5 | `cli` + idempotency | OGR-9 | follows |
| 6 | CI + standards via `ogre:repo` | OGR-10 | follows |

## What's importable today

```python
from vault_yt.extractor import (
    ExtractorError,
    fetch_meta,        # url → metadata dict (id, title, channel, captions, ...)
    fetch_captions,    # url, lang → plain transcript text or None
    download_audio,    # url, dest_dir → Path to audio file (Whisper input)
)
```

See `src/vault_yt/extractor.py` for signatures and
`tests/test_extractor.py` for usage examples.
