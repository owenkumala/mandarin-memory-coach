# Backend Skill — SpeakHan (Mandarin Memory Coach)

This document defines how backend code must be written, organized, and committed
in this repository. Any AI tool or contributor generating backend code
(FastAPI + SQLAlchemy + Qwen integration) must follow this skill exactly.
When in doubt, prefer the simpler, more explicit option over a clever one.

---

## 1. Project structure (authoritative — do not deviate)

```
backend/
  app/
    __init__.py
    main.py                      # App factory only: create app, mount middleware/static, include routers. No business logic.

    core/
      __init__.py
      config.py                  # Settings (pydantic-settings). All env vars declared here, nowhere else.

    db/
      __init__.py
      database.py                # Engine, SessionLocal, Base, get_db() dependency. No table definitions here.
      models.py                  # SQLAlchemy ORM models only. No query logic here.

    schemas.py                   # Pydantic request/response models. Every endpoint has an explicit response_model.

    api/
      __init__.py
      v1/
        __init__.py
        router.py                # Aggregates all v1 endpoint routers into one APIRouter.
        endpoints/
          __init__.py
          health.py
          voice_chat.py
          memory.py
          lesson_plan.py

    services/
      __init__.py
      qwen_client.py              # All Qwen API calls (ASR, chat, mistake analysis, TTS). No DB access here.
      memory_service.py           # All DB reads/writes related to memory (users, sessions, mistakes, weaknesses).
      lesson_service.py           # Lesson-plan generation/persistence logic.

    utils/
      __init__.py
      audio.py                    # Pure helper functions (file naming, path handling, format conversion). No FastAPI or DB imports.

  storage/
    user_audio/
    tutor_audio/

  tests/
    test_health.py

  requirements.txt
  .env.example
  .gitignore
```

### Where new code goes (decision rule)

