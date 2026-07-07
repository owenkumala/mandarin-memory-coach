# Frontend Skill - SpeakHan / Mandarin Memory Coach

This document defines how frontend code must be written, organized, reviewed,
and committed in this repository. Any AI tool or contributor generating
frontend code for SpeakHan must follow this skill exactly.

Frontend stack:

- Next.js App Router
- TypeScript
- Tailwind CSS
- Browser MediaRecorder API for recording learner audio
- Browser Web Speech API for temporary tutor voice playback
- React

When in doubt, prefer the simpler, more explicit option over a clever one.

---

## 0. Product-Specific Frontend Goal

SpeakHan is not a generic chatbot UI.

The frontend exists to demonstrate the MemoryAgent behavior clearly:

1. Learner records Mandarin audio.
2. Backend sends audio to real Qwen ASR.
3. Backend returns transcript.
4. Backend returns Qwen tutor reply and structured feedback.
5. Backend updates learner memory.
6. Frontend shows `memory_before` and `memory_after` so judges can see the
   agent remembers recurring weaknesses.
7. Frontend speaks the tutor reply aloud using browser TTS.

The most important demo moment is that the same `user_id` carries memory across
sessions.

Example demo flow:

1. First session: learner says `呃，请问我可以点菜了吗？`
2. Backend detects hesitation `呃`.
3. Backend stores hesitation as a weakness.
4. Second session with the same `user_id`: learner says `呃，我要一份宫保鸡丁。`
5. Frontend shows `memory_before` already contains hesitation weakness.
6. Backend increments `times_failed`.
7. Frontend shows updated drill in `memory_after`.

The UI must make this memory behavior obvious.

---

## 1. Project Structure

Use this structure unless the existing frontend already has a clearly different
setup.

```txt
frontend/
  app/
    layout.tsx
    page.tsx
    globals.css
    practice/page.tsx
    memory/page.tsx

  components/
    ui/
    practice/
    memory/

  hooks/
  lib/
    api/
    audio/
    speech/
    format/
  types/
  public/
```

### File Responsibilities

- `app/`: routes and page composition only. Pages should assemble components
  and pass props. Pages should not contain large business logic.
- `components/ui/`: small reusable UI primitives that do not know about
  SpeakHan-specific API data.
- `components/practice/`: recording, transcript, tutor reply, feedback, and
  voice-chat result components.
- `components/memory/`: active weakness list, memory comparison, recent
  sessions, and next lesson components.
- `hooks/`: focused stateful logic such as `useAudioRecorder`,
  `useVoiceChat`, `useTutorSpeech`, and `useMemory`.
- `lib/api/`: all backend API calls. Components must never call `fetch()`
  directly.
- `lib/audio/`: browser audio helper logic with no React rendering.
- `lib/speech/`: browser TTS helper logic.
- `lib/format/`: pure display helpers.
- `types/api.ts`: TypeScript types mirroring backend Pydantic schemas exactly.

If backend `schemas.py` changes, update `types/api.ts` in the same PR.

---

## 2. Backend API Contract

Frontend talks to the FastAPI backend.

The backend base URL must come from:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Do not hardcode `http://localhost:8000` inside components. Do not include
`/api/v1` in `NEXT_PUBLIC_API_BASE_URL` if the API client appends `/api/v1`.

### `POST /api/v1/voice-chat`

Main frontend endpoint.

Request type: `multipart/form-data`

Fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `audio` | `File` or `Blob` | yes | Filename must end in `.webm`, `.mp3`, `.wav`, or `.m4a` |
| `user_id` | `string` | yes | Same user ID is required for memory continuity |
| `scenario` | `string` | yes | Example: `restaurant ordering` |
| `level` | `string` | yes | Example: `HSK1 beginner` |

Demo defaults:

```txt
user_id=demo-user-asr-test-2
scenario=restaurant ordering
level=HSK1 beginner
```

### `GET /api/v1/memory/{user_id}`

