"""Fake-first Qwen client for ASR, tutor reply, analysis, and TTS.

The class keeps all future Alibaba Cloud Model Studio calls behind one
interface while fake mode makes the memory pipeline testable without secrets.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from textwrap import dedent

import dashscope
from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
from dashscope.common.error import DashScopeException
from openai import APITimeoutError, AsyncOpenAI, OpenAIError
from pydantic import ValidationError
from requests import RequestException

from app.core.config import Settings
from app.schemas import (
    AnalysisResponse,
    MemoryResponse,
    MistakeAnalysis,
    MistakeType,
    WeaknessCategory,
)
from app.services.oss_audio_service import upload_audio_to_oss
from app.services.s3_audio_service import upload_audio_to_s3
from app.utils.audio import storage_url

logger = logging.getLogger(__name__)
SUPPORTED_TTS_OUTPUT_FORMATS = {"mp3", "wav"}

ANALYSIS_JSON_EXAMPLE = {
    "mistakes": [
        {
            "type": "pronunciation",
            "weakness_category": "zh_ch_confusion",
            "target": "中国菜 / 吃",
            "target_pinyin": "Zhōngguó cài / chī",
            "heard_pinyin": None,
            "problem_sound": "zh/ch",
            "problem_tone": None,
            "display_correction": "中国菜 zhōngguó cài；吃 chī",
            "severity": 4,
            "feedback": "Practice separating zh in 中国 from ch in 吃.",
            "example_sentence": "我想吃中国菜。",
            "recommended_drill": "Repeat 中国菜 and 想吃 slowly, then in a full sentence.",
        }
    ],
    "fluency_score": 65,
    "confidence_score": 60,
    "summary": "Short summary of the learner's Mandarin performance.",
    "next_focus": "Next lesson focus.",
    "next_drill": "Specific drill for next practice.",
}

TURN_JSON_EXAMPLE = {
    "tutor_reply": "很好！你说：我想吃中国菜。现在请说：请给我一份中国菜。",
    "feedback": ANALYSIS_JSON_EXAMPLE,
}


class QwenClient:
    """Client wrapper for fake and real Qwen Model Studio calls."""

    def __init__(self, settings: Settings) -> None:
        """Store settings so fake and future real modes share one interface."""
        self.settings = settings

    async def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe learner audio through fake mode or real Qwen ASR."""
        started_at = time.perf_counter()
        audio_ref_mode = self.settings.QWEN_ASR_AUDIO_REF_MODE.strip().lower()
        logger.info(
            "qwen.asr_audio_ref_mode=%s bytes=%s fake_qwen=%s fake_asr=%s",
            audio_ref_mode,
            _audio_size_for_log(audio_path),
            self.settings.USE_FAKE_QWEN,
            self.settings.USE_FAKE_ASR,
        )
        try:
            if self.settings.USE_FAKE_QWEN or self.settings.USE_FAKE_ASR:
                return "我想吃中国菜"

            audio_ref = await build_asr_audio_ref(audio_path, self.settings)
            return await run_dashscope_asr(self.settings, audio_ref)
        finally:
            logger.info(
                "qwen.asr_total_seconds=%.2f audio_ref_mode=%s",
                time.perf_counter() - started_at,
                audio_ref_mode,
            )

    async def generate_tutor_reply(
        self,
        transcript: str,
        memory: MemoryResponse,
        scenario: str,
        level: str,
    ) -> str:
        """Generate a Mandarin tutor reply using current learner memory."""
        fake_reply = _fake_tutor_reply(
            transcript=transcript,
            memory=memory,
            scenario=scenario,
            level=level,
        )
        if self.settings.USE_FAKE_QWEN:
            return fake_reply

        client = self._real_client()
        started_at = time.perf_counter()
        try:
            response = await client.chat.completions.create(
                model=self.settings.QWEN_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": _tutor_system_prompt()},
                    {
                        "role": "user",
                        "content": _tutor_user_prompt(
                            transcript=transcript,
                            memory=memory,
                            scenario=scenario,
                            level=level,
                        ),
                    },
                ],
                temperature=0.4,
                max_tokens=self.settings.QWEN_MAX_TUTOR_TOKENS,
            )
        except APITimeoutError as exc:
            raise ValueError(_qwen_timeout_message("tutor reply", self.settings)) from exc
        except OpenAIError as exc:
            raise ValueError("Qwen tutor reply request failed.") from exc
        finally:
            elapsed = time.perf_counter() - started_at
            logger.info(
                "qwen.tutor_reply_seconds=%.2f model=%s",
                elapsed,
                self.settings.QWEN_CHAT_MODEL,
            )
        return _extract_chat_content(response)

    async def stream_tutor_reply(
        self,
        transcript: str,
        memory: MemoryResponse,
        scenario: str,
        level: str,
    ) -> AsyncIterator[str]:
        """Yield tutor reply text chunks from fake mode or Qwen streaming chat."""
        fake_reply = _fake_tutor_reply(
            transcript=transcript,
            memory=memory,
            scenario=scenario,
            level=level,
        )
        if self.settings.USE_FAKE_QWEN:
            for chunk in _fake_stream_chunks(fake_reply):
                yield chunk
            return

        client = self._real_client()
        started_at = time.perf_counter()
        try:
            stream = await client.chat.completions.create(
                model=self.settings.QWEN_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": _tutor_realtime_system_prompt()},
                    {
                        "role": "user",
                        "content": _tutor_realtime_user_prompt(
                            transcript=transcript,
                            memory=memory,
                            scenario=scenario,
                            level=level,
                        ),
                    },
                ],
                temperature=0.4,
                max_tokens=self.settings.QWEN_MAX_TUTOR_TOKENS,
                stream=True,
            )
            async for chunk in stream:
                text = _extract_stream_delta(chunk)
                if text:
                    yield text
        except APITimeoutError as exc:
            raise ValueError(
                _qwen_timeout_message("streaming tutor reply", self.settings)
            ) from exc
        except OpenAIError as exc:
            raise ValueError("Qwen streaming tutor reply request failed.") from exc
        finally:
            elapsed = time.perf_counter() - started_at
            logger.info(
                "qwen.tutor_reply_stream_seconds=%.2f model=%s",
                elapsed,
                self.settings.QWEN_CHAT_MODEL,
            )

    async def analyze_mistakes(
        self,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return structured Mandarin feedback with fixed enum categories."""
        fake_analysis = _fake_analysis(
            transcript=transcript,
            scenario=scenario,
            level=level,
        )
        if self.settings.USE_FAKE_QWEN:
            return fake_analysis

        client = self._real_client()
        started_at = time.perf_counter()
        try:
            response = await client.chat.completions.create(
                model=self.settings.QWEN_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": _analysis_system_prompt()},
                    {
                        "role": "user",
                        "content": _analysis_user_prompt(
                            transcript=transcript,
                            scenario=scenario,
                            level=level,
                        ),
                    },
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
                max_tokens=self.settings.QWEN_MAX_ANALYSIS_TOKENS,
            )
        except APITimeoutError as exc:
            raise ValueError(_qwen_timeout_message("analysis", self.settings)) from exc
        except OpenAIError as exc:
            raise ValueError("Qwen analysis request failed.") from exc
        finally:
            elapsed = time.perf_counter() - started_at
            logger.info(
                "qwen.analysis_seconds=%.2f model=%s",
                elapsed,
                self.settings.QWEN_CHAT_MODEL,
            )
        return parse_analysis_json(_extract_chat_content(response))

    async def generate_tutor_turn(
        self,
        transcript: str,
        memory: MemoryResponse,
        scenario: str,
        level: str,
    ) -> tuple[str, AnalysisResponse]:
        """Generate tutor reply and analysis in one real Qwen chat call."""
        if self.settings.USE_FAKE_QWEN:
            return (
                _fake_tutor_reply(
                    transcript=transcript,
                    memory=memory,
                    scenario=scenario,
                    level=level,
                ),
                _fake_analysis(
                    transcript=transcript,
                    scenario=scenario,
                    level=level,
                ),
            )

        client = self._real_client()
        started_at = time.perf_counter()
        try:
            response = await client.chat.completions.create(
                model=self.settings.QWEN_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": _turn_system_prompt()},
                    {
                        "role": "user",
                        "content": _turn_user_prompt(
                            transcript=transcript,
                            memory=memory,
                            scenario=scenario,
                            level=level,
                        ),
                    },
                ],
                temperature=0.25,
                response_format={"type": "json_object"},
                max_tokens=self.settings.QWEN_MAX_TURN_TOKENS,
            )
        except APITimeoutError as exc:
            raise ValueError(_qwen_timeout_message("tutor turn", self.settings)) from exc
        except OpenAIError as exc:
            raise ValueError("Qwen tutor turn request failed.") from exc
        finally:
            elapsed = time.perf_counter() - started_at
            logger.info(
                "qwen.tutor_turn_seconds=%.2f model=%s",
                elapsed,
                self.settings.QWEN_CHAT_MODEL,
            )
        return parse_tutor_turn_json(_extract_chat_content(response))

    async def synthesize_speech(self, text: str, output_path: str) -> str | None:
        """Synthesize tutor reply audio through fake mode or DashScope TTS."""
        if self.settings.USE_FAKE_TTS:
            return None

        return await run_dashscope_tts(
            settings=self.settings,
            text=text,
            output_path=output_path,
        )

    def _real_client(self) -> AsyncOpenAI:
        """Validate real-Qwen settings and return an OpenAI-compatible client."""
        missing_settings = [
            name
            for name in ("QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_CHAT_MODEL")
            if not getattr(self.settings, name).strip()
        ]
        if missing_settings:
            missing = ", ".join(missing_settings)
            raise ValueError(
                "Qwen real mode requires QWEN_API_KEY, QWEN_BASE_URL, and "
                f"QWEN_CHAT_MODEL. Missing: {missing}."
            )
        return AsyncOpenAI(
            api_key=self.settings.QWEN_API_KEY,
            base_url=self.settings.QWEN_BASE_URL,
            timeout=self.settings.QWEN_REQUEST_TIMEOUT_SECONDS,
            max_retries=self.settings.QWEN_MAX_RETRIES,
        )


def _tutor_system_prompt() -> str:
    """Return the system prompt for spoken Mandarin tutoring."""
    return (
        "You are SpeakHan, a Mandarin speaking coach for HSK1-HSK6 learners. "
        "You adapt strictly to the learner level supplied in the user prompt. "
        "HSK1 uses short survival phrases, HSK2 uses simple connected sentences, "
        "HSK3 uses longer practical scenario language, HSK4 uses more natural "
        "conversation with correction detail, and HSK5/6 uses nuanced expression, "
        "register, fluency, and idiomatic usage. "
        "You may include brief English explanations only when useful. "
        "You must adapt your reply based on the learner memory. "
        "Keep replies short, spoken, and suitable for text-to-speech."
    )


def _tutor_realtime_system_prompt() -> str:
    """Return stricter realtime tutor prompt rules for TTS-safe streaming."""
    return (
        "You are SpeakHan, a Mandarin speaking coach for HSK1-HSK6 learners. "
        "Your realtime reply will be spoken by text-to-speech. "
        "A short acknowledgement has already been spoken: 我来帮你改一句。 "
        "Do not repeat that acknowledgement. "
        "Sound like a friendly Mandarin tutor in a live call, not a fixed "
        "correction template. "
        "Usually reply with 2 to 4 short spoken sentences and target 6 to 10 "
        "seconds of speech. "
        "Give at most one main correction or natural recast, then ask one "
        "natural follow-up question or repeat prompt. "
        "Avoid always starting with 可以说 or always asking 现在请你说一遍. "
        "Do not over-explain every mistake in the spoken reply; save detailed "
        "feedback, pinyin, and pronunciation notes for the structured analysis "
        "call. "
        "For HSK1-HSK2, be English-friendly with a clear Mandarin practice "
        "phrase. For HSK3, use mixed English/Chinese and simple Mandarin. "
        "For HSK4, use mostly Mandarin with short English only if useful. "
        "For HSK5-HSK6, use Mandarin-first natural correction with minimal "
        "English. "
        "Do not use emoji, markdown, bullet points, parentheses, slash marks, "
        "plus signs, weird symbols, long pinyin blocks, or quote-heavy "
        "explanations. "
        "Avoid nested Chinese quotation marks. "
        "End every sentence with normal Chinese punctuation: 。！？ "
        "Use the provided scenario dynamically; never hardcode one scene. "
        "Do not invent specific dish, item, or place examples unless the learner "
        "mentioned them or the scenario strongly needs a placeholder. "
        "Keep the reply concise, warm, and suitable for sentence-level TTS."
    )


def _qwen_timeout_message(operation: str, settings: Settings) -> str:
    """Return a clear timeout message without exposing credentials."""
    return (
        f"Qwen {operation} request timed out after "
        f"{settings.QWEN_REQUEST_TIMEOUT_SECONDS:.0f} seconds."
    )


async def run_dashscope_asr(settings: Settings, audio_ref: str) -> str:
    """Run DashScope native qwen3-asr-flash and return parsed transcript text."""
    response = await call_dashscope_asr(settings, audio_ref)
    parse_started_at = time.perf_counter()
    try:
        return parse_dashscope_asr_response(response, settings)
    finally:
        logger.info(
            "qwen.asr_parse_seconds=%.2f model=%s",
            time.perf_counter() - parse_started_at,
            settings.QWEN_ASR_MODEL,
        )


async def call_dashscope_asr(settings: Settings, audio_ref: str) -> object:
    """Call DashScope native ASR and return the raw SDK response object."""
    api_key, key_source = _asr_api_key(settings)
    if not settings.QWEN_ASR_MODEL.strip():
        raise ValueError("Qwen ASR requires QWEN_ASR_MODEL.")

    started_at = time.perf_counter()
    logger.info(
        "qwen.asr_request_start model=%s key_source=%s asr_base_url_set=%s audio_ref_mode=%s",
        settings.QWEN_ASR_MODEL,
        key_source,
        bool(settings.QWEN_ASR_BASE_URL.strip()),
        settings.QWEN_ASR_AUDIO_REF_MODE,
    )
    try:
        # qwen3-asr-flash uses DashScope native MultiModalConversation, not
        # OpenAI-compatible /audio/transcriptions.
        response = await asyncio.to_thread(
            dashscope.MultiModalConversation.call,
            api_key=api_key,
            model=settings.QWEN_ASR_MODEL,
            messages=[
                {"role": "system", "content": [{"text": ""}]},
                {"role": "user", "content": [{"audio": audio_ref}]},
            ],
            result_format="message",
            asr_options={
                "enable_lid": settings.QWEN_ASR_ENABLE_LID,
                "enable_itn": settings.QWEN_ASR_ENABLE_ITN,
                "language": settings.QWEN_ASR_LANGUAGE,
            },
            request_timeout=settings.QWEN_ASR_REQUEST_TIMEOUT_SECONDS,
            **_dashscope_base_address_kwargs(settings),
        )
    except (DashScopeException, RequestException) as exc:
        logger.warning(
            "qwen.asr_dashscope_exception model=%s key_source=%s details=%s",
            settings.QWEN_ASR_MODEL,
            key_source,
            _safe_error_detail(str(exc), settings),
        )
        raise ValueError("Qwen ASR DashScope request failed.") from exc
    finally:
        elapsed = time.perf_counter() - started_at
        logger.info(
            "qwen.asr_seconds=%.2f model=%s",
            elapsed,
            settings.QWEN_ASR_MODEL,
        )
    return response


def _asr_api_key(settings: Settings) -> tuple[str, str]:
    """Return the ASR API key and safe source name using documented precedence."""
    if settings.DASHSCOPE_API_KEY.strip():
        return settings.DASHSCOPE_API_KEY, "DASHSCOPE_API_KEY"
    if settings.QWEN_API_KEY.strip():
        return settings.QWEN_API_KEY, "QWEN_API_KEY"
    raise ValueError("Qwen ASR requires DASHSCOPE_API_KEY or QWEN_API_KEY.")


def _tts_api_key(settings: Settings) -> tuple[str, str]:
    """Return the TTS API key and safe source name using documented precedence."""
    if settings.DASHSCOPE_API_KEY.strip():
        return settings.DASHSCOPE_API_KEY, "DASHSCOPE_API_KEY"
    if settings.QWEN_API_KEY.strip():
        return settings.QWEN_API_KEY, "QWEN_API_KEY"
    raise ValueError("Qwen TTS requires DASHSCOPE_API_KEY or QWEN_API_KEY.")


async def run_dashscope_tts(settings: Settings, text: str, output_path: str) -> str:
    """Run DashScope CosyVoice TTS and save returned audio bytes locally."""
    return await asyncio.to_thread(_run_dashscope_tts_sync, settings, text, output_path)


def _run_dashscope_tts_sync(settings: Settings, text: str, output_path: str) -> str:
    """Call DashScope non-streaming TTS and write the generated audio file."""
    tts_base_url = _tts_base_url(settings)
    api_key, key_source = _tts_api_key(settings)
    model = settings.QWEN_TTS_MODEL.strip()
    voice = settings.QWEN_TTS_VOICE.strip()
    output_format = _tts_output_format(settings)
    if not model:
        raise ValueError("Qwen TTS requires QWEN_TTS_MODEL.")
    if not voice:
        raise ValueError("Qwen TTS requires QWEN_TTS_VOICE.")
    if not text.strip():
        raise ValueError("Qwen TTS text was empty.")

    started_at = time.perf_counter()
    logger.info(
        "qwen.tts_request model=%s voice=%s key_source=%s tts_base_url_set=%s format=%s",
        model,
        voice,
        key_source,
        bool(settings.QWEN_TTS_BASE_URL.strip()),
        output_format,
    )
    previous_api_key = getattr(dashscope, "api_key", None)
    try:
        # Qwen Cloud's CosyVoice example uses tts_v2.SpeechSynthesizer.call()
        # and returns complete audio bytes; no streaming mode is requested.
        dashscope.api_key = api_key
        synthesizer = SpeechSynthesizer(
            model=model,
            voice=voice,
            format=_tts_audio_format(settings),
            url=tts_base_url,
        )
        audio_bytes = synthesizer.call(text)
        if not audio_bytes:
            raise RuntimeError("Qwen TTS response audio data was empty.")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
    except (
        AttributeError,
        DashScopeException,
        RequestException,
        RuntimeError,
        OSError,
        TypeError,
    ) as exc:
        logger.warning(
            "qwen.tts_dashscope_exception model=%s key_source=%s details=%s",
            model,
            key_source,
            _safe_error_detail(str(exc), settings),
        )
        raise ValueError("Qwen TTS request failed.") from exc
    finally:
        dashscope.api_key = previous_api_key
        elapsed = time.perf_counter() - started_at
        logger.info("qwen.tts_seconds=%.2f model=%s", elapsed, model)
    return str(path)


def _tts_output_format(settings: Settings) -> str:
    """Return a browser-friendly TTS output format supported by the MVP."""
    output_format = settings.QWEN_TTS_OUTPUT_FORMAT.strip().lower() or "mp3"
    if output_format not in SUPPORTED_TTS_OUTPUT_FORMATS:
        raise ValueError("QWEN_TTS_OUTPUT_FORMAT must be one of: mp3, wav.")
    return output_format


def _tts_base_url(settings: Settings) -> str | None:
    """Return a validated optional DashScope TTS websocket base URL."""
    tts_base_url = settings.QWEN_TTS_BASE_URL.strip()
    if not tts_base_url:
        return None
    if tts_base_url.startswith(("ws://", "wss://")):
        return tts_base_url
    raise ValueError(
        "QWEN_TTS_BASE_URL must be blank or a websocket URL starting with "
        "ws:// or wss://."
    )


def _tts_audio_format(settings: Settings) -> AudioFormat:
    """Map the configured MVP audio extension to DashScope's TTS enum."""
    output_format = _tts_output_format(settings)
    if output_format == "wav":
        return AudioFormat.WAV_24000HZ_MONO_16BIT
    return AudioFormat.MP3_24000HZ_MONO_256KBPS


def _dashscope_base_address_kwargs(settings: Settings) -> dict[str, str]:
    """Return request-level DashScope base URL override when configured."""
    if not settings.QWEN_ASR_BASE_URL.strip():
        return {}
    return {"base_address": settings.QWEN_ASR_BASE_URL.strip()}


def _audio_size_for_log(audio_path: str) -> int | str:
    """Return an audio byte count for diagnostics without logging local paths."""
    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        return "unavailable"
    return path.stat().st_size


async def build_asr_audio_ref(audio_path: str, settings: Settings) -> str:
    """Build the audio reference passed to DashScope ASR without blocking."""
    path = Path(audio_path)
    if not path.exists():
        raise ValueError("Audio file for Qwen ASR was not found.")
    if not path.is_file():
        raise ValueError("Audio file for Qwen ASR was not a regular file.")

    started_at = time.perf_counter()
    audio_ref_mode = settings.QWEN_ASR_AUDIO_REF_MODE.strip().lower()
    logger.info(
        "qwen.asr_prepare_audio_ref_start audio_ref_mode=%s bytes=%s",
        audio_ref_mode,
        path.stat().st_size,
    )
    try:
        if audio_ref_mode == "oss_url":
            upload_started_at = time.perf_counter()
            result = await asyncio.to_thread(upload_audio_to_oss, str(path), settings)
            logger.info(
                "qwen.asr_upload_seconds=%.2f provider=oss bytes=%s",
                time.perf_counter() - upload_started_at,
                path.stat().st_size,
            )
            logger.info("qwen.asr_oss_object_key=%s", result.object_key)
            return result.url
        if audio_ref_mode == "s3_url":
            upload_started_at = time.perf_counter()
            result = await asyncio.to_thread(upload_audio_to_s3, str(path), settings)
            logger.info(
                "qwen.asr_upload_seconds=%.2f provider=s3 bytes=%s",
                time.perf_counter() - upload_started_at,
                path.stat().st_size,
            )
            logger.info("qwen.asr_s3_object_key=%s", result.object_key)
            return result.url
        if audio_ref_mode == "public_url":
            return _public_audio_url(str(path), settings)
        if audio_ref_mode == "local_path":
            return str(path)
        if audio_ref_mode == "file_url":
            return path.resolve().as_uri()
        raise ValueError(
            "QWEN_ASR_AUDIO_REF_MODE must be one of: oss_url, s3_url, public_url, "
            "local_path, file_url."
        )
    finally:
        logger.info(
            "qwen.asr_prepare_audio_ref_seconds=%.2f audio_ref_mode=%s",
            time.perf_counter() - started_at,
            audio_ref_mode,
        )


def _build_asr_audio_ref(audio_path: str, settings: Settings) -> str:
    """Build non-OSS ASR audio references for tests and diagnostics."""
    path = Path(audio_path)
    if not path.exists():
        raise ValueError("Audio file for Qwen ASR was not found.")
    if not path.is_file():
        raise ValueError("Audio file for Qwen ASR was not a regular file.")

    audio_ref_mode = settings.QWEN_ASR_AUDIO_REF_MODE.strip().lower()
    if audio_ref_mode == "public_url":
        return _public_audio_url(str(path), settings)
    if audio_ref_mode == "local_path":
        return str(path)
    if audio_ref_mode == "file_url":
        return path.resolve().as_uri()
    if audio_ref_mode == "oss_url":
        raise ValueError("Use build_asr_audio_ref for QWEN_ASR_AUDIO_REF_MODE=oss_url.")
    if audio_ref_mode == "s3_url":
        raise ValueError("Use build_asr_audio_ref for QWEN_ASR_AUDIO_REF_MODE=s3_url.")
    raise ValueError(
        "QWEN_ASR_AUDIO_REF_MODE must be one of: oss_url, s3_url, public_url, "
        "local_path, file_url."
    )


def _public_audio_url(audio_path: str, settings: Settings) -> str:
    """Build a public URL for a stored audio file served by the backend."""
    if not settings.PUBLIC_BACKEND_BASE_URL.strip():
        raise ValueError(
            "PUBLIC_BACKEND_BASE_URL is required for "
            "QWEN_ASR_AUDIO_REF_MODE=public_url."
        )
    relative_storage_url = storage_url(audio_path, settings.STORAGE_DIR)
    return _join_url(settings.PUBLIC_BACKEND_BASE_URL, relative_storage_url)


def _join_url(base_url: str, path: str) -> str:
    """Join a public base URL and path without accidental double slashes."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def parse_dashscope_asr_response(response: object, settings: Settings) -> str:
    """Parse a DashScope ASR response and return transcript text."""
    status_code = _response_value(response, "status_code")
    if status_code is not None and int(status_code) != 200:
        raise ValueError(_dashscope_asr_failure_message(response, settings))

    output = _response_value(response, "output")
    transcript = _extract_asr_transcript(output)
    if transcript:
        return transcript

    transcript = _extract_asr_transcript(response)
    if transcript:
        return transcript
    raise ValueError("Qwen ASR response transcript was empty.")


def _dashscope_asr_failure_message(response: object, settings: Settings) -> str:
    """Build a safe, useful error message from a failed DashScope response."""
    status_code = _response_value(response, "status_code")
    code = _response_value(response, "code")
    request_id = _response_value(response, "request_id")
    message = _safe_error_detail(_response_value(response, "message"), settings)
    parts = [f"status_code={status_code}"]
    if code:
        parts.append(f"code={code}")
    if request_id:
        parts.append(f"request_id={request_id}")
    if message:
        parts.append(f"message={message}")

    guidance = ""
    if code == "InvalidApiKey":
        guidance = (
            " Check whether DASHSCOPE_API_KEY/QWEN_API_KEY matches the "
            "DashScope native ASR endpoint and whether QWEN_ASR_BASE_URL is correct."
        )
    return f"Qwen ASR request failed with {' '.join(parts)}.{guidance}"


def _response_value(value: object, key: str) -> object:
    """Read a field from DashScope response objects and dict-like payloads."""
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _log_openai_error(
    operation: str,
    exc: OpenAIError,
    model: str,
    settings: Settings,
) -> None:
    """Log safe OpenAI error details for local debugging without secrets."""
    details = {
        "error_type": type(exc).__name__,
        "status_code": getattr(exc, "status_code", None),
        "code": getattr(exc, "code", None),
        "message": _safe_error_detail(_openai_error_message(exc), settings),
        "body": _safe_error_detail(getattr(exc, "body", None), settings),
    }
    safe_details = {
        key: value
        for key, value in details.items()
        if value not in (None, "", {}, [])
    }
    logger.warning(
        "qwen.%s_openai_error model=%s details=%s",
        operation,
        model,
        safe_details,
    )


def _openai_error_message(exc: OpenAIError) -> str:
    """Return the most useful OpenAI error message available."""
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message
    return str(exc)


def _safe_error_detail(value: object, settings: Settings) -> object:
    """Redact configured secrets and keep logged error details compact."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {
            str(key): _safe_error_detail(nested_value, settings)
            for key, nested_value in value.items()
            if str(key).lower() not in {"authorization", "api_key", "api-key"}
        }
    if isinstance(value, list):
        return [_safe_error_detail(item, settings) for item in value[:5]]

    text = str(value)
    if settings.QWEN_API_KEY:
        text = text.replace(settings.QWEN_API_KEY, "[redacted]")
    if settings.DASHSCOPE_API_KEY:
        text = text.replace(settings.DASHSCOPE_API_KEY, "[redacted]")
    if settings.ALIBABA_OSS_ACCESS_KEY_ID:
        text = text.replace(settings.ALIBABA_OSS_ACCESS_KEY_ID, "[redacted]")
    if settings.ALIBABA_OSS_ACCESS_KEY_SECRET:
        text = text.replace(settings.ALIBABA_OSS_ACCESS_KEY_SECRET, "[redacted]")
    if settings.S3_ACCESS_KEY_ID:
        text = text.replace(settings.S3_ACCESS_KEY_ID, "[redacted]")
    if settings.S3_SECRET_ACCESS_KEY:
        text = text.replace(settings.S3_SECRET_ACCESS_KEY, "[redacted]")
    if len(text) > 500:
        text = f"{text[:500]}..."
    return text


