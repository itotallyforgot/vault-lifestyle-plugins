# Issue Tracker: Linear

Work for this repo lives in Linear.

## Linear Workspace

- Workspace: `ogre-labs`
- Team: `OGR` / `Ogre-labs`
- Project: `vault-lifestyle-plugins`
- Issue IDs: `OGR-N`, for example `OGR-87`

Use `linear-cli` when authenticated. Prefer Linear for planning, ownership,
status, and task comments.

## GitHub Relationship

Code lives on GitHub at:

```text
https://github.com/itotallyforgot/vault-lifestyle-plugins
```

Pull requests are opened on GitHub and should reference the Linear issue ID in
the title, branch, commit, PR body, or Linear comment.

GitHub Issues may exist as code-attached closure history, but Linear is the
source of truth for active work.

## Common Commands

```bash
linear-cli issues list --filter project.name=vault-lifestyle-plugins
linear-cli issues get OGR-87
linear-cli issues start OGR-87
linear-cli issues comment OGR-87 --body "PR opened: https://github.com/..."
linear-cli issues close OGR-87
```

## Workflow

1. Read the relevant Linear issue before editing.
2. Start or claim the Linear issue before implementation when possible.
3. Create a branch using the repo convention, normally
   `codex/OGR-N-short-slug` for Codex-created work.
4. Open a GitHub PR and add the PR link plus verification notes back to Linear.
5. When the PR is merged, close the Linear issue and delete the merged branch.

Keep this compatible with the broader workflow in `CONTRIBUTING.md`.
