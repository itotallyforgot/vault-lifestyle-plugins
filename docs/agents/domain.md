# Domain Docs

This is a single-context repo for agent-navigation purposes.

## Read First

Before diagnosing, planning, triaging, or refactoring, read:

- `CONTEXT.md` for domain language and architectural boundaries.
- Relevant ADRs in `docs/adr/`.
- `CONTRIBUTING.md` for repo workflow, Linear/GitHub coordination, branch naming,
  and verification expectations.

## Domain Layout

```text
/
├── CONTEXT.md
├── CONTRIBUTING.md
├── docs/
│   ├── adr/
│   └── agents/
├── lib/
├── youtube/
└── spotify/
```

There is no `CONTEXT-MAP.md`; do not look for separate per-integration context
maps unless one is added later.

## ADR Use

Architectural decisions live under `docs/adr/`. Read the ADRs that touch the
area under work:

- standalone vault boundary
- raw ingest writes only
- per-integration auth
- YouTube bulk staging handoff

If a proposed change conflicts with an ADR, surface that conflict explicitly
before editing.

## Vocabulary Discipline

Use the terms from `CONTEXT.md` in issue titles, PR descriptions, tests, and
architecture notes. In particular:

- `vault`
- `standalone vault`
- `plug-in`
- `integration`
- `ingest plug-in`
- `action plug-in`
- `raw ingest`
- `shared lib`
- `per-integration runtime`

The most important boundary: this repo writes source material into the target
vault's `raw/`; the target vault owns `wiki/` writes and final knowledge
processing.
