# Qwen Chat and Analysis Integration

SpeakHan can run the tutor reply and structured mistake analysis steps through
Alibaba Cloud Model Studio's OpenAI-compatible chat API.

## Local setup

Create or update `backend/.env` with:

```text
USE_FAKE_QWEN=false
QWEN_API_KEY=your_model_studio_api_key
QWEN_BASE_URL=https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
QWEN_CHAT_MODEL=qwen-plus
```

Do not commit `.env`; it contains secrets and is ignored by git.

## What is real in this first Qwen commit

- `generate_tutor_reply()` calls Qwen chat when `USE_FAKE_QWEN=false`.
- `analyze_mistakes()` calls Qwen chat and validates structured JSON into the
  existing `AnalysisResponse` schema when `USE_FAKE_QWEN=false`.

ASR and TTS are still intentionally fake:

- `transcribe_audio()` still returns the MVP transcript `我想吃中国菜`.
- `synthesize_speech()` still returns `None`.

## Manual verification

Run the backend:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

POST a valid dummy audio file to `/api/v1/voice-chat`. The response should keep
the fake transcript while returning a real Qwen tutor reply and Qwen-validated
feedback JSON.
