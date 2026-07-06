# Backend TODO — SpeakHan / Mandarin Memory Coach

This checklist is the current backend handoff for a teammate joining the
SpeakHan / Mandarin Memory Coach project.

## Completed

- [x] FastAPI project structure
- [x] SQLite memory database
- [x] SQLAlchemy models
- [x] Pydantic schemas and enums
- [x] Fake Qwen mode
- [x] `POST /api/v1/voice-chat`
- [x] `GET /api/v1/memory/{user_id}`
- [x] `GET /api/v1/lesson-plan/{user_id}`
- [x] `GET /api/v1/health`
- [x] Session, mistake, and active weakness persistence
- [x] Weakness memory scoring and status updates
- [x] Real Qwen tutor reply and structured feedback
- [x] Real Qwen ASR transcription
- [x] Combined Qwen call for lower `/voice-chat` latency
- [x] Timing logs for voice-chat and Qwen stages
- [x] Upload validation for extension, empty file, and size limit
- [x] Pytest coverage for endpoints, memory behavior, validation, and Qwen client helpers

## In Progress / Verify

- [ ] Confirm local commits are not pushed yet before handing off.
- [ ] Confirm `.env.example` matches demo settings.
- [ ] Confirm Qwen integration docs recommend `qwen-plus`.
- [ ] Confirm timing logs appear in uvicorn during manual testing.
- [ ] Confirm `qwen-plus` live `/voice-chat` latency remains below 10-15 seconds.
- [ ] Run manual real-ASR test with short spoken Mandarin audio.
- [ ] Confirm demo user memory should be reset or use a fresh `user_id`.

## Next Backend Tasks

- [ ] Add real Qwen TTS.
- [ ] Add graceful fallback if Qwen times out.
- [ ] Make prompts smaller if latency grows.
- [ ] Add endpoint or script to reset demo user memory.
- [ ] Add seed demo data option.
- [ ] Add GitHub Actions CI.
- [ ] Add production deployment instructions for Alibaba Cloud ECS.
- [ ] Improve root README.
- [ ] Add architecture diagram.
- [ ] Add demo script.

## Frontend / Integration TODO

- [ ] Push-to-talk audio recorder.
- [ ] Send audio to `/api/v1/voice-chat`.
- [ ] Show transcript.
- [ ] Show tutor reply.
- [ ] Play tutor audio once TTS exists.
- [ ] Show memory dashboard.
- [ ] Show active weaknesses and lesson plan.
- [ ] Add demo mode with fixed user ID.

## Hackathon Submission TODO

- [ ] Polish README.
- [ ] Record demo video.
- [ ] Add architecture diagram.
- [ ] Add Alibaba Cloud deployment proof.
- [ ] Explain Qwen usage clearly.
- [ ] Demonstrate MemoryAgent behavior clearly.
- [ ] Clean GitHub repo.
- [ ] Complete `.env.example`.
- [ ] Confirm no secrets are committed.