Returns current memory for a learner. Frontend uses this for the memory
dashboard.

### `GET /api/v1/lesson-plan/{user_id}`

Returns latest lesson plan or a starter lesson.

### `GET /api/v1/health`

Checks backend health. Use this only for diagnostics or a simple backend status
indicator.

---

## 3. TypeScript API Types

Types must mirror backend Pydantic schemas exactly.

Use snake_case field names if backend returns snake_case. Do not rename backend
fields inside API types. Display components may format labels, but raw API data
should remain faithful to the backend.

The canonical frontend API type file is `types/api.ts`.

---

## 4. API Client Rules

Components must never call `fetch()` directly. All backend calls go through
`lib/api/`.

`lib/api/client.ts` responsibilities:

- read `NEXT_PUBLIC_API_BASE_URL`
- append `/api/v1`
- centralize error handling
- throw typed `ApiError`
- parse JSON safely

Rules:

- Do not expose raw stack traces to users.
- Non-2xx responses must throw `ApiError`.
- API functions return typed data.
- API functions do not render UI.

---

## 5. Audio Recording Rules

Use the browser `MediaRecorder` API. Prefer `audio/webm` and upload with the
filename `recording.webm`.

Rules:

- Recording logic belongs in `lib/audio/recorder.ts` and/or
  `useAudioRecorder.ts`.
- UI components must not manually manage raw `MediaRecorder` internals.
- Stop all media tracks after recording.
- Do not allow overlapping `MediaRecorder` instances.
- Handle microphone permission denial clearly.
- Do not record indefinitely.
- Do not keep large audio blobs in state longer than needed.
- Do not upload until recording has fully stopped.
- Show clear user-facing states.

Required recording states:

```ts
export type RecordingState =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "stopped"
  | "uploading"
  | "success"
  | "error";
```

Accessibility:

- record button must be a real `<button>`
- record button must have clear visible text
- record button must include an accessible label when icon-only
- recording state should be visible to screen readers where practical

---

## 6. Browser TTS Requirement

Backend Qwen TTS is not implemented yet. Backend currently returns
`"tutor_audio_url": null`.

Until backend TTS is explicitly added, frontend must speak the tutor reply using
the browser Web Speech API.

Rules:

- Use `SpeechSynthesisUtterance`.
- Speak `response.tutor_reply` after successful `/voice-chat`.
- Prefer Mandarin voice with `lang = "zh-CN"`.
- Add a `Replay tutor voice` button.
- Add a `Stop voice` button if speech can overlap.
- If `window.speechSynthesis` is unavailable, fail gracefully and show text
  only.
- Do not add paid TTS APIs.
- Do not add backend TTS integration unless explicitly requested later.
- Do not block rendering if TTS fails.

---

## 7. Required Practice Page UI

After a successful `/voice-chat` call, show:

1. Transcript
2. Tutor reply
3. Mistake cards
4. Fluency score
5. Confidence score
6. Feedback summary
7. Next focus
8. Next drill
9. Memory before
10. Memory after
11. Active weaknesses
12. `times_failed`
13. weakness `status`
14. `severity_score`
15. latest lesson plan

Minimum page sections:

```txt
Practice controls
Transcript
Tutor reply
Feedback
Memory before / after
Next drill
```

The memory comparison must be visible enough for judges to understand that the
agent remembered something from a previous session. Do not hide `memory_before`
and `memory_after` behind developer-only JSON unless a polished summary is also
visible.

---

## 8. Required Memory Dashboard UI

The memory page should show:

1. User ID
2. Learner level
3. Active weaknesses
4. Weakness status
5. Severity score
6. Times failed
7. Recommended drill
8. Recent sessions
9. Latest lesson plan

Empty states are required:

- `No weaknesses yet. Complete a speaking practice session first.`
- `No recent sessions yet.`
- `No lesson plan yet.`

---

## 9. Component Design Principles

