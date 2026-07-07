# Backend Skill — SpeakHan / Mandarin Memory Coach

This document defines how backend code must be written, organized, and committed
in this repository. Any AI tool or contributor generating backend code
(FastAPI + SQLAlchemy + Qwen integration) must follow this skill exactly.
When in doubt, prefer the simpler, more explicit option over a clever one.

---

## 0. Backend handoff summary

### Product summary

SpeakHan / Mandarin Memory Coach is a Qwen-powered Mandarin speaking memory
coach for the MemoryAgent hackathon track. It is not a generic Mandarin
chatbot: it tracks each learner's recurring pronunciation, tone, vocabulary,
grammar, fluency, and hesitation weaknesses across sessions, then adapts later
practice to those memories.

The demo loop is:

1. Learner speaks Mandarin through `/api/v1/voice-chat`.
2. The backend transcribes speech. ASR is fake in `USE_FAKE_QWEN=true` or
   `USE_FAKE_ASR=true`, and real DashScope Qwen ASR in `USE_FAKE_QWEN=false`
   plus `USE_FAKE_ASR=false` when ASR settings are configured.
3. Qwen generates a short tutor reply and structured feedback JSON.
4. The backend saves the session, mistakes, and active weaknesses.
5. The next session retrieves memory and adapts the lesson.

The key demo moment is that the coach can say, in effect: "Welcome back. Last
time you struggled with zh/ch pronunciation and tone accuracy. Let's warm that
up first."

### Current backend architecture

- FastAPI API-only backend.
- SQLite MVP memory database.
- SQLAlchemy ORM models for users, sessions, mistakes, active weaknesses, and
  lesson plans.
- Pydantic schemas and enums for endpoint contracts and Qwen structured output.
- Fake-first Qwen client in `app/services/qwen_client.py`.
- Alibaba Cloud Model Studio OpenAI-compatible chat API for real tutor reply
  and structured feedback.
- DashScope native `MultiModalConversation` API for upload-style
  `qwen3-asr-flash` ASR.
- Local audio storage under `backend/storage/`.
- `memory_service.py` owns DB reads/writes for learner memory.
- `lesson_service.py` owns lesson-plan persistence and defaults.
- `voice_chat_service.py` owns the voice-chat orchestration pipeline.

### Current API endpoints

- `GET /api/v1/health`: returns backend status, project name, fake-Qwen mode,
  and database type.
- `POST /api/v1/voice-chat`: accepts multipart form data with:
  - `audio`: uploaded `.webm`, `.wav`, `.mp3`, or `.m4a` file.
  - `user_id`: learner id, defaulting to demo usage.
  - `scenario`: speaking scenario such as `restaurant ordering`.
  - `level`: learner level such as `HSK1 beginner`.
- `GET /api/v1/memory/{user_id}`: returns active weaknesses, recent sessions,
  and latest lesson plan.
- `GET /api/v1/lesson-plan/{user_id}`: returns the latest lesson plan or a
  starter lesson for new users.

The `/voice-chat` response includes the fake transcript, Qwen tutor reply,
optional tutor audio URL, structured feedback, memory before and after, and a
`memory_updated` flag. `tutor_audio_url` is `null` when fake TTS is enabled and
points to stored tutor audio when optional Qwen/DashScope TTS is configured.

### Current Qwen status

- Real Qwen tutor reply and structured feedback work when
  `USE_FAKE_QWEN=false`.
- The local code uses a combined Qwen turn call for lower latency: one Qwen
  request returns both `tutor_reply` and `feedback`.
- Fake mode remains available for tests and development.
- ASR calls DashScope native Qwen ASR in real mode when ASR settings are
  configured.
- Fake ASR remains available; `transcribe_audio()` returns `我想吃中国菜`.
- TTS is optional. `synthesize_speech()` returns `None` when
  `USE_FAKE_TTS=true`, and can call DashScope CosyVoice TTS v2 when
  `USE_FAKE_TTS=false`.

### Recommended model settings

- Recommended live demo model: `QWEN_CHAT_MODEL=qwen-plus`.
- Manual local testing showed `qwen-plus` completing the full `/voice-chat`
  request in about 7.85 seconds in this environment.
- Fallback model: `qwen3.6-flash`. It completed successfully but took about
  21.76 seconds in this environment.
- Stronger/newer models can be used when latency is less important, but
  `qwen-plus` is recommended for the live demo because it gave the most
  reliable low-latency response in manual testing.
- `qwen3.7-plus` may be slower or less suitable for live demo latency in this
  environment because it timed out during testing.

