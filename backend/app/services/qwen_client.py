"""Fake-first Qwen client for ASR, tutor reply, analysis, and TTS.

The class keeps all future Alibaba Cloud Model Studio calls behind one
interface while fake mode makes the memory pipeline testable without secrets.
"""

import json
import logging
import time
from textwrap import dedent

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas import (
    AnalysisResponse,
    MemoryResponse,
    MistakeAnalysis,
    MistakeType,
    WeaknessCategory,
)

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
        """Return a fake transcript until real ASR is integrated later."""
        return "我想吃中国菜"

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