def _turn_system_prompt() -> str:
    """Return the strict combined tutor-turn prompt for one-call voice chat."""
    allowed_types = ", ".join(mistake_type.value for mistake_type in MistakeType)
    allowed_categories = ", ".join(category.value for category in WeaknessCategory)
    return dedent(
        f"""
        You are SpeakHan, a Mandarin speaking coach for HSK1-HSK6 learners.
        Return JSON only, with no markdown and no extra text.
        The response must include:
        - tutor_reply: a short spoken tutor reply adapted to the learner HSK level,
          with brief English only when useful.
        - feedback: structured Mandarin mistake analysis adapted to the learner
          HSK level.
        Level rules:
        {_level_guidance_text()}
        Allowed mistake types: {allowed_types}.
        Allowed weakness categories: {allowed_categories}.
        The JSON must match this exact shape:
        {json.dumps(TURN_JSON_EXAMPLE, ensure_ascii=False, indent=2)}
        Keep tutor_reply short and suitable for text-to-speech.
        Severity must be an integer from 1 to 5.
        Scores must be integers from 0 to 100.
        """
    ).strip()


def _tutor_user_prompt(
    transcript: str,
    memory: MemoryResponse,
    scenario: str,
    level: str,
) -> str:
    """Build a compact tutor prompt from transcript, scenario, and memory."""
    weaknesses = [
        {
            "category": weakness.weakness_category.value,
            "name": weakness.weakness_name,
            "severity_score": weakness.severity_score,
            "recommended_drill": weakness.recommended_drill,
        }
        for weakness in memory.active_weaknesses
    ]
    latest_lesson_plan = (
        memory.latest_lesson_plan.model_dump(mode="json")
        if memory.latest_lesson_plan is not None
        else None
    )
    return dedent(
        f"""
        Learner level: {level}
        Scenario: {scenario}
        Transcript: {transcript}
        Active weaknesses: {json.dumps(weaknesses, ensure_ascii=False)}
        Latest lesson plan: {json.dumps(latest_lesson_plan, ensure_ascii=False)}
        Level guidance: {_level_guidance(level)}

        Reply as the Mandarin tutor. Make the learner feel guided, remember their
        weaknesses if present, and give one short next speaking prompt.
        """
    ).strip()