Components should be small and have one clear purpose.

Pages compose components. Page files should mostly compose feature components.

Use server components by default. Add `"use client"` only for components/hooks
that need state, effects, event handlers, browser APIs, MediaRecorder,
speechSynthesis, or localStorage.

Components in `components/ui/` must not import SpeakHan API types. Feature
components may import API types.

---

## 10. Hook Design Principles

Hooks must not become god objects.

- `useAudioRecorder()` owns microphone permission, recording state, start/stop,
  audio blob, and recording errors. It does not call backend API.
- `useVoiceChat()` owns request state, upload state, API error state, and latest
  `VoiceChatResponse`. It does not manage `MediaRecorder` or TTS.
- `useTutorSpeech()` owns speak, replay, stop, and browser support state. It
  does not call backend API.
- `useMemory()` owns memory fetching and memory loading/error state. It does
  not record or upload audio.

---

## 11. Data Transformation Rules

Backend response objects must be preserved as typed API data. Do not mutate API
responses directly.

Derived display helpers go in `lib/format/`.

Do not hide these backend fields in the UI:

- `memory_before`
- `memory_after`
- `active_weaknesses`
- `times_failed`
- `status`
- `severity_score`
- `recommended_drill`

These fields are central to the hackathon demo.

---

## 12. Styling Rules

Use Tailwind utility classes. Do not use inline styles unless truly dynamic,
such as a score bar width.

Keep styling simple and consistent. Do not overbuild animations. Do not install
heavy UI libraries unless explicitly requested.

---

## 13. Accessibility Rules

- Buttons must be real `<button>` elements.
- Inputs must have labels.
- Icon-only buttons must have `aria-label`.
- Images must have `alt`.
- Loading states must be visible.
- Errors must be visible.
- Record button must clearly say whether it starts or stops recording.
- Disable submit button while uploading.
- Do not rely on color alone to indicate weakness status.
- For microphone permission, show clear instructions if permission is denied.

---

## 14. Error Handling Conventions

All API errors should flow through `ApiError`. Hooks catch errors and expose
them as state. Components render friendly messages.

Do not show raw JSON stack traces to users.

Good:

```txt
Could not reach the tutor. Please check that the backend is running.
```

Microphone permission denial is expected and should have a specific message.

---

## 15. Environment Variables

Frontend environment file:

```txt
frontend/.env.local
```

Example:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Rules:

- Do not commit `.env.local`.
- Do not put Qwen keys in frontend.
- Do not put Cloudflare R2 keys in frontend.
- Do not put Alibaba OSS keys in frontend.
- Frontend only needs backend base URL.
- All secrets stay in backend `.env`.

---

## 16. Hackathon Demo Priority

Prefer clear, reliable demo UX over complex UI.

Do not add unless explicitly requested:

- authentication
- payments
- settings page
- user account management
- global state libraries
- backend TTS
- realtime streaming
- complex animations
- complicated routing
- database admin panels

The MVP frontend succeeds if a judge can clearly see:

```txt
record audio -> transcript -> tutor reply -> feedback -> memory_before
-> memory_after -> next drill
```

The memory behavior matters more than visual polish.

---

## 17. Manual Verification Flow

Start backend:

```bash
cd backend
python3 -m uvicorn app.main:app --reload --port 8000
```

Start frontend:

```bash
cd frontend
npm install
npm run dev
```

Open:

```txt
http://localhost:3000
```

Demo session 1:

- `user_id`: `demo-user-asr-test-2`
- `scenario`: `restaurant ordering`
- `level`: `HSK1 beginner`
- say: `呃，请问我可以点菜了吗？`

Expected UI:

- transcript appears
- tutor reply appears
- browser speaks tutor reply
- feedback detects hesitation
- `memory_after` shows hesitation weakness
- next drill appears

Demo session 2:

- use the same `user_id`
- say: `呃，我要一份宫保鸡丁。`

Expected UI:

