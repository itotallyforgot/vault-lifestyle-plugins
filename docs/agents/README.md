# Agent Metadata

This repo does not commit a root `AGENTS.md` or `CLAUDE.md` today. Codex receives
the shared vault agent instructions through the injected global AGENTS entry for
`/Users/ogre/Projects/vault-lifestyle-plugins`, which imports:

```text
/Users/ogre/Projects/Second-Brain/.Codex/Codex-global.md
```

Keep repo-specific skill metadata in this directory so skills such as
`to-issues`, `triage`, `diagnose`, `tdd`, and architecture review can discover
tracker, triage, and domain-doc conventions without guessing.

If this repo later needs committed root instructions, add an `## Agent skills`
block to that file and point it at these docs:

```markdown
## Agent skills

### Issue tracker

Work is tracked in Linear team OGR, project `vault-lifestyle-plugins`. See
`docs/agents/issue-tracker.md`.

### Triage labels

Linear statuses are authoritative; no repo-specific triage labels are configured
yet. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo: read `CONTEXT.md` and relevant ADRs in `docs/adr/`. See
`docs/agents/domain.md`.
```