def _tutor_realtime_user_prompt(
    transcript: str,
    memory: MemoryResponse,
    scenario: str,
    level: str,
) -> str:
    """Build a concise realtime tutor prompt optimized for TTS chunking."""
    tutor_context = _tutor_user_prompt(
        transcript=transcript,
        memory=memory,
        scenario=scenario,
        level=level,
    )
    return dedent(
        f"""
        {tutor_context}

        Realtime TTS constraints:
        - A short acknowledgement has already been spoken: 我来帮你改一句。
        - Do not repeat that acknowledgement.
        - Sound like a friendly Mandarin tutor in a live call, not a fixed template.
        - Usually reply with 2 to 4 short spoken sentences.
        - Target around 6 to 10 seconds of spoken audio.
        - Give at most one main correction or natural recast.
        - Ask one natural follow-up question or repeat prompt.
        - Avoid repetitive templates like always starting with 可以说 or always
          saying 现在请你说一遍.
        - Do not use emoji, markdown, bullets, parentheses, slash marks, plus signs,
          tables, headings, long pinyin blocks, or quote-heavy examples.
        - Avoid nested Chinese quotation marks, lecture-style explanations, and
          multiple teaching points.
        - End each sentence with normal Chinese punctuation: 。！？
        - HSK1-HSK2: English-friendly, with one clear Mandarin practice phrase.
        - HSK3: mixed English/Chinese, simple Mandarin.
        - HSK4: mostly Mandarin, short English only if useful.
        - HSK5-HSK6: Mandarin-first, natural correction, minimal English.
        - Use the provided scenario dynamically: {scenario}.
        - Do not invent specific dish, item, or place examples unless the learner
          mentioned them or the scenario strongly needs a placeholder.
        - Save detailed mistake explanations, pinyin, and pronunciation/tone notes
          for the structured feedback call.

        Give one natural correction/recast and one conversational next turn.
        """
    ).strip()