### Current environment variables

Use placeholders only; never commit real secrets.

```env
USE_FAKE_QWEN=true
USE_FAKE_ASR=true
USE_FAKE_TTS=true
QWEN_API_KEY=
DASHSCOPE_API_KEY=
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_CHAT_MODEL=qwen-plus
QWEN_ASR_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
QWEN_ASR_MODEL=qwen3-asr-flash
QWEN_ASR_LANGUAGE=zh
QWEN_ASR_ENABLE_LID=true
QWEN_ASR_ENABLE_ITN=false
QWEN_ASR_AUDIO_REF_MODE=s3_url
QWEN_ASR_REQUEST_TIMEOUT_SECONDS=30
QWEN_ASR_MAX_RETRIES=0
QWEN_TTS_MODEL=cosyvoice-v3-plus
QWEN_TTS_VOICE=longanyang
QWEN_TTS_BASE_URL=
QWEN_TTS_OUTPUT_FORMAT=mp3
QWEN_REQUEST_TIMEOUT_SECONDS=30
QWEN_MAX_RETRIES=0
QWEN_MAX_TURN_TOKENS=500
QWEN_MAX_TUTOR_TOKENS=180
QWEN_MAX_ANALYSIS_TOKENS=650
MAX_AUDIO_UPLOAD_BYTES=5000000
DATABASE_URL=sqlite:///./memory.db
STORAGE_DIR=./storage
USER_AUDIO_DIR=./storage/user_audio
TUTOR_AUDIO_DIR=./storage/tutor_audio
PUBLIC_BACKEND_BASE_URL=
ALIBABA_OSS_ACCESS_KEY_ID=
ALIBABA_OSS_ACCESS_KEY_SECRET=
ALIBABA_OSS_ENDPOINT=
ALIBABA_OSS_BUCKET=
ALIBABA_OSS_PUBLIC_BASE_URL=
ALIBABA_OSS_PREFIX=speechan/audio/
ALIBABA_OSS_SIGNED_URL_EXPIRES_SECONDS=900
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_ENDPOINT_URL=
S3_BUCKET=
S3_REGION=auto
S3_PUBLIC_BASE_URL=
S3_PREFIX=speechan/audio/
S3_SIGNED_URL_EXPIRES_SECONDS=900
```

### Local run instructions

```bash
cd backend
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --port 8000
```

API docs are available at:

```text
http://localhost:8000/docs
```

### Manual test command

```bash
printf "fake audio" > sample.webm

time curl -s -X POST http://localhost:8000/api/v1/voice-chat \
  -F "audio=@sample.webm;type=audio/webm" \
  -F "user_id=demo-user-latency-test" \
  -F "scenario=restaurant ordering" \
  -F "level=HSK1 beginner"
```

Expected:

- real audio transcript from Qwen ASR when real mode and ASR settings are enabled
- fake transcript `我想吃中国菜` when fake mode is enabled
- tutor reply from Qwen when real mode is enabled
- feedback JSON from Qwen when real mode is enabled
- memory updates
- `tutor_audio_url=null` when `USE_FAKE_TTS=true`
- `tutor_audio_url=/storage/tutor_audio/...` when optional TTS is configured

### Testing

```bash
cd backend
python3 -m pytest
```

Automated tests must not call live Qwen. Keep live Qwen checks manual.

### Engineering rules quick reference

- Keep route files thin.
- Put orchestration and business logic in services.
- Put Qwen calls only in `app/services/qwen_client.py`.
- Keep `QWEN_BASE_URL` for OpenAI-compatible chat and `QWEN_ASR_BASE_URL` for
  DashScope native ASR overrides.
- Alibaba OSS remains the intended final provider for real-ASR demos.
  `QWEN_ASR_AUDIO_REF_MODE=s3_url` is a temporary Cloudflare R2 fallback while
  OSS setup is blocked. Qwen's server-side ASR fetcher accepted stable HTTPS
  URLs but rejected ngrok public URLs with `Missing Content-Length of multimodal
  url`.
- Put DB logic in `memory_service.py` and `lesson_service.py`.
- Use explicit Pydantic `response_model` schemas for every endpoint.
- Keep fake-first external dependencies working.
- Never commit `.env`, API keys, SQLite DB files, generated audio, or storage
  artifacts.
- Never log API keys or secrets.
- Keep tests non-live.

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
      oss_audio_service.py         # Alibaba OSS audio upload/signing for ASR. No DB access here.
      s3_audio_service.py          # Temporary S3/R2 audio upload/signing for ASR. No DB access here.
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
