# Coding standards — Git workflow

Conventions for branches, commits, and pull requests in this repository.

## Branch naming

Use lowercase, hyphen-separated slugs. Prefix with a category so history and automation stay readable.

| Prefix      | Use for |
|------------|---------|
| `feat/` | New behaviour or user-facing capability |
| `fix/`     | Bug fixes |
| `chore/`   | Tooling, deps, config, refactors with no user-visible change |
| `docs/`    | Documentation only |
| `test/`    | Test-only changes (large additions or infra) |

**Pattern:** `<prefix>/<short-description>`

**Examples:**

- `feat/prescription-image-upload`
- `fix/reminder-timezone`
- `chore/bump-supabase-cli`
- `docs/auth-testing-guide`

Avoid vague names like `feat/update` or personal branches like `john/wip`.

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/) so logs and changelogs stay consistent.

**Format:**

```text
<type>(<optional scope>): <short description in imperative mood>

[optional body]

[optional footer(s)]
```

**Common types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`.

**Rules:**

- Use the imperative mood (“add”, “fix”, not “added”, “fixes”).
- Keep the first line about 72 characters or less.
- Put **why** in the body when the change is not obvious from the title.
- Reference issues or tickets in the footer when applicable, e.g. `Closes #12`.

**Examples:**

```text
feat(auth): validate JWT on protected routes

fix(reminders): use user timezone for next fire time

docs: link CODING_STANDARDS from README

chore: pin pydantic to 2.x in requirements
```

## Pull requests

**Before opening**

- Branch is up to date with the target branch (usually `main`) where practical.
- Commits tell a coherent story; squash locally if the branch is noisy.
- Tests and linters pass for the areas you touched.

**Title**

- Prefer the same spirit as Conventional Commits: clear type + scope or area.
- Example: `feat: add prescription OCR pipeline` or `fix: handle empty VLM response`.

**Description**

Include enough context for a reviewer who did not pair with you:

- **What** changed (short summary).
- **Why** (problem, goal, or ticket).
- **How to verify** (commands, manual steps, or “N/A” for docs-only).

**Scope and etiquette**

- Prefer smaller PRs; split large work when it can land independently.
- Link related issues (`Closes #…`, `Refs #…`).
- Request review when ready; respond to feedback or mark threads resolved when addressed.
