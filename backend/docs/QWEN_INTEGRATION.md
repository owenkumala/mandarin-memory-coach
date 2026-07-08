# Qwen Chat and Analysis Integration

SpeakHan can run the tutor reply and structured mistake analysis steps through
Alibaba Cloud Model Studio's OpenAI-compatible chat API.

The voice-chat pipeline uses one combined real Qwen call for the tutor reply
and structured analysis when `USE_FAKE_QWEN=false`. This keeps the endpoint
response shape unchanged while reducing latency versus two sequential Qwen
chat requests.

The stable REST endpoint remains:

```text
POST /api/v1/voice-chat
```

It returns one complete response after ASR, tutor reply, structured feedback,
memory update, lesson-plan update, and optional TTS finish.

The progressive realtime endpoint is:

```text
WS /api/v1/voice-chat/realtime
```

It emits frontend-ready events while the pipeline runs, so the UI can show ASR
progress, stream the tutor reply, and play sentence-level audio chunks as soon
as they are ready.

## Local setup

Create or update `backend/.env` with:

```text
USE_FAKE_QWEN=false
USE_FAKE_ASR=true
USE_FAKE_TTS=true
QWEN_API_KEY=...
DASHSCOPE_API_KEY=
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_CHAT_MODEL=qwen-plus
QWEN_ASR_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
QWEN_ASR_MODEL=qwen3-asr-flash
QWEN_ASR_LANGUAGE=zh
QWEN_ASR_ENABLE_LID=true
QWEN_ASR_ENABLE_ITN=false
QWEN_ASR_AUDIO_REF_MODE=s3_url
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
QWEN_ASR_REQUEST_TIMEOUT_SECONDS=30
QWEN_ASR_MAX_RETRIES=0
QWEN_TTS_MODEL=cosyvoice-v3-plus
QWEN_TTS_VOICE=longanyang
QWEN_TTS_BASE_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
QWEN_TTS_OUTPUT_FORMAT=mp3
REALTIME_TTS_MAX_CONCURRENCY=1
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

`qwen3-asr-flash` requires an HTTPS audio URL accepted by Qwen's server-side
multimodal fetcher. Local file paths can fail because the DashScope SDK
local-file upload certificate flow returned `InvalidApiKey` with this Qwen Cloud
key.

Ngrok/FastAPI `public_url` mode also failed in manual testing with
`Missing Content-Length of multimodal url`, even though `curl -I` saw
`content-length`.

Alibaba OSS remains the preferred final provider because it strengthens the
Alibaba Cloud proof for the hackathon. While OSS setup is blocked externally,
Cloudflare R2 can be used as a temporary S3-compatible fallback with
`QWEN_ASR_AUDIO_REF_MODE=s3_url`. The backend uploads the saved audio file to
R2/S3-compatible storage and passes a signed or public HTTPS URL to Qwen ASR.
Switch back to `oss_url` when Alibaba OSS is available.

`public_url` remains available only for deployed/static hosting that Qwen's
server-side fetcher accepts. `local_path` and `file_url` remain diagnostic modes
only. Signed URLs must not be printed with query parameters because those query
strings can contain signature data.

`qwen3-asr-flash-realtime` is intended for WebSocket streaming ASR, but this
branch does not invent an unsupported protocol. Local SDK inspection found:

- `dashscope.audio.asr.Recognition`, which exposes an official websocket-style
  recognition interface with `start()`, `send_audio_frame()`, and `stop()`.
- `dashscope.audio.qwen_asr.QwenTranscription`, which is a Qwen batch
  transcription API.
- no clear local SDK class or sample that maps `qwen3-asr-flash` or
  `qwen3-asr-flash-realtime` to a supported realtime Qwen ASR session.

The realtime WebSocket endpoint therefore uses a `RealtimeAsrSession`
abstraction with a buffered fallback implementation: the frontend sends base64
audio chunks, the backend stores them, and on `end_audio` it reuses the stable
`transcribe_audio()` path. If Qwen publishes or confirms the realtime model
contract for this SDK, the provider-specific session should be added behind the
same abstraction and emit `asr_partial` and `asr_final` events.

TTS is optional and configured separately with `USE_FAKE_TTS`. When
`USE_FAKE_TTS=true`, the backend keeps returning `tutor_audio_url=null` and the
frontend should use browser Web Speech API playback as the fallback. When
`USE_FAKE_TTS=false`, `synthesize_speech()` uses the Alibaba DashScope SDK
`dashscope.audio.tts_v2.SpeechSynthesizer` official non-streaming CosyVoice
flow and writes the returned audio bytes to `backend/storage/tutor_audio/`.

For TTS, set:

```text
USE_FAKE_TTS=false
QWEN_TTS_MODEL=cosyvoice-v3-plus
QWEN_TTS_VOICE=longanyang
QWEN_TTS_BASE_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
QWEN_TTS_OUTPUT_FORMAT=mp3
REALTIME_TTS_MAX_CONCURRENCY=1
```

`DASHSCOPE_API_KEY` is used first for TTS, then `QWEN_API_KEY`. Do not commit
real keys. If Qwen/DashScope TTS setup fails during demo prep, keep
`USE_FAKE_TTS=true` and rely on browser TTS in the frontend.

`QWEN_TTS_BASE_URL` may be blank or a websocket URL. For Qwen Cloud
international CosyVoice TTS, use:

```text
QWEN_TTS_BASE_URL=wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference
```

Do not use `https://dashscope-intl.aliyuncs.com/api/v1` for TTS; that URL is
for DashScope native HTTP-style APIs such as upload ASR, while CosyVoice TTS
uses WSS/WebSocket internally.