def _turn_user_prompt(
    transcript: str,
    memory: MemoryResponse,
    scenario: str,
    level: str,
) -> str:
    """Build the combined tutor-reply and analysis prompt."""
    tutor_context = _tutor_user_prompt(
        transcript=transcript,
        memory=memory,
        scenario=scenario,
        level=level,
    )
    return dedent(
        f"""
        {tutor_context}

        Also analyze this response for Mandarin pronunciation, tone, vocabulary,
        grammar, fluency, and hesitation weaknesses. Return only valid JSON with
        tutor_reply and feedback.
        """
    ).strip()


def _analysis_system_prompt() -> str:
    """Return the strict JSON schema prompt for mistake analysis."""
    allowed_types = ", ".join(mistake_type.value for mistake_type in MistakeType)
    allowed_categories = ", ".join(category.value for category in WeaknessCategory)
    return dedent(
        f"""
        You analyze Mandarin speaking practice for SpeakHan learners from HSK1
        through HSK6.
        Return JSON only, with no markdown and no extra text.
        Adapt feedback to the supplied level. Lower HSK feedback should focus on
        pronunciation, tones, survival vocabulary, and simple grammar. Higher HSK
        feedback should focus on fluency, word choice, naturalness, discourse
        structure, register, and idiomatic usage.
        Allowed mistake types: {allowed_types}.
        Allowed weakness categories: {allowed_categories}.
        The JSON must match this exact shape:
        {json.dumps(ANALYSIS_JSON_EXAMPLE, ensure_ascii=False, indent=2)}
        Optional frontend correction-card fields may be null or omitted:
        target_pinyin, heard_pinyin, problem_sound, problem_tone,
        display_correction.
        When identifying pronunciation or tone issues, include pinyin with tone
        marks when helpful. Use problem_sound for issues like sh/s, zh/ch, r/l,
        or finals. Use problem_tone for tone numbers or tone patterns. If ASR
        appears to confuse contextually similar characters such as 是 and 市,
        distinguish likely transcript/context confusion from a real
        pronunciation issue instead of overclaiming.
        Severity must be an integer from 1 to 5.
        Scores must be integers from 0 to 100.
        If the answer is mostly correct, include at least one useful fluency or
        vocabulary coaching point.
        """
    ).strip()


