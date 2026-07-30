# YouTube Playlist Diff Runbook — detecting new videos vs the vault

Given a YouTube playlist, produce the list of videos **not yet captured**
in the vault — reliably, without silently missing the newest additions.

This is the step that runs *before* the export → handoff → ingest flow in
`docs/youtube-private-playlist-runbook.md`. That runbook ingests a handoff;
this one decides *what is new and worth ingesting*.

## Why this runbook exists

Two failure modes make a naive "list the playlist, diff the ids" wrong. Both
produce a confident, clean-looking result that is actually incomplete.

1. **Pagination truncation.** A partial enumeration just looks like "fewer
   videos." YouTube returns a default playlist in **date-added ascending**
   order, so the **newest additions live at the tail** (highest index). A
   truncated fetch drops the tail first — i.e. exactly the videos you are
   hunting. The diff then reports "nothing new" while the new videos were
   never fetched.

2. **Failure masquerading as empty.** `vault-yt --export-playlist` swallows
   yt-dlp resolve errors and, on failure, writes an **empty** handoff and
   **exits 0** (`handoff written`). An empty export is indistinguishable from
   "empty playlist" unless you check. `0 new` can mean `export failed`. See
   **Known gap** below.

The defense for both is one rule: **verify the count before you trust the
diff** (step 2).

A secondary point is **ordering**. "New" is ambiguous between *recently added
to the playlist* and *never ingested*. Define it operationally as a
set-difference by `video_id`, then sort by `playlist_index` descending so the
recently-added tail surfaces first. See **Ordering reference**.

## 0. Prereqs

- Playlist URL or `list=` id. **You do not need to ask the user for it** —
  if you have their cookies you can resolve a playlist by name yourself
  (step 0a).
- A cookie source if the playlist is private/unlisted (most personal
  playlists are; `availability` comes back `private`). On this Mac the
  logged-in browser is **Brave** → `--browser brave`. Treat cookies as
  account secrets — see the safety rules in
  `docs/youtube-private-playlist-runbook.md`.
- The plugin venv: run via `uv --directory youtube run vault-yt ...` or the
  built console script at `youtube/.venv/bin/vault-yt`.

## 0a. Resolve a playlist id by name (authenticated)

The authenticated `feed/playlists` endpoint lists **all** of the account's
playlists, public and private. Use it to map a name → `list=` id instead of
asking — names the user gives are often paraphrased (e.g. "Cloud / DevOps"
vs the real title "Engineering / DevOps / Cloud").

```bash
youtube/.venv/bin/python - <<'PY' 2>/dev/null
from yt_dlp import YoutubeDL
opts={"extract_flat":True,"quiet":True,"no_warnings":True,"skip_download":True,
      "cookiesfrombrowser":("brave",None,None,None)}
with YoutubeDL(opts) as ydl:
    info=ydl.sanitize_info(ydl.extract_info("https://www.youtube.com/feed/playlists",download=False))
for e in (info.get("entries") or []):
    if isinstance(e,dict) and e.get("id"):
        print(e["id"], "\t", e.get("title"))
PY
```

Match the user's phrase against the title list (case-insensitive,
word-order-tolerant). Known ids: `Engineering - AI` =
`PLn7D0_HUBsRAhCElFtaKQPpGN_UDHw7Ev`, `Engineering / DevOps / Cloud` =
`PLn7D0_HUBsRAoDbrcxIl1bdJTzRbCVvHG`.

## 1. Export full membership

```bash
uv --directory youtube run vault-yt \
  --export-playlist "https://www.youtube.com/playlist?list=<id>" \
  --browser brave \
  --output /tmp/<name>-export.jsonl \
  --verbose
```

- **Do not pass `--limit` here.** `--limit` bounds *ingest*, not *export*;
  the exporter always enumerates the whole playlist. Capping the export is
  how you reintroduce failure mode #1 by hand.
- `--verbose` makes yt-dlp print `Downloading item N of M` — `M` is the true
  total you will check against in step 2.

## 2. Verify completeness — THE pagination guard

The authoritative total is yt-dlp's `playlist_count`. It reports the **true**
total even when the fetch is capped (verified: a `playlistend:5` fetch still
reports `playlist_count = 166`). Do **not** use `n_entries` — it is `None` in
flat-extract mode.

The export is trustworthy only if **all** of these hold:

- `wc -l <output.jsonl>` equals `M` from `Downloading item N of M`.
- The file is non-empty.
- No `The playlist does not exist` / auth / cookie errors scrolled by.

If any fail, **enumeration is incomplete — stop. Do not diff.** Re-run with
valid cookies / the right `--browser`. An empty file plus exit 0 is **not**
an empty playlist.

```bash
wc -l /tmp/<name>-export.jsonl   # must equal M
```

