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
USE_FAKE_ASR=true
QWEN_API_KEY=...
DASHSCOPE_API_KEY=
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_CHAT_MODEL=qwen-plus
QWEN_ASR_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
QWEN_ASR_MODEL=qwen3-asr-flash
QWEN_ASR_LANGUAGE=zh
QWEN_ASR_ENABLE_LID=true
QWEN_ASR_ENABLE_ITN=false
QWEN_ASR_AUDIO_REF_MODE=public_url
PUBLIC_BACKEND_BASE_URL=
QWEN_ASR_REQUEST_TIMEOUT_SECONDS=30
QWEN_ASR_MAX_RETRIES=0
QWEN_REQUEST_TIMEOUT_SECONDS=30
QWEN_MAX_TURN_TOKENS=500
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

ASR is configured separately with `QWEN_ASR_MODEL`. `qwen3-asr-flash` uses the
DashScope native `MultiModalConversation` API, not OpenAI-compatible
`/audio/transcriptions`. The previous attempt to call
`/compatible-mode/v1/audio/transcriptions` returned 404 because that path is
not the ASR API for this model.

Keep these base URLs conceptually separate:

- `QWEN_BASE_URL`: OpenAI-compatible chat base URL, for example
  `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
- `QWEN_ASR_BASE_URL`: DashScope native ASR base URL when an override is needed.
  For international Qwen Cloud keys, a likely candidate to test is
  `https://dashscope-intl.aliyuncs.com/api/v1`. If empty, the DashScope SDK uses
  its default native endpoint.

ASR uses `DASHSCOPE_API_KEY` first, then falls back to `QWEN_API_KEY`. A 401
`InvalidApiKey` from DashScope can mean the key is not accepted by the native
ASR endpoint, or the SDK is hitting the wrong region/base URL. Do not commit
real keys in `.env`.

Manual testing confirmed `qwen3-asr-flash` works with HTTPS audio URLs. The
Qwen sample URL `https://dashscope.oss-cn-beijing.aliyuncs.com/audios/welcome.mp3`
returned the transcript `欢迎使用阿里云。`.

Local file paths can fail because the DashScope SDK local-file upload
certificate flow returned `InvalidApiKey` with this Qwen Cloud key. For demo,
use `QWEN_ASR_AUDIO_REF_MODE=public_url` and set `PUBLIC_BACKEND_BASE_URL` to a
publicly reachable backend URL, such as an ngrok URL, a deployed Alibaba Cloud
ECS URL, or serve/upload the file through OSS.

`qwen3-asr-flash-realtime` is a WebSocket streaming model and is not implemented
yet. This backend currently implements upload-style ASR with `qwen3-asr-flash`.

## What is real

- `generate_tutor_turn()` calls Qwen once for both tutor reply and structured
  feedback when `USE_FAKE_QWEN=false`.
- The separate `generate_tutor_reply()` and `analyze_mistakes()` methods remain
  available for focused tests and future use.
- Structured feedback is validated into the existing `AnalysisResponse` schema.
- `transcribe_audio()` calls DashScope native Qwen ASR when
  `USE_FAKE_QWEN=false`, `USE_FAKE_ASR=false`, and ASR settings are configured.

Fake mode and TTS behavior:

- `transcribe_audio()` still returns the MVP transcript `我想吃中国菜` when either
  `USE_FAKE_QWEN=true` or `USE_FAKE_ASR=true`.
- `synthesize_speech()` still returns `None`.

## Manual verification

First run the ASR diagnostic script:

```bash
cd backend
python3 scripts/check_qwen_asr.py
python3 scripts/check_qwen_asr.py sample-mandarin.m4a
python3 scripts/check_qwen_asr.py --audio-ref-mode local_path sample-mandarin.m4a
```

The script prints whether `QWEN_API_KEY` and `DASHSCOPE_API_KEY` are present,
which key source is used, the chat and ASR base URLs, the model, and the audio
reference. It never prints key values.
If the audio argument is already an HTTPS URL, the script sends it directly to
ASR.

Run the backend:

```bash
cd backend
python3 -m uvicorn app.main:app --reload --port 8000
```

POST a valid short `.m4a`, `.webm`, `.wav`, or `.mp3` file to
`/api/v1/voice-chat` with `user_id=demo-user`, scenario `restaurant ordering`,
and level `HSK1 beginner`. A 1-3 second file is best for demo testing because
the backend still reads and saves the upload.

You can use Swagger at:

```text
http://localhost:8000/docs
```

Or run curl with a short Mandarin sample:

```bash
time curl -s -X POST http://localhost:8000/api/v1/voice-chat \
  -F "audio=@sample-mandarin.m4a;type=audio/mp4" \
  -F "user_id=demo-user-asr-test" \
  -F "scenario=restaurant ordering" \
  -F "level=HSK1 beginner"
```

Expected response:

- `transcript` reflects the uploaded speech when real ASR is configured, rather
  than always returning `我想吃中国菜`
- `tutor_reply` comes from real Qwen
- `feedback` comes from real Qwen structured JSON
- memory, session, and lesson-plan rows still update
- `tutor_audio_url` remains `null`

If `QWEN_ASR_AUDIO_REF_MODE=public_url`, the backend builds the ASR audio
reference as `PUBLIC_BACKEND_BASE_URL + /storage/...`. Ensure the resulting URL
is reachable by Alibaba Cloud before the live demo.
