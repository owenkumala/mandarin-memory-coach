"""Unit tests for fake and real-mode Qwen client helpers."""

import asyncio
from unittest.mock import AsyncMock, Mock

from openai import APIConnectionError
import pytest

from app.core.config import Settings
from app.schemas import AnalysisResponse, MemoryResponse
from app.services.qwen_client import (
    QwenClient,
    parse_analysis_json,
    strip_json_code_fence,
)


def _empty_memory() -> MemoryResponse:
    """Return minimal learner memory for Qwen client unit tests."""
    return MemoryResponse(
        user_id="demo-user",
        learner_level="HSK1 beginner",
        native_language="Indonesian",
        active_weaknesses=[],
        recent_sessions=[],
        latest_lesson_plan=None,
    )


def test_fake_mode_still_returns_fake_reply_and_analysis() -> None:
    """Fake mode keeps the no-credential tutor and analysis behavior."""
    client = QwenClient(settings=Settings(USE_FAKE_QWEN=True))

    tutor_reply = asyncio.run(
        client.generate_tutor_reply(
            transcript="我想吃中国菜",
            memory=_empty_memory(),
            scenario="restaurant ordering",
            level="HSK1 beginner",
        )
    )
    analysis = asyncio.run(
        client.analyze_mistakes(
            transcript="我想吃中国菜",
            scenario="restaurant ordering",
            level="HSK1 beginner",
        )
    )

    assert "很好" in tutor_reply
    assert isinstance(analysis, AnalysisResponse)
    assert analysis.mistakes[0].weakness_category.value == "zh_ch_confusion"


def test_real_mode_missing_api_key_raises_useful_value_error() -> None:
    """Real mode validates required Qwen settings before network calls."""
    client = QwenClient(
        settings=Settings(
            USE_FAKE_QWEN=False,
            QWEN_API_KEY="",
            QWEN_BASE_URL="https://example.com/compatible-mode/v1",
            QWEN_CHAT_MODEL="qwen-plus",
        )
    )

    with pytest.raises(ValueError, match="Missing: QWEN_API_KEY"):
        asyncio.run(
            client.generate_tutor_reply(
                transcript="我想吃中国菜",
                memory=_empty_memory(),
                scenario="restaurant ordering",
                level="HSK1 beginner",
            )
        )


def test_tutor_reply_openai_error_becomes_value_error() -> None:
    """Real tutor request OpenAIError is converted into a useful ValueError."""
    client = QwenClient(
        settings=Settings(
            USE_FAKE_QWEN=False,
            QWEN_API_KEY="test-key",
            QWEN_BASE_URL="https://example.com/compatible-mode/v1",
            QWEN_CHAT_MODEL="qwen-plus",
        )
    )
    mock_qwen = Mock()
    mock_qwen.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=Mock())
    )
    client._real_client = Mock(return_value=mock_qwen)

    with pytest.raises(ValueError, match="Qwen tutor reply request failed."):
        asyncio.run(
            client.generate_tutor_reply(
                transcript="我想吃中国菜",
                memory=_empty_memory(),
                scenario="restaurant ordering",
                level="HSK1 beginner",
            )
        )


def test_analysis_openai_error_becomes_value_error() -> None:
    """Real analysis request OpenAIError is converted into a useful ValueError."""
    client = QwenClient(
        settings=Settings(
            USE_FAKE_QWEN=False,
            QWEN_API_KEY="test-key",
            QWEN_BASE_URL="https://example.com/compatible-mode/v1",
            QWEN_CHAT_MODEL="qwen-plus",
        )
    )
    mock_qwen = Mock()
    mock_qwen.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(request=Mock())
    )
    client._real_client = Mock(return_value=mock_qwen)

    with pytest.raises(ValueError, match="Qwen analysis request failed."):
        asyncio.run(
            client.analyze_mistakes(
                transcript="我想吃中国菜",
                scenario="restaurant ordering",
                level="HSK1 beginner",
            )
        )


def test_json_code_fence_parsing_works() -> None:
    """Qwen JSON output can be parsed even if wrapped in a markdown fence."""
    fenced_json = """```json
{
  "mistakes": [
    {
      "type": "pronunciation",
      "weakness_category": "zh_ch_confusion",
      "target": "中国菜 / 吃",
      "severity": 4,
      "feedback": "Practice separating zh in 中国 from ch in 吃.",
      "example_sentence": "我想吃中国菜。",
      "recommended_drill": "Repeat 中国菜 and 想吃 slowly."
    }
  ],
  "fluency_score": 65,
  "confidence_score": 60,
  "summary": "The learner gave a short restaurant-ordering answer.",
  "next_focus": "Practice zh/ch sounds.",
  "next_drill": "Repeat 中国菜 and 想吃."
}
```"""

    analysis = parse_analysis_json(fenced_json)

    assert strip_json_code_fence(fenced_json).startswith("{")
    assert analysis.mistakes[0].target == "中国菜 / 吃"
    assert analysis.next_focus == "Practice zh/ch sounds."


def test_invalid_analysis_json_raises_useful_error() -> None:
    """Invalid JSON is reported as a Qwen analysis parsing error."""
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_analysis_json("not json")


def test_invalid_analysis_enum_raises_useful_error() -> None:
    """Invalid enum values are rejected by AnalysisResponse validation."""
    invalid_enum_json = """
{
  "mistakes": [
    {
      "type": "accent",
      "weakness_category": "zh_ch_confusion",
      "target": "中国菜 / 吃",
      "severity": 4,
      "feedback": "Practice separating zh in 中国 from ch in 吃.",
      "example_sentence": "我想吃中国菜。",
      "recommended_drill": "Repeat 中国菜 and 想吃 slowly."
    }
  ],
  "fluency_score": 65,
  "confidence_score": 60,
  "summary": "The learner gave a short answer.",
  "next_focus": "Practice zh/ch sounds.",
  "next_drill": "Repeat 中国菜 and 想吃."
}
"""

    with pytest.raises(ValueError, match="expected schema or enums"):
        parse_analysis_json(invalid_enum_json)