def _analysis_user_prompt(transcript: str, scenario: str, level: str) -> str:
    """Build the user prompt for structured Mandarin mistake analysis."""
    return dedent(
        f"""
        Learner level: {level}
        Scenario: {scenario}
        Transcript: {transcript}
        Level guidance: {_level_guidance(level)}

        Analyze this response for Mandarin pronunciation, tone, vocabulary,
        grammar, fluency, and hesitation weaknesses. Include pinyin, problem
        sounds, problem tones, and a display correction when useful for a
        frontend correction card. Return only valid JSON.
        """
    ).strip()


def _fake_tutor_reply(
    transcript: str,
    memory: MemoryResponse,
    scenario: str,
    level: str,
) -> str:
    """Return the stable fake tutor reply used by tests and local demos."""
    level_prompt = _fake_level_prompt(level)
    if memory.active_weaknesses:
        weakness_names = "、".join(
            weakness.weakness_name for weakness in memory.active_weaknesses[:3]
        )
        return (
            f"欢迎回来！我记得你之前需要练习 {weakness_names}。"
            f"我们先热身，然后继续{scenario}练习。{level_prompt}"
        )

    return (
        f"很好！你说的是：{transcript}。我们现在练习{scenario}。"
        f"{level_prompt}"
    )


def _fake_analysis(transcript: str, scenario: str, level: str) -> AnalysisResponse:
    """Return the stable fake structured feedback for tests and local demos."""
    next_focus, next_drill, fluency_drill = _fake_analysis_drills(level)
    mistakes = [
        MistakeAnalysis(
            type=MistakeType.PRONUNCIATION,
            weakness_category=WeaknessCategory.ZH_CH_CONFUSION,
            target="中国菜 / 吃",
            target_pinyin="Zhōngguó cài / chī",
            problem_sound="zh/ch",
            display_correction="中国菜 zhōngguó cài；吃 chī",
            severity=4,
            feedback="Practice separating zh in 中国 from ch in 吃.",
            example_sentence="我想吃中国菜。",
            recommended_drill="Repeat 中国菜 and 想吃 slowly, then in a full sentence.",
        ),
        MistakeAnalysis(
            type=MistakeType.FLUENCY,
            weakness_category=WeaknessCategory.SENTENCE_LENGTH,
            target="short answer",
            severity=3,
            feedback="Try answering with a complete sentence instead of a short phrase.",
            example_sentence="我想吃中国菜，也想喝茶。",
            recommended_drill=fluency_drill,
        ),
    ]
    return AnalysisResponse(
        mistakes=mistakes,
        fluency_score=65,
        confidence_score=60,
        summary=f"Fake analysis for {level} {scenario}: {transcript}",
        next_focus=next_focus,
        next_drill=next_drill,
    )