If DashScope TTS fails with a local WebSocket/certificate error such as
`SSL: CERTIFICATE_VERIFY_FAILED`, the `/voice-chat` endpoint keeps returning the
text tutor reply and sets `tutor_audio_url=null`. This preserves the demo loop;
the frontend should use browser TTS as the fallback while local certificate or
DashScope websocket setup is fixed.

## Qwen TTS certificate setup

CosyVoice TTS uses WSS/WebSocket internally. On macOS framework Python installs,
the WebSocket TLS handshake can fail even when the Qwen key and model are
correct. Do not disable SSL verification, and do not set `cert_reqs` to
`ssl.CERT_NONE`.

The backend now auto-configures Python SSL certificate environment variables
at app startup. If `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` are missing, it sets
them for the current Python process to `certifi.where()` before routes or
Qwen/DashScope clients are used. Existing user-provided values are never
overwritten.

Manual exports are only needed when you want explicit shell-level configuration
or when debugging outside the FastAPI process. For manual shell setup, install
or refresh `certifi`, then point Python clients at its CA bundle:

```bash
python3 -m pip install --upgrade certifi
export SSL_CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())')"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
```

For macOS framework Python, the Apple-style certificate installer may also help:

```bash
open "/Applications/Python 3.14/Install Certificates.command"
```

Use the matching Python version in that path if your local Python is not 3.14.
To make the shell-level certifi fix permanent, manually add the two `export`
lines above to `~/.zshrc`.

On Linux or Alibaba Cloud deployment targets, ensure the system CA bundle is
installed and up to date, for example with the distro `ca-certificates` package.

Two manual diagnostics are available:

```bash
cd backend
python3 scripts/check_python_certs.py
python3 scripts/check_qwen_tts.py
```

`check_python_certs.py` treats a DashScope 401 `InvalidApiKey` or
`No API-key provided` response as a good connectivity result because it means
TLS and network access reached DashScope. The TTS script prints whether keys are
configured, but never prints key values. Both scripts also call the same
automatic certifi configuration helper before running diagnostics.

## What is real

- `generate_tutor_turn()` calls Qwen once for both tutor reply and structured
  feedback when `USE_FAKE_QWEN=false`.
- The separate `generate_tutor_reply()` and `analyze_mistakes()` methods remain
  available for focused tests and future use.
- `stream_tutor_reply()` uses OpenAI-compatible streaming chat for the realtime
  endpoint when `USE_FAKE_QWEN=false`.
- Structured feedback is validated into the existing `AnalysisResponse` schema.
- `transcribe_audio()` calls DashScope native Qwen ASR when
  `USE_FAKE_QWEN=false`, `USE_FAKE_ASR=false`, and ASR settings are configured.

## Realtime WebSocket protocol

Frontend control messages are JSON objects:

