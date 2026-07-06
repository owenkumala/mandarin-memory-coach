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
QWEN_CHAT_MODEL=qwen-plus
QWEN_REQUEST_TIMEOUT_SECONDS=30
QWEN_MAX_TURN_TOKENS=900
QWEN_MAX_TUTOR_TOKENS=180
QWEN_MAX_ANALYSIS_TOKENS=650
QWEN_MAX_RETRIES=0
MAX_AUDIO_UPLOAD_BYTES=5000000
```

Do not commit `.env`; it contains secrets and is ignored by git.

For live demo reliability, use `QWEN_CHAT_MODEL=qwen-plus`. In manual
real-Qwen `/voice-chat` testing, `qwen-plus` completed the full request in about
7.85 seconds in this environment.

`QWEN_CHAT_MODEL` is configurable. Stronger or newer Qwen models can be used
when answer quality matters more than latency. For example, `qwen3.7-plus` may
produce strong responses but can be slower or less suitable for live demo
latency in this environment.

As an alternative fallback, `QWEN_CHAT_MODEL=qwen3.6-flash` completed in manual
testing but took about 21.76 seconds here.

For live demos, keep `QWEN_MAX_RETRIES=0` so failed Qwen requests fail fast
instead of waiting through multiple SDK retries. A `QWEN_REQUEST_TIMEOUT_SECONDS`
value of `25` or `30` is usually better for demo UX than a long timeout.

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
