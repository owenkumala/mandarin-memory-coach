# SpeakHan Frontend

Next.js App Router frontend for the SpeakHan Mandarin memory coach demo.

## Local Setup

```bash
cd frontend
npm install
npm run dev
```

Set the backend URL in `.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Do not put Qwen, R2, OSS, or other backend secrets in frontend environment
files.

## Demo Flow

1. Start the backend on `http://localhost:8000`.
2. Open the frontend at `http://localhost:3000`.
3. Use the same `user_id` for two practice turns.
4. Record or upload audio.
5. Confirm transcript, tutor reply, feedback, `memory_before`, `memory_after`,
   weakness `times_failed`, status, severity, and next drill are visible.

See `docs/FRONTEND_SKILL.md` for the frontend coding standards.
