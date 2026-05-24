# Auditing a new tool before release

This doc is the developer-facing checklist for adding a new tool to
`vault-lifestyle-plugins`. "Tool" here means any new entry point that
crosses a trust boundary — see [`attack-surface-manifest.md`](./attack-surface-manifest.md)
§"Scope" for the working definition.

Use this checklist before the PR that introduces the tool merges. Every
high-risk surface needs at least one documented misuse case. Low-risk
surfaces still need the manifest row so the staleness check passes.

## The checklist

### 1. Identify the entry point and direction

- Where does the user (or another tool) invoke this?
  - CLI subcommand on an existing Typer app? Note the parent app + the
    `@app.command(...)` registration.
  - Brand-new console script in `[project.scripts]`? Note the
    `pyproject.toml` change.
  - Importable function exposed to other code? Note the public symbol.
  - HTTP route or MCP tool? Note the route/tool name and the server.
- Direction: does it INGEST (external → vault) or ACT (vault → external)
  or BOTH? Match the repo's `[direction]` taxonomy in `CONTEXT.md`.

### 2. Fill in every field in the manifest contract

Each tool gets a section in `attack-surface-manifest.md` with this exact
shape:

```markdown
## tool-name (plugin: <plugin>)

| Field | Value |
|---|---|
| Entry point | `module.path:function_name` or HTTP route |
| Direction | ingest / act / bidir |
| Inputs | typed list, each marked trusted/untrusted |
| Auth assumptions | API key / OAuth / cookie / none |
| Side effects | file writes / external POSTs / state mutation |
| Filesystem access | paths read/written; vault / cache / user home |
| Network access | outbound destinations; retries; timeouts; caps |
| Trust boundary | what untrusted data enters, where it ends up |
| Lethal-trifecta exposure | yes/no + which legs |
| Safe test payload | example that exercises the surface safely |
| Misuse / abuse cases | bullet list with severity tags |
```

Fill every row. If a field genuinely doesn't apply (e.g. "Network access:
none"), say so explicitly — empty rows are not honesty.

### 3. Check trust boundaries

Trace untrusted data from entry to exit:

- What is the trust source for every input? (User shell, file on disk,
  remote API, another tool's output?)
- Where does each input end up? (Vault page body, frontmatter value,
  manifest JSON, log line, outbound request body?)
- Is there a serialization or validation layer between input and output?
  Name it. (Pydantic, yaml.safe_dump, allow-list check, regex.)

Honesty check: if you write "trust boundary: parse-only" but the function
calls into yt-dlp or spotipy, those libraries are downstream trust
boundaries — name them.

### 4. Check the lethal-trifecta composition

[[lethal-trifecta]] composes when one call touches all three of:

- **Private data** — user credentials, tokens, refresh tokens, browser
  cookies, listening history, private playlist contents, vault contents
  that aren't already public.
- **Untrusted input** — user-supplied URLs, third-party API responses,
  external-tool output, untrusted file contents.
- **Exfil vector** — outbound HTTP, file write to a shared location,
  log line that flows to an external aggregator, vault write that gets
  rendered in a browser-loaded preview.

If a tool composes all three in the same call: **flag P0**, expand the
misuse section, and consider whether the composition can be broken (e.g.
by splitting the tool into two stages with the privileged step taking
trusted-only input).

If a tool composes two of three: not the trifecta, but document the
composition explicitly in the manifest's "Lethal-trifecta exposure" row.
A future tool that adds the missing leg in the same trust scope re-forms
the trifecta — the manifest is the place to catch that.

### 5. Define at least one safe test payload

The test payload must:

- Exercise the surface (not a no-op).
- Not exfiltrate real data (use a public URL, a tmp vault, `--dry-run`,
  or a test double).
- Be re-runnable by another reviewer on a clean machine.

For tools that *can* be exercised offline, prefer that. For tools that
require network egress, prefer well-known public test fixtures
(`youtu.be/dQw4w9WgXcQ`, Spotify's developer demo app, etc.).

### 6. Document misuse and abuse cases

For every tool that crosses a trust boundary:

- At least one misuse case ("what if the user passes X?").
- For high-risk surfaces (P0 or P1), at least one abuse case ("what if
  an attacker controls X?").

Format each case as: brief scenario → mitigation status → severity tag.
Severity vocabulary in the manifest header.

If a tool genuinely has no misuse risk (read-only public API call, pure
function with no I/O), say so honestly. The acceptance criterion in ISSUE-N
is "do not invent risks" — empty manifest rows that say "none" are honest.
Filled rows that fabricate misuse to look thorough are not.

### 7. Add the tool to `attack-surface-manifest.md`

- Choose the correct top-level section (`vault-yt`, `vault-spotify`,
  `lib/`, `MCP server surface`).
- Use the contract shape above. Match the table column widths used in
  surrounding entries for readability — pandoc-style markdown tables.
- Keep the section heading short and stable (no trailing emoji, no
  punctuation that breaks anchor links).

### 8. Run the staleness check

```bash
uv --directory lib run pytest tests/test_manifest_coverage.py
```

The check discovers every `[project.scripts]` entry in the monorepo
(`youtube/pyproject.toml`, `spotify/pyproject.toml`, and any future
sibling plug-in) and asserts each script name appears as a heading in
`docs/attack-surface-manifest.md`. New console scripts that ship without
a manifest entry fail the test.

Note: the check is scoped to **console scripts** (the externally exposed
surface). Internal Typer subcommands and importable APIs are not auto-
discovered — the human auditor still has to follow steps 1-6 for those.
The check is a floor, not a ceiling.

To skip the staleness check during local dev:

```bash
uv --directory lib run pytest --ignore=tests/test_manifest_coverage.py
```

CI does not skip it.

### 9. Open a security-review ticket if the tool has P0/P1 risk

If the manifest section ended up with any P0 or P1 misuse cases:

- Open a follow-up Linear ticket tagged `security-review`.
- Include the manifest section as the ticket body.
- Link the PR that introduced the tool.

Do not block the PR on the security review — the manifest is the
durable artifact; the ticket schedules the deep dive.

## Composing previously isolated tools

The trifecta can form across tool boundaries. When you introduce a new
caller that chains two existing tools (e.g. a future cron that runs
`vault-spotify recent` and pipes the output into a yet-unbuilt
`vault-gmail` action), re-audit the composition:

- Does the chain pass private data from tool A to tool B?
- Does tool B accept untrusted input (any input it didn't generate
  itself counts)?
- Does the chain have an exfil channel (HTTP egress, file write to a
  shared location)?

If yes to all three, the *chain* composes the trifecta even if neither
tool does in isolation. Add a manifest row for the composing tool (the
cron, the orchestrator) — that's where the new trust boundary lives.

## When this checklist applies

- New console script in any `*/pyproject.toml`.
- New Typer subcommand on `vault-yt` or `vault-spotify`.
- New importable function that performs I/O, network, or
  credential-handling.
- New HTTP route or MCP server tool.
- New caller that chains two existing tools in a way that changes the
  trust profile (see "Composing previously isolated tools" above).

## When this checklist does not apply

- Pure refactors that move code around without changing inputs / outputs
  / side effects.
- Test-only code under `*/tests/`.
- Documentation-only changes.

If you're unsure whether a change needs an audit, run the staleness check
first — if it passes, the new code didn't add a console script, which is
the cheapest gate. Then read the diff against the criteria in step 1: if
any of the four entry-point kinds applies, run the full checklist.