def _extract_chat_content(response: object) -> str:
    """Extract text content from an OpenAI-compatible chat completion response."""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise ValueError("Qwen response did not include a chat message.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Qwen response content was empty.")
    return content.strip()


def _extract_stream_delta(chunk: object) -> str:
    """Extract a text delta from one OpenAI-compatible streaming chunk."""
    try:
        delta = chunk.choices[0].delta
    except (AttributeError, IndexError):
        return ""
    content = getattr(delta, "content", None)
    if isinstance(content, str):
        return content
    return ""


def _fake_stream_chunks(text: str) -> list[str]:
    """Return deterministic fake streaming chunks for tests and local demos."""
    chunk_size = 8
    return [
        text[index : index + chunk_size]
        for index in range(0, len(text), chunk_size)
    ]


def _level_guidance(level: str) -> str:
    """Return the HSK adaptation rule that best matches a learner level."""
    normalized_level = level.lower()
    if "hsk6" in normalized_level or "hsk5" in normalized_level:
        return (
            "Use nuanced expressions, fluency coaching, register, idiomatic usage, "
            "word choice, sentence naturalness, and discourse structure."
        )
    if "hsk4" in normalized_level:
        return (
            "Use more natural conversation, connected correction detail, and "
            "practical grammar explanations."
        )
    if "hsk3" in normalized_level:
        return (
            "Use longer practical sentences, scenario vocabulary, and manageable "
            "follow-up questions."
        )
    if "hsk2" in normalized_level:
        return (
            "Use simple connected sentences, basic question patterns, and everyday "
            "vocabulary."
        )
    return (
        "Use short simple survival phrases, pronunciation and tone coaching, "
        "survival vocabulary, and simple grammar."
    )


