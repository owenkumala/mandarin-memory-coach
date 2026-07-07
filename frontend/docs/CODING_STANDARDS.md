# Coding Standards - Git Workflow

Conventions for branches, commits, and pull requests in this repository.

This repository is used by multiple contributors and AI coding agents. To avoid
clashes between backend and frontend work, nobody should push directly to `main`
unless explicitly agreed.

---

## 1. Main Branch Rule

`main` should always stay runnable.

Do not commit directly to `main` for normal feature work.

Use a branch for:

- frontend work
- backend work
- docs changes
- bug fixes
- AI/Codex-generated changes

Only merge into `main` after the change has been reviewed or approved.

---

## 2. Branch Naming

Use lowercase, hyphen-separated slugs. Prefix with a category so history stays
readable.

| Prefix | Use for |
| --- | --- |
| `feat/` | New behaviour or user-facing capability |
| `fix/` | Bug fixes |
| `chore/` | Tooling, dependencies, config, refactors with no user-visible change |
| `docs/` | Documentation only |
| `test/` | Test-only changes |
| `ci/` | CI/CD or GitHub Actions changes |

Pattern:

```text
<prefix>/<short-description>
```

Examples for this project:

```text
feat/frontend-mvp
feat/practice-recording-page
feat/memory-dashboard
feat/browser-tutor-tts
fix/weakness-status-semantics
fix/voice-chat-error-state
docs/frontend-skill
docs/backend-deployment-guide
chore/frontend-tailwind-setup
```

Avoid vague names:

```text
feat/update
fix/stuff
frontend
owen/wip
john/test
```

---

## 3. Recommended Branch Workflow

Before starting work:

```bash
git checkout main
git pull origin main
git checkout -b feat/frontend-mvp
```

During work, if `main` changes:

```bash
git fetch origin
git rebase origin/main
```

After committing:

```bash
git push -u origin feat/frontend-mvp
```

Then open a Pull Request into `main`.

---

## 4. Frontend Contributor Rule

Frontend contributors should normally work only inside:

```text
frontend/
```

They should not edit backend files unless coordinated.

Frontend work should use branches such as:

```text
feat/frontend-mvp
feat/practice-page
feat/memory-dashboard
fix/record-button-permission-error
```

Frontend contributors must not commit:

```text
frontend/.env.local
node_modules/
.next/
dist/
build/
```

Frontend environment variables should be copied from:

```text
frontend/.env.example
```

Local example:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Do not hardcode backend URLs inside React components.

---

## 5. Backend Contributor Rule

Backend contributors should normally work inside:

```text
backend/
```

Backend work should use branches such as:

```text
fix/weakness-status-semantics
feat/qwen-tts
fix/asr-storage-url
docs/alibaba-deployment-proof
```

Backend contributors must not commit:

```text
backend/.env
*.db
backend/storage/
uploaded audio files
API keys
cloud credentials
```

Any change involving Qwen, Alibaba OSS, Cloudflare R2, or secrets must be
checked carefully before committing.

---

## 6. AI / Codex Workflow

AI-generated code must follow the same Git rules as human contributors.

Unless explicitly instructed otherwise, Codex or any AI agent should:

1. Read the relevant skill document first.
2. Make the smallest safe change.
3. Run tests or relevant verification commands.
4. Commit locally only.
5. Show changed files, test result, commit SHA, and git status.
6. Ask for permission before pushing.

Required final question from Codex:

```text
Does this look correct? Do I have permission to push?
```

AI agents must not commit secrets, `.env` files, local database files, storage
files, or generated audio.

---

## 7. Commit Messages

Follow Conventional Commits so logs and changelogs stay consistent.

Format:

```text
<type>(<optional scope>): <short description in imperative mood>

[optional body]

[optional footer(s)]
```

Common types:

```text
feat
fix
docs
style
refactor
test
chore
ci
perf
```

Rules:

- Use imperative mood: "add", "fix", "update", not "added" or "fixes".
- Keep the first line around 72 characters or less.
- Put the reason in the body when the change is not obvious.
- Reference issues in the footer when applicable, e.g. `Closes #12`.

Good examples:

```text
feat(frontend): add SpeakHan MVP interface

feat(practice): add audio recording flow

feat(memory): show active weaknesses dashboard

fix(backend): improve weakness status semantics

fix(api): preserve scenario spacing in lesson plans

docs(frontend): define frontend implementation skill

chore(frontend): configure Tailwind and TypeScript
```

Bad examples:

```text
update

fix stuff

frontend changes

wip

done
```

---

## 8. Pull Requests

### Before Opening A PR

Make sure:

- Branch is up to date with `main` where practical.
- Commits tell a coherent story.
- No secrets or local generated files are included.
- Tests, typecheck, lint, or relevant manual checks pass for the area touched.

Useful checks:

Backend:

```bash
cd backend
python3 -m pytest
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

If a command does not exist yet, mention that in the PR description.

---

## 9. Pull Request Title

Use the same style as commit messages.

Examples:

```text
feat(frontend): add practice recording page

feat(memory): add learner memory dashboard

fix(backend): improve repeated weakness status

docs: add frontend implementation skill
```

---

## 10. Pull Request Description

Every PR should include:

```md
## What changed

Short summary of the change.

## Why

Why this change was needed.

## How to verify

Exact commands or manual steps.

## Notes

Anything the reviewer should know.
```

Example:

```md
## What changed

Added the frontend practice page with audio recording, voice-chat upload,
transcript display, tutor reply display, mistake cards, and memory summary.

## Why

The hackathon demo needs to show the full SpeakHan loop:
record audio -> Qwen transcript -> tutor feedback -> memory update.

## How to verify

1. Start backend:
   `cd backend && python3 -m uvicorn app.main:app --reload --port 8000`

2. Start frontend:
   `cd frontend && npm run dev`

3. Open `/practice`.

4. Record Mandarin audio and submit.

5. Confirm transcript, tutor reply, feedback, and memory update appear.

## Notes

Browser TTS is used for tutor voice playback because backend Qwen TTS is not
implemented yet.
```

---

## 11. Scope And Etiquette

Prefer small PRs.

Good:

```text
PR 1: docs(frontend): add frontend skill
PR 2: chore(frontend): initialize Next.js app
PR 3: feat(practice): add recording and voice-chat flow
PR 4: feat(memory): add memory dashboard
```

Bad:

```text
One huge PR containing frontend setup, backend changes, deployment config,
random refactors, and README rewrite.
```

If a frontend PR needs backend changes, mention it clearly and coordinate first.

---

## 12. Merge Rule

Before merging to `main`, confirm:

- The PR does not include secrets.
- The app still runs.
- The touched area was tested or manually verified.
- The PR scope is understandable.
- The branch can be safely deleted after merge.

After merging:

```bash
git checkout main
git pull origin main
git branch -d <branch-name>
```

For frontend contributors starting fresh:

```bash
git checkout main
git pull origin main
git checkout -b feat/frontend-mvp
```

Then work in `frontend/`, push that branch, and open a PR.
