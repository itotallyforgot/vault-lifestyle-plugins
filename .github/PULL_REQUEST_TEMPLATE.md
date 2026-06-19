<!--
PR title: use the Conventional Commit subject, e.g. `fix(youtube): ...`.
Link any related GitHub issue below.
-->

## Summary

<!-- 1-3 bullets: what changed and why -->
-

## Related issue

<!-- e.g. Closes #123, or "none" -->
-

## Verify

<!-- Paste the actual command + observed output that proves the change works. -->

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