def _level_guidance_text() -> str:
    """Return compact HSK level rules for Qwen system prompts."""
    return (
        "HSK1: short, simple survival phrases. "
        "HSK2: simple connected sentences and basic question patterns. "
        "HSK3: longer practical sentences and more scenario vocabulary. "
        "HSK4: natural conversation and more correction detail. "
        "HSK5/6: nuanced expressions, fluency, register, idiomatic usage, word "
        "choice, naturalness, and discourse structure."
    )


def _fake_level_prompt(level: str) -> str:
    """Return a deterministic fake next prompt that is not locked to HSK1."""
    normalized_level = level.lower()
    if "hsk6" in normalized_level or "hsk5" in normalized_level:
        return "你可以继续说：这家餐厅的口味很地道，不过价格稍微有点高。"
    if "hsk4" in normalized_level:
        return "你可以继续说：请问你们有什么推荐的特色菜？"
    if "hsk3" in normalized_level:
        return "你可以继续说：我想点一份中国菜，还想要一杯热茶。"
    if "hsk2" in normalized_level:
        return "你可以继续说：我想吃饭，也想喝茶。"
    return "你可以继续说：我想喝茶。"


def _fake_analysis_drills(level: str) -> tuple[str, str, str]:
    """Return deterministic fake feedback drills adapted to learner level."""
    normalized_level = level.lower()
    if "hsk6" in normalized_level or "hsk5" in normalized_level:
        return (
            "restaurant ordering with natural register and nuanced word choice",
            "Practice 地道, 口味偏淡, 性价比, and 更符合我的口味.",
            "Extend answers with nuanced preference and register choices.",
        )
    if "hsk4" in normalized_level:
        return (
            "restaurant ordering with natural follow-up questions",
            "Practice 特色菜, 推荐, 口味, and 请问你们有什么推荐.",
            "Extend answers with reasons and polite follow-up questions.",
        )
    if "hsk3" in normalized_level:
        return (
            "restaurant ordering with fuller practical sentences",
            "Practice 一份中国菜, 还想要一杯热茶, 一共多少钱.",
            "Extend answers with 一份, 还想要, 一共多少钱, and 因为.",
        )
    if "hsk2" in normalized_level:
        return (
            "restaurant ordering with simple connected sentences",
            "Practice 我想吃饭, 也想喝茶, 你有中国菜吗.",
            "Extend answers with 也想, 有吗, and simple question patterns.",
        )
    return (
        "restaurant ordering with clearer zh/ch sounds and fuller answers",
        "Practice 中国菜, 想吃, 多少钱, and 我想喝茶.",
        "Extend answers with 也想, 多少钱, and 我喜欢.",
    )