- `memory_before` already contains hesitation weakness
- `memory_after` increments `times_failed`
- tutor gives another drill
- recent sessions shows both attempts

This proves MemoryAgent behavior.

---

## 18. Testing

Testing should be pragmatic for the hackathon.

Prioritize manual verification of:

```txt
record -> submit -> transcript renders -> tutor reply renders
-> browser TTS speaks -> feedback renders -> memory updates
```

Add tests for pure logic if time allows:

- API client error handling
- format helpers
- speech helper fallback
- audio recorder helper behavior that does not require real microphone

Do not write tests that require live Qwen, live R2, live OSS, or real
microphone unless explicitly configured as manual tests.

---

## 19. Git Workflow

Use lowercase, hyphen-separated branch names:

```txt
<prefix>/<short-description>
```

Allowed prefixes: `feat/`, `fix/`, `chore/`, `docs/`, `test/`, `style/`.

Use Conventional Commits:

```txt
<type>(<scope>): <imperative description>
```

Examples:

- `feat(practice): add audio recording flow`
- `feat(memory): show before-after weakness comparison`
- `fix(api): show friendly backend connection errors`
- `docs(frontend): define implementation skill`
- `chore(frontend): configure Tailwind`

---

## 20. Anti-Patterns

Do not do these:

- Calling `fetch()` directly inside a component.
- Hardcoding `http://localhost:8000` inside components.
- Putting Qwen, R2, or OSS keys in frontend.
- Creating a giant `PracticePage` that does everything.
- Creating one god hook for recording, API, memory, and TTS.
- Marking every component `"use client"`.
- Mutating API responses directly.
- Duplicating backend response types in multiple files.
- Hiding `memory_before` and `memory_after`.
- Showing only a chat bubble and ignoring memory.
- Ignoring loading and error states.
- Swallowing microphone permission errors.
- Using raw strings everywhere for statuses/categories.
- Adding auth/settings/payments before MVP demo works.
- Adding backend TTS before browser TTS/demo UI is stable.
- Adding realtime streaming before the normal upload flow is stable.
- Printing or displaying signed storage URLs in the UI.

---

## 21. Checklist Before Committing Frontend Changes

- [ ] Backend-facing calls go through `lib/api/`.
- [ ] API types in `types/api.ts` mirror backend schemas.
- [ ] Components do not call `fetch()` directly.
- [ ] Components are split by responsibility.
- [ ] No god hook was created.
- [ ] `"use client"` is used only where needed.
- [ ] Loading states are visible.
- [ ] Error states are visible.
- [ ] Microphone permission denial is handled.
- [ ] Tutor reply can be spoken with browser TTS.
- [ ] Replay tutor voice button exists if tutor reply is shown.
- [ ] Memory before/after is visible.
- [ ] `times_failed`, `status`, and `severity_score` are visible.
- [ ] No frontend secrets.
- [ ] No hardcoded backend URL in components.
- [ ] `.env.example` includes `NEXT_PUBLIC_API_BASE_URL`.
- [ ] Manual demo flow works.
- [ ] Commit message follows Conventional Commits.

---

## 22. Definition Of Done For Frontend MVP

Frontend MVP is done when:

1. User can record or upload audio.
2. Frontend sends audio to `/api/v1/voice-chat`.
3. Transcript is displayed.
4. Tutor reply is displayed.
5. Tutor reply is spoken aloud using browser TTS.
6. Feedback mistakes are displayed.
7. Fluency and confidence scores are displayed.
8. Next drill is displayed.
9. Memory before and after are displayed.
10. Repeated weakness tracking is visible across two sessions with the same
    `user_id`.
11. App handles loading, backend error, and microphone permission denial.
12. No secrets are committed.
13. The demo can be run locally with backend on `localhost:8000`.

Final MVP demo sentence:

> SpeakHan listens to my Mandarin, replies as a tutor, remembers my recurring
> mistakes, and adapts the next drill.
