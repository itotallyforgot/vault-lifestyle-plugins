# Issue Tracker: Linear

Work for this repo lives in Linear.

## Linear Workspace

- Workspace: `tracker`
- Team: `OGR` / `tracker`
- Project: `vault-lifestyle-plugins`
- Issue IDs: `OGR-N`, for example `ISSUE-N`

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
linear-cli issues get ISSUE-N
linear-cli issues start ISSUE-N
linear-cli issues comment ISSUE-N --body "PR opened: https://github.com/..."
linear-cli issues close ISSUE-N
```

## Workflow

1. Read the relevant Linear issue before editing.
2. Start or claim the Linear issue before implementation when possible.
3. Create a branch using the repo convention, normally
   `codex/OGR-N-short-slug` for Codex-created work.
4. Open a GitHub PR and add the PR link plus verification notes back to Linear.
5. When the PR is merged, close the Linear issue and delete the merged branch.

Keep this compatible with the broader workflow in `CONTRIBUTING.md`.