```json
{"type": "start", "user_id": "demo-user-1", "scenario": "restaurant ordering", "level": "HSK3 lower intermediate", "audio_filename": "sample-mandarin.mp3", "audio_mime_type": "audio/mpeg"}
{"type": "audio_chunk", "audio_base64": "..."}
{"type": "end_audio"}
{"type": "cancel"}
```

If `level` is missing from `start`, the backend defaults to `HSK1 beginner`.
The level is stored on the learner record and passed into the same tutor and
feedback logic used by REST `/voice-chat`. HSK behavior is level-adaptive:

- HSK1 focuses on short survival phrases, pronunciation, tones, survival
  vocabulary, and simple grammar.
- HSK2 uses simple connected sentences and basic question patterns.
- HSK3 uses longer practical sentences and more scenario vocabulary.
- HSK4 uses more natural conversation and more correction detail.
- HSK5/6 focuses on nuanced expression, fluency, register, idiomatic usage,
  word choice, naturalness, and discourse structure.

Realtime `start` may include optional audio metadata. If `audio_filename` or
`audio_mime_type` is missing, the backend defaults to `realtime.webm` and
`audio/webm`, which is the normal browser microphone path. The backend sanitizes
the filename to a safe basename and only preserves `.mp3`, `.m4a`, `.wav`, or
`.webm`; unsupported extensions fall back to `.webm`. Correct extension metadata
matters because S3/OSS upload content type is inferred from the saved file
suffix before Qwen ASR fetches the audio URL.

The backend emits events in this shape:

```json
{"type": "session_started", "payload": {"session_id": "...", "level": "HSK3 lower intermediate"}}
```

Supported event types:

- `session_started`: emitted immediately after the `start` message is accepted.
- `audio_received`: confirms each buffered audio chunk.
- `asr_partial`: reserved for future true streaming ASR support.
- `asr_final`: final transcript after buffered or realtime ASR completes.
- `tutor_token`: streamed tutor text chunk.
- `tutor_sentence`: completed sentence ready for TTS processing.
- `audio_chunk_ready`: sentence-level TTS MP3/WAV is ready.
- `feedback_ready`: structured `AnalysisResponse` is ready.
- `memory_updated`: session, mistakes, active weaknesses, and lesson plan are
  saved.
- `error`: recoverable warning or terminal error.
- `done`: terminal event for the session.

Realtime mode intentionally splits user-facing tutor reply generation from
structured feedback analysis. Tutor reply streaming starts first for perceived
latency; structured feedback runs in parallel and can emit `feedback_ready`
before slow final TTS chunks finish. Memory persistence waits for complete tutor
text plus feedback, but does not wait for every audio chunk unless needed. The
frontend should show streamed text and play ready audio progressively; it should
not wait for `done` before showing or speaking the tutor reply. The terminal
`done` event still waits until tutor text, feedback/memory work, and all pending
TTS chunk tasks have completed or emitted warning errors.

Realtime tutor text is prompted more strictly than the REST tutor response
because it is fed directly into sentence-level TTS. The realtime prompt asks for
1-2 short spoken sentences, mainly Mandarin, normal Chinese sentence endings,
no emoji, no markdown, no bullet points, no quote-heavy examples, and concise
HSK-appropriate wording. The first model-generated sentence should be the
correction or direct replacement; the optional second sentence should ask the
learner to repeat or answer. HSK1-HSK3 replies target about 55 Chinese
characters or fewer; HSK4-HSK6 replies target about 80. Detailed mistake
explanations, memory updates, and next-drill analysis arrive later through
`feedback_ready` and `memory_updated` instead of being spoken immediately.
The scenario comes from the WebSocket `start` message; `restaurant ordering` is
only the default/demo scenario, not a hardcoded realtime tutoring scene.

After `asr_final`, realtime mode emits the fast acknowledgement sentence as
sequence `0`. If the shared fast-ack audio file is already cached, the matching
`audio_chunk_ready` event is sent immediately before the Qwen tutor stream
starts:

```json
{"type": "tutor_sentence", "payload": {"sequence": 0, "text": "我来帮你改一句。", "source": "fast_ack"}}
{"type": "audio_chunk_ready", "payload": {"sequence": 0, "audio_url": "/storage/tutor_audio/_shared/realtime-fast-ack.mp3", "source": "fast_ack"}}
```