def _extract_asr_transcript(response: object) -> str:
    """Extract transcript text from common DashScope ASR response shapes."""
    content = _dashscope_content(response)
    if content is not None:
        return _text_from_content(content)

    text = _response_value(response, "text")
    if isinstance(text, str):
        return text.strip()
    return ""


def _dashscope_content(response: object) -> object:
    """Return message content from DashScope output choices when present."""
    output = _response_value(response, "output") or response
    choices = _response_value(output, "choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    message = _response_value(first_choice, "message")
    if message is None:
        return _response_value(first_choice, "content")
    return _response_value(message, "content")


def _text_from_content(content: object) -> str:
    """Extract ASR transcript text from DashScope content string or list."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = [
            str(text).strip()
            for item in content
            if (text := _response_value(item, "text")) is not None
        ]
        return " ".join(part for part in text_parts if part).strip()
    text = _response_value(content, "text")
    if isinstance(text, str):
        return text.strip()
    return ""


def strip_json_code_fence(content: str) -> str:
    """Strip optional markdown JSON fences from Qwen structured output."""
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return stripped
    first_line = lines[0].strip().lower()
    if first_line not in ("```", "```json"):
        return stripped
    return "\n".join(lines[1:-1]).strip()


def parse_analysis_json(content: str) -> AnalysisResponse:
    """Parse Qwen JSON content and validate it against AnalysisResponse."""
    json_content = strip_json_code_fence(content)
    try:
        payload = json.loads(json_content)
    except json.JSONDecodeError as exc:
        raise ValueError("Qwen analysis response was not valid JSON.") from exc

    try:
        return AnalysisResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            "Qwen analysis response did not match the expected schema or enums."
        ) from exc


def parse_tutor_turn_json(content: str) -> tuple[str, AnalysisResponse]:
    """Parse combined Qwen turn JSON into tutor reply and feedback schema."""
    json_content = strip_json_code_fence(content)
    try:
        payload = json.loads(json_content)
    except json.JSONDecodeError as exc:
        raise ValueError("Qwen tutor turn response was not valid JSON.") from exc

    tutor_reply = payload.get("tutor_reply") if isinstance(payload, dict) else None
    if not isinstance(tutor_reply, str) or not tutor_reply.strip():
        raise ValueError("Qwen tutor turn response was missing tutor_reply.")

    feedback = payload.get("feedback") if isinstance(payload, dict) else None
    if feedback is None:
        raise ValueError("Qwen tutor turn response was missing feedback.")

    try:
        analysis = AnalysisResponse.model_validate(feedback)
    except ValidationError as exc:
        raise ValueError(
            "Qwen tutor turn feedback did not match the expected schema or enums."
        ) from exc
    return tutor_reply.strip(), analysis
