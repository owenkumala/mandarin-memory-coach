# Qwen Chat and Analysis Integration

SpeakHan can run the tutor reply and structured mistake analysis steps through
Alibaba Cloud Model Studio's OpenAI-compatible chat API.

The voice-chat pipeline uses one combined real Qwen call for the tutor reply
and structured analysis when `USE_FAKE_QWEN=false`. This keeps the endpoint
response shape unchanged while reducing latency versus two sequential Qwen
chat requests.

## Local setup

Create or update `backend/.env` with:

```text
USE_FAKE_QWEN=false
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_CHAT_MODEL=qwen3.7-plus
QWEN_REQUEST_TIMEOUT_SECONDS=45
QWEN_MAX_TURN_TOKENS=900
QWEN_MAX_TUTOR_TOKENS=180
QWEN_MAX_ANALYSIS_TOKENS=650
MAX_AUDIO_UPLOAD_BYTES=5000000
```

Do not commit `.env`; it contains secrets and is ignored by git.

For faster demo testing, try `QWEN_CHAT_MODEL=qwen3.6-flash`.

## What is real in this first Qwen commit

- `generate_tutor_turn()` calls Qwen once for both tutor reply and structured
  feedback when `USE_FAKE_QWEN=false`.
- The separate `generate_tutor_reply()` and `analyze_mistakes()` methods remain
  available for focused tests and future use.
- Structured feedback is validated into the existing `AnalysisResponse` schema.

ASR and TTS are still intentionally fake:

- `transcribe_audio()` still returns the MVP transcript `我想吃中国菜`.
- `synthesize_speech()` still returns `None`.

## Manual verification

Run the backend:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

POST a valid short `.m4a`, `.webm`, `.wav`, or `.mp3` file to
`/api/v1/voice-chat` with `user_id=demo-user`, scenario `restaurant ordering`,
and level `HSK1 beginner`. A 1-3 second file is best for demo testing because
the backend still reads and saves the upload.

Expected response:

- `transcript` remains fake: `我想吃中国菜`
- `tutor_reply` comes from real Qwen
- `feedback` comes from real Qwen structured JSON
- memory, session, and lesson-plan rows still update
- `tutor_audio_url` remains `null`
