"""Fake-first Qwen client for ASR, tutor reply, analysis, and TTS.

The class keeps all future Alibaba Cloud Model Studio calls behind one
interface while fake mode makes the memory pipeline testable without secrets.
"""

from app.core.config import Settings
from app.schemas import (
    AnalysisResponse,
    MemoryResponse,
    MistakeAnalysis,
    MistakeType,
    WeaknessCategory,
)


class QwenClient:
    """Client wrapper for Qwen services, currently implemented in fake mode."""

    def __init__(self, settings: Settings) -> None:
        """Store settings so fake and future real modes share one interface."""
        self.settings = settings

    async def transcribe_audio(self, audio_path: str) -> str:
        """Return a transcript for the uploaded audio path."""
        if not self.settings.USE_FAKE_QWEN:
            raise NotImplementedError("Real Qwen ASR is not connected yet.")
        return "我想吃中国菜"

    async def generate_tutor_reply(
        self,
        transcript: str,
        memory: MemoryResponse,
        scenario: str,
        level: str,
    ) -> str:
        """Generate a Mandarin tutor reply using current learner memory."""
        if not self.settings.USE_FAKE_QWEN:
            raise NotImplementedError("Real Qwen chat is not connected yet.")

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

    async def analyze_mistakes(
        self,
        transcript: str,
        scenario: str,
        level: str,
    ) -> AnalysisResponse:
        """Return structured Mandarin feedback with fixed enum categories."""
        if not self.settings.USE_FAKE_QWEN:
            raise NotImplementedError("Real Qwen analysis is not connected yet.")

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

    async def synthesize_speech(self, text: str, output_path: str) -> str | None:
        """Generate tutor speech and return its path when TTS is available."""
        if not self.settings.USE_FAKE_QWEN:
            raise NotImplementedError("Real Qwen TTS is not connected yet.")
        return None
