# Triage Labels

Linear statuses are authoritative for this repo. The current Linear workspace
does not have a repo-specific triage label vocabulary configured.

When a skill asks for one of the canonical triage roles, use the status or note
below rather than inventing new labels.

| Canonical role | Current Linear representation | Meaning |
|---|---|---|
| `needs-triage` | `Backlog` | Maintainer has not committed to active work yet. |
| `needs-info` | Comment on the issue and leave it in its current state. | Waiting on reporter or owner for clarification. |
| `ready-for-agent` | `Backlog` with a complete description and acceptance criteria. | An agent can pick it up without extra human context. |
| `ready-for-human` | Comment explicitly that human judgment or credentials are needed. | Needs human implementation, decision, or access. |
| `wontfix` | Close the issue with an explanatory comment. | Will not be actioned. |

Do not create Linear labels just to satisfy these roles unless the user asks for
a label taxonomy. If labels are added later, update this table with the exact
configured label names.