The frontend should play sequence `0` first if present. The model-generated
tutor sentences still start at sequence `1`. If the cache is cold, the backend
generates the fast-ack audio in the background, so sequence `0` audio may arrive
after early tutor tokens. If fake TTS is enabled or the fast acknowledgement TTS
fails, sequence `0` audio is skipped and the normal sequence `1+` flow
continues.

The perceived realtime flow is:

```text
asr_final -> cached fast ack audio when present -> streamed correction text -> generated TTS chunks
```

This improves perceived latency after buffered ASR finalizes, but true 1-2
second ChatGPT-like response still requires a later real streaming ASR
implementation.

### ASR latency diagnostics

Realtime ASR currently uses the buffered fallback: the WebSocket collects audio
chunks, writes one local audio file on `end_audio`, then reuses the stable Qwen
ASR path. Cached fast acknowledgement audio can start playback immediately after
`asr_final`, but it cannot reduce slow or variable ASR time before `asr_final`.
True 1-2 second ChatGPT-like latency still requires a later supported streaming
ASR implementation.

When `asr_final` is slow, inspect backend logs for these stage timings:

```text
realtime.end_audio_received_seconds=...
realtime.asr_finish_start_seconds=...
realtime.asr_buffer_bytes=... chunks=...
realtime.asr_save_audio_seconds=... bytes=...
realtime.asr_transcribe_start
qwen.asr_audio_ref_mode=... bytes=...
qwen.asr_prepare_audio_ref_start audio_ref_mode=...
s3.upload_audio_seconds=... bytes=... key=...
s3.presigned_url_seconds=... key=...
oss.upload_audio_seconds=... bytes=... key=...
oss.signed_url_seconds=... key=...
qwen.asr_upload_seconds=... provider=...
qwen.asr_prepare_audio_ref_seconds=...
qwen.asr_request_start model=... audio_ref_mode=...
qwen.asr_seconds=... model=...
qwen.asr_parse_seconds=... model=...
qwen.asr_total_seconds=... audio_ref_mode=...
realtime.asr_transcribe_seconds=...
realtime.asr_finish_done_seconds=...
realtime.asr_final_seconds=...
```

The logs intentionally include audio size, object key, model, and audio
reference mode, but never API keys, authorization headers, raw audio bytes, or
full signed URLs. Compare the realtime timestamps against `qwen.asr_total_seconds`
and the storage upload/signing logs to separate local buffering, upload, URL
preparation, DashScope request time, and response parsing.

Sentence-level TTS runs as tutor tokens arrive. The backend finalizes sentences
on `。！？!?` or newline, starts `synthesize_speech()` for each sentence, saves
files as:

```text
storage/tutor_audio/<user_id>/chunk-<sequence>-<uuid>.mp3
```

Each successful TTS task emits:

```json
{"type": "audio_chunk_ready", "payload": {"sequence": 1, "audio_url": "/storage/tutor_audio/..."}}
```

The frontend should play `audio_chunk_ready` URLs in ascending `sequence` order.
If one sentence TTS task fails, the backend emits an `error` event with
`severity=warning` and continues later chunks where possible. `audio_chunk_ready`
events may arrive out of order because sentence-level TTS tasks finish at
different speeds, so the frontend must buffer by `sequence` and play chunks in
order.

### Realtime TTS tuning

Sentence-level realtime TTS is pipelined, but it is still not true streaming
TTS. Each complete tutor sentence starts one `synthesize_speech()` call and
emits an `audio_chunk_ready` event after the MP3/WAV file is saved.

`REALTIME_TTS_MAX_CONCURRENCY` controls how many model-generated sentence TTS
tasks may call Qwen CosyVoice at once. The default is `1`, which is safest for
live Qwen TTS because CosyVoice uses WSS/WebSocket connections and multiple
near-simultaneous connections can fail during demo runs. Higher values, clamped
internally to a small cap, may reduce total completion time in fake/local tests
or carefully tuned environments, but they can increase websocket connection
failures.

The frontend must still buffer `audio_chunk_ready` events by `sequence`. With
`REALTIME_TTS_MAX_CONCURRENCY=1`, model-generated chunks should usually arrive
in order, but the frontend should not assume that because future settings or
provider behavior may change ordering. Fast acknowledgement audio is separate:
sequence `0` comes from the shared fast-ack path, while model-generated TTS
starts at sequence `1`.