Note: `playlist_count` counts **records**, not distinct videos. A playlist
can contain the same video twice, so `unique video_ids <= playlist_count` is
normal and fine — the completeness gate is `records == playlist_count`; the
diff dedupes by `video_id` separately. When diffing **multiple** playlists in
one sweep, dedupe the combined NEW set across playlists too (the same video
often sits in several playlists).

## 3. Build the "already have" set

`video_id` is the canonical 11-char YouTube id. A video counts as already
captured if it appears in **either** source of truth:

- `raw/` filenames: `YYYY-MM-DD-youtube-<id>-<slug>.md`
- run manifests: `.vault-lifestyle/youtube/runs/*/manifest.json` (`video_id`)

```bash
VAULT=/path/to/vault
{ ls "$VAULT/raw" | grep youtube \
    | sed -E 's/^[0-9]{4}-[0-9]{2}-[0-9]{2}-youtube-([A-Za-z0-9_-]{11})-.*/\1/'
  grep -rhoE '"video_id": "[A-Za-z0-9_-]{11}"' "$VAULT/.vault-lifestyle/youtube/runs/" \
    | sed -E 's/.*"([A-Za-z0-9_-]{11})".*/\1/'
} | sort -u > /tmp/have_ids.txt
wc -l /tmp/have_ids.txt
```

## 4. Diff, ordered newest-added first

```bash
python3 - /tmp/<name>-export.jsonl /tmp/have_ids.txt <<'PY'
import json, sys
export, have_file = sys.argv[1], sys.argv[2]
have = set(open(have_file).read().split())
rows = [json.loads(l) for l in open(export) if l.strip()]
seen, uniq = set(), []
for r in rows:                       # dedupe by video_id, keep first
    if r["video_id"] not in seen:
        seen.add(r["video_id"]); uniq.append(r)
new = [r for r in uniq if r["video_id"] not in have]
new.sort(key=lambda r: -(r.get("playlist_index") or 0))   # newest-added first
print(f"playlist={len(uniq)} have-hits={len(uniq)-len(new)} NEW={len(new)}")
for r in new:
    print(f"  #{r.get('playlist_index'):>3}  {r['video_id']}  {(r.get('title') or '')[:70]}")
PY
```

`NEW` = in the playlist, not yet captured. That set mixes two things:

- **Recently added** — a contiguous block of high indices that are all new
  (the tail). This is "added since the last sweep."
- **Never-ingested backlog** — new videos scattered at lower indices, present
  in the playlist for a while but never pulled in.

If the user only wants "added since last sweep," report the contiguous
high-index tail. If they want "everything not in the vault," report all of
`NEW`. When unsure, show both and let them gate.

## 5. Present, gate, ingest

Present `NEW` (index · id · title), get the user's approved subset, then hand
the approved ids to the ingest flow in
`docs/youtube-private-playlist-runbook.md` §3 (handoff → `vault-yt --handoff`
→ raw pages), and finish with vault-side `/vault ingest`.

## Ordering reference

- Default YouTube playlist order is **date added ascending**; new additions
  append at the end, so **highest `playlist_index` = most recently added**.
- `playlist_index` is reliable from this exporter (it came back `1..N`
  monotonic). In pure flat-extract mode `playlist_index` can be `None`; the
  exporter then falls back to enumeration position, which is the same order.
  Either way the **last** record is the newest-added.
- Caveat: if the playlist is manually reordered, or the user sorted it by
  "date published," index no longer equals add-order. The set-difference is
  still correct for "not yet captured"; only the *recency* interpretation
  breaks. Fall back to set-difference and say so.

## Known gap — exporter honesty bug (as of 2026-06-18)

`vault-yt --export-playlist` does not fail closed, which is why step 2 is
manual:

- `export_playlist_handoff` runs yt-dlp with `ignoreerrors:"only_download"`,
  so a failed resolve (private playlist with no/expired cookies →
  `The playlist does not exist`) raises nothing, yields 0 entries, writes an
  empty handoff, and `_export_playlist` prints `handoff written` and exits 0.
- It never compares records written to `playlist_count`, so a mid-playlist
  pagination truncation is also silent.

Both violate the adapter contract in
`docs/youtube-handoff-adapter-contract.md` ("Exit non-zero if playlist
enumeration is incomplete" / "Adapters should fail closed").

**Proposed fix** (until then, run step 2 by hand): in
`export_playlist_handoff`, capture `info["playlist_count"]`, and raise when
the resolve errored, when 0 records are written for a playlist that reports a
non-zero count, or when `len(records) != playlist_count`. `_export_playlist`
exits non-zero on that error instead of printing `handoff written`. Add a
`playlist_count` / `complete` field to the run so downstream can assert it.