- Talks to the database? -> `services/*_service.py`, using models from `db/models.py`.
- Talks to Qwen / any external API? -> `services/qwen_client.py` (or a new `services/<name>_client.py` if it's a genuinely different external system).
- Defines a request/response shape? -> `schemas.py`.
- Defines a new route? -> `api/v1/endpoints/<feature>.py`, then register it in `api/v1/router.py`.
- Pure logic with no I/O (formatting, parsing, small calculations)? -> `utils/`.
- Settings or environment variables? -> `core/config.py` only. Never read `os.environ` directly elsewhere.

If a change doesn't obviously fit one of these, stop and ask rather than guessing a new location.

---

## 2. Core principles

1. **Routers contain no business logic.** An endpoint function should read: validate/collect input -> call one or more service functions -> return a schema. If a route function is doing calculations, DB queries, or Qwen calls directly, that logic belongs in `services/`.

2. **Every endpoint has an explicit `response_model`.** Never return a raw `dict` from a route. If the shape doesn't exist yet in `schemas.py`, add it before writing the route.

3. **Dependency injection over globals.** Use FastAPI's `Depends(get_db)` for DB sessions. Don't instantiate sessions manually inside route functions.

4. **Async all the way for I/O.** Any function that calls Qwen or does network I/O is `async def`. Functions that only touch SQLAlchemy (sync driver) stay regular `def`, called from async routes — do not fake-await sync DB calls.

5. **Fail loud, fail typed.** Never silently swallow an exception. Wrap external calls (Qwen, file I/O) in `try/except` that raises a specific `HTTPException` with a clear status code and message, not a bare `except: pass`.

6. **No magic strings duplicated across files.** Enum-like values (mistake types, weakness categories, statuses) are defined once — as a Python `Enum` or constant in `schemas.py` — and imported everywhere else. Do not repeat literal strings like `"pronunciation"` across multiple files.

7. **Type hints are mandatory** on every function signature (params and return type), including internal service functions.

8. **Small functions, single responsibility.** If a service function exceeds ~40 lines or does more than one clearly nameable thing, split it.

9. **No secrets in code.** All credentials come from `core/config.py`, sourced from `.env`. `.env` is gitignored; `.env.example` documents required keys with empty values.

10. **Fake-first for external dependencies during development.** New integrations (e.g. real Qwen calls) should be built behind a `use_fake_*` flag in config, matching the existing `qwen_client.py` pattern, so the rest of the app can be tested without live credentials.

---

## 3. Commenting and docstrings (required, not optional)

Every file must be understandable on its own without needing to trace through the rest of the codebase.

- **Every function** gets a one-to-three-line docstring: what it does, what it takes, what it returns. State *why* only when it's not obvious from the code.
- **Every non-trivial block inside a function** gets an inline `#` comment explaining intent — not restating the code, but why this step exists in the pipeline. Example of the expected style:

```python
async def voice_chat(...):
    """
    Full voice-chat pipeline: transcribe audio, generate a tutor reply informed
    by the learner's memory, analyze mistakes, persist everything, and return
    the updated memory state to the frontend.
    """
    # Ensure the learner exists before we attach any session/mistake data to them.
    get_or_create_user(db, user_id=user_id, mandarin_level=level)

    # Save the uploaded audio to disk before sending it to Qwen ASR, so we keep
    # a persistent record even if transcription later fails.
    ...
```

- Avoid comments that just narrate syntax (`# loop over mistakes`). Every comment should answer "why is this here" or "what does this accomplish in the bigger pipeline," since that's what a reviewer or future contributor actually needs.
- Module-level docstring at the top of every file in `services/` and `api/v1/endpoints/` stating the file's single responsibility (1-2 sentences).

---

## 4. Testing

- Test files live in `tests/`, named `test_<feature>.py`, using `pytest`.
- Every new endpoint gets at least one test: the happy path with `use_fake_qwen=True`.
- Service functions with real logic (e.g. `update_active_weaknesses`, weakness normalization) get direct unit tests, not just tests through the HTTP layer.
- Do not commit tests that depend on live Qwen API access — use the fake client for all automated tests.

---

## 5. Error handling conventions

- Route layer: catch expected failure modes and raise `HTTPException(status_code=..., detail=...)` with a message safe to show a client.
- Service layer: raise domain-specific exceptions (or let SQLAlchemy/Qwen client exceptions propagate) — do not construct `HTTPException` inside `services/`, since services shouldn't know about HTTP.
- Never use a bare `except:`. Always catch the narrowest exception type you expect.
- Log the underlying error before converting it into a client-facing message.

---

## 6. Git workflow

*(Matches `CODING_STANDARDS.md` in this repo — restated here so backend code generation follows it automatically.)*

### Branch naming

`<prefix>/<short-description>`, lowercase, hyphen-separated.

| Prefix | Use for |
|---|---|
| `feat/` | New behaviour or user-facing capability |
| `fix/` | Bug fixes |
| `chore/` | Tooling, deps, config, refactors with no user-visible change |
| `docs/` | Documentation only |
| `test/` | Test-only changes |

Examples: `feat/voice-chat-endpoint`, `fix/weakness-dedup-bug`, `chore/split-qwen-client`.

Avoid vague names (`feat/update`) or personal branches (`owen/wip`).

### Commit messages — Conventional Commits

```
<type>(<optional scope>): <short description, imperative mood>

[optional body — the "why", if not obvious]

[optional footer — Closes #12]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`.

Rules:
- Imperative mood ("add", not "added").
- First line under about 72 characters.
- Put reasoning in the body when the change isn't self-explanatory from the title.

Examples:
```
feat(voice-chat): persist mistakes and update weaknesses after each turn

fix(memory): dedupe weakness rows by normalized name

chore(qwen-client): split ASR and TTS into separate methods
```

### Pull requests

**Before opening:** branch up to date with `main`; commits tell a coherent story (squash noisy WIP commits); relevant tests pass.

**Title:** same spirit as commit types — `feat: add lesson-plan generation endpoint`.

**Description must include:**
- **What** changed (short summary).
- **Why** (the problem or goal).
- **How to verify** (exact commands or manual steps — e.g. `uvicorn app.main:app --reload` then `curl .../health`).

**Scope:** prefer small PRs; one feature/fix per PR where practical; link related issues.

---

## 7. Anti-patterns — do not do these

- Returning raw dicts from routes instead of `response_model` schemas.
- Putting SQLAlchemy queries directly inside `api/v1/endpoints/*.py`.
- Reading `os.environ` outside of `core/config.py`.
- String-matching free-text LLM output to infer categories (e.g. checking `"zh" in target.lower()`) — instead, constrain the LLM's output to a fixed enum in the prompt and validate against it.
- Bare `except:` blocks.
- One giant `main.py` or `qwen_client.py` that keeps growing — split by responsibility once a file covers more than one clear concern.
- Committing `.env`, `storage/user_audio/*`, `storage/tutor_audio/*`, or the SQLite `.db` file.
- Vague commits (`fix stuff`, `wip`, `updates`) or vague branch names.

---

## 8. Checklist before committing any backend change

- [ ] New/changed endpoint has a `response_model` in `schemas.py`.
- [ ] Business logic lives in `services/`, not in the route.
- [ ] New functions have docstrings and inline comments explaining intent.
- [ ] No secrets or literal env values committed.
- [ ] Tests added/updated for the change (fake-Qwen mode).
- [ ] Branch name and commit messages follow the conventions in Section 6.
- [ ] PR description includes what / why / how-to-verify.