Realtime TTS queue logs include sequence number, sentence length, pending task
count, chosen max concurrency, start, completion, and warning failures:
`realtime.tts_queue_sentence`, `realtime.tts_start`, `realtime.tts_done`,
`realtime.tts_failed`, and `realtime.tts_wait_pending`.

The realtime backend logs these latency milestones with elapsed seconds from
the accepted `start` message:

- `realtime.session_started`: start message accepted and session event sent.
- `realtime.audio_received`: one audio chunk was accepted; includes byte counts.
- `realtime.asr_final_seconds`: buffered or realtime ASR produced the transcript.
- `realtime.first_tutor_token_seconds`: first streamed tutor text chunk emitted.
- `realtime.first_tutor_sentence_seconds`: first sentence boundary detected.
- `realtime.first_audio_chunk_ready_seconds`: first sentence audio URL emitted.
- `realtime.feedback_ready_seconds`: structured feedback emitted.
- `realtime.memory_updated_seconds`: session, mistakes, weaknesses, and lesson
  plan saved.
- `realtime.done_seconds`: terminal event sent after all required work finished.

Fake mode and TTS behavior:

- `transcribe_audio()` still returns the MVP transcript `我想吃中国菜` when either
  `USE_FAKE_QWEN=true` or `USE_FAKE_ASR=true`.
- `synthesize_speech()` returns `None` when `USE_FAKE_TTS=true`.
- `synthesize_speech()` saves tutor audio and returns a local path when
  `USE_FAKE_TTS=false` and TTS settings are configured.

## Manual verification

First run the ASR diagnostic script:

```bash
cd backend
python3 scripts/check_qwen_asr.py
python3 scripts/check_qwen_asr.py sample-mandarin.m4a
python3 scripts/check_qwen_asr.py --audio-ref-mode s3_url sample-mandarin.mp3
python3 scripts/check_qwen_asr.py --audio-ref-mode oss_url sample-mandarin.mp3
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

To inspect realtime WebSocket event timing manually, run:

```bash
cd backend
python3 scripts/check_realtime_voice_ws.py \
  --audio sample-mandarin.mp3 \
  --user-id demo-user-realtime-manual \
  --scenario "restaurant ordering" \
  --level "HSK3 lower intermediate"
```

The script connects to
`ws://localhost:8000/api/v1/voice-chat/realtime` by default. Override with
`--url` if the backend is running somewhere else. It infers `audio_filename` and
`audio_mime_type` from `--audio` (`.mp3`, `.m4a`, `.wav`, or `.webm`) and sends
that metadata in the `start` message. It prints event timing without printing
secrets or raw audio:

```text
0.00s session_started payload_keys=session_id,user_id,scenario,level,asr_mode
0.08s audio_received total_bytes_received=12345
3.80s asr_final transcript=我想点中国菜
3.85s tutor_sentence sequence=0 source=fast_ack text=我来帮你改一句。
3.90s audio_chunk_ready sequence=0 source=fast_ack audio_url=/storage/tutor_audio/_shared/realtime-fast-ack.mp3
4.10s tutor_token text=很好
4.40s tutor_sentence sequence=1 text=很好，你可以说：我想点一份中国菜。
5.20s feedback_ready
5.30s memory_updated
6.20s audio_chunk_ready sequence=1 audio_url=/storage/tutor_audio/...
6.20s done
```

In optimized realtime runs, `feedback_ready` and `memory_updated` may appear
before a slow `audio_chunk_ready`. The frontend should treat event ordering as
progressive rather than assuming feedback always follows all audio chunks.
Likewise, the frontend should not wait for `done` before rendering tutor text or
starting audio playback.

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
- `tutor_audio_url` is `null` when `USE_FAKE_TTS=true`
- `tutor_audio_url` points to `/storage/tutor_audio/...` when
  `USE_FAKE_TTS=false` and DashScope TTS succeeds

If `QWEN_ASR_AUDIO_REF_MODE=oss_url`, the backend uploads the audio to OSS and
uses either `ALIBABA_OSS_PUBLIC_BASE_URL + object_key` or a signed URL from
`bucket.sign_url("GET", object_key, expires)`.

If `QWEN_ASR_AUDIO_REF_MODE=s3_url`, the backend uploads the audio to
S3-compatible storage such as Cloudflare R2 and uses either
`S3_PUBLIC_BASE_URL + object_key` or a presigned GET URL.
