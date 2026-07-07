"""Fake-first Qwen client for ASR, tutor reply, analysis, and TTS.

The class keeps all future Alibaba Cloud Model Studio calls behind one
interface while fake mode makes the memory pipeline testable without secrets.
"""

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from pathlib import Path
from textwrap import dedent

import dashscope
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
from app.utils.audio import storage_url

logger = logging.getLogger(__name__)

ANALYSIS_JSON_EXAMPLE = {
    "mistakes": [
        {
            "type": "pronunciation",
            "weakness_category": "zh_ch_confusion",
            "target": "中国菜 / 吃",
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
        if self.settings.USE_FAKE_QWEN or self.settings.USE_FAKE_ASR:
            return "我想吃中国菜"

        audio_ref = _build_asr_audio_ref(audio_path, self.settings)
        return await run_dashscope_asr(self.settings, audio_ref)

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
        """Return no tutor audio until real TTS is integrated later."""
        return None

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
        "You are SpeakHan, a Mandarin speaking coach for beginner Mandarin learners. "
        "You speak mainly in simple Mandarin suitable for the learner level. "
        "You may include brief English explanations only when useful. "
        "You must adapt your reply based on the learner memory. "
        "Keep replies short, spoken, and suitable for text-to-speech."
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
    return parse_dashscope_asr_response(response, settings)


async def call_dashscope_asr(settings: Settings, audio_ref: str) -> object:
    """Call DashScope native ASR and return the raw SDK response object."""
    api_key, key_source = _asr_api_key(settings)
    if not settings.QWEN_ASR_MODEL.strip():
        raise ValueError("Qwen ASR requires QWEN_ASR_MODEL.")

    started_at = time.perf_counter()
    logger.info(
        "qwen.asr_request model=%s key_source=%s asr_base_url_set=%s audio_ref_mode=%s",
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


def _dashscope_base_address_kwargs(settings: Settings) -> dict[str, str]:
    """Return request-level DashScope base URL override when configured."""
    if not settings.QWEN_ASR_BASE_URL.strip():
        return {}
    return {"base_address": settings.QWEN_ASR_BASE_URL.strip()}


def _build_asr_audio_ref(audio_path: str, settings: Settings) -> str:
    """Build the audio reference passed to DashScope ASR."""
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
    raise ValueError(
        "QWEN_ASR_AUDIO_REF_MODE must be one of: public_url, local_path, file_url."
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
    if len(text) > 500:
        text = f"{text[:500]}..."
    return text


def _turn_system_prompt() -> str:
    """Return the strict combined tutor-turn prompt for one-call voice chat."""
    allowed_types = ", ".join(mistake_type.value for mistake_type in MistakeType)
    allowed_categories = ", ".join(category.value for category in WeaknessCategory)
    return dedent(
        f"""
        You are SpeakHan, a Mandarin speaking coach for beginner Mandarin learners.
        Return JSON only, with no markdown and no extra text.
        The response must include:
        - tutor_reply: a short spoken tutor reply in simple Mandarin, with brief
          English only when useful.
        - feedback: structured Mandarin mistake analysis.
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

        Reply as the Mandarin tutor. Make the learner feel guided, remember their
        weaknesses if present, and give one short next speaking prompt.
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
        You analyze beginner Mandarin speaking practice for SpeakHan.
        Return JSON only, with no markdown and no extra text.
        Allowed mistake types: {allowed_types}.
        Allowed weakness categories: {allowed_categories}.
        The JSON must match this exact shape:
        {json.dumps(ANALYSIS_JSON_EXAMPLE, ensure_ascii=False, indent=2)}
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

        Analyze this response for Mandarin pronunciation, tone, vocabulary,
        grammar, fluency, and hesitation weaknesses. Return only valid JSON.
        """
    ).strip()


def _fake_tutor_reply(
    transcript: str,
    memory: MemoryResponse,
    scenario: str,
) -> str:
    """Return the stable fake tutor reply used by tests and local demos."""
    if memory.active_weaknesses:
        weakness_names = "、".join(
            weakness.weakness_name for weakness in memory.active_weaknesses[:3]
        )
        return (
            f"欢迎回来！我记得你之前需要练习 {weakness_names}。"
            f"我们先热身，然后继续{scenario}练习。你可以说：我想吃中国菜。"
        )

    return (
        f"很好！你说的是：{transcript}。我们现在练习{scenario}。"
        "你可以继续说：我想喝茶。"
    )


def _fake_analysis(transcript: str, scenario: str, level: str) -> AnalysisResponse:
    """Return the stable fake structured feedback for tests and local demos."""
    mistakes = [
        MistakeAnalysis(
            type=MistakeType.PRONUNCIATION,
            weakness_category=WeaknessCategory.ZH_CH_CONFUSION,
            target="中国菜 / 吃",
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
            recommended_drill="Extend answers with 也想, 多少钱, and 我喜欢.",
        ),
    ]
    return AnalysisResponse(
        mistakes=mistakes,
        fluency_score=65,
        confidence_score=60,
        summary=f"Fake analysis for {level} {scenario}: {transcript}",
        next_focus="restaurant ordering with clearer zh/ch sounds and fuller answers",
        next_drill="Practice 中国菜, 想吃, 多少钱, and 我想喝茶.",
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
