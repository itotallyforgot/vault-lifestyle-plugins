<!--
PR title format: `[OGR-N] <conventional-commit-subject>`
Linear auto-links + auto-closes OGR-N on merge.
-->

## Summary

<!-- 1-3 bullets: what changed and why -->
-

## Linear

- Closes OGR-N
- Slice plan reference: `second-brain/_ops/2026-05-04-youtube-ingester-plan.md` § Slice N (if applicable)
- Spec reference: `second-brain/_ops/2026-05-04-youtube-ingester-spec.md` (if applicable)

## Verify

<!-- Match the slice's verify line from the plan doc. Paste the actual command + observed output. -->

```
$ <command>
<output excerpt>
```

## Test plan

- [ ] Unit tests added/updated; `pytest <subdir>/tests/` green
- [ ] Manual smoke test (when applicable; cite which case)
- [ ] No regressions in sibling subdirs (`pytest` from repo root)
- [ ] Linter clean (`ruff check`, `ruff format --check`)
- [ ] Frontmatter validates against `lib/schemas/raw_frontmatter.json` (for raw/-writing changes)

## Risks / open questions

<!-- Anything that should block merge or warrant a follow-up issue. None is OK; explicitly say so. -->

🤖 Generated with [Claude Code](https://claude.com/claude-code)
