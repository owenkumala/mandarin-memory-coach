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
    parse_tutor_turn_json,
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


def _valid_feedback_json() -> str:
    """Return valid feedback JSON content for parser tests."""
    return """
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
"""


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


def test_generate_tutor_turn_fake_mode_returns_reply_and_analysis() -> None:
    """Combined turn generation keeps fake mode deterministic."""
    client = QwenClient(settings=Settings(USE_FAKE_QWEN=True))

    tutor_reply, analysis = asyncio.run(
        client.generate_tutor_turn(
            transcript="我想吃中国菜",
            memory=_empty_memory(),
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


def test_generate_tutor_turn_real_mode_missing_api_key_raises_value_error() -> None:
    """Combined real mode validates required Qwen settings before calls."""
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
            client.generate_tutor_turn(
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


def test_generate_tutor_turn_openai_error_becomes_value_error() -> None:
    """Combined Qwen request OpenAIError is converted into ValueError."""
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

    with pytest.raises(ValueError, match="Qwen tutor turn request failed."):
        asyncio.run(
            client.generate_tutor_turn(
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
    fenced_json = f"""```json
{_valid_feedback_json().strip()}
```"""

    analysis = parse_analysis_json(fenced_json)

    assert strip_json_code_fence(fenced_json).startswith("{")
    assert analysis.mistakes[0].target == "中国菜 / 吃"
    assert analysis.next_focus == "Practice zh/ch sounds."


def test_combined_json_parsing_works_with_valid_json() -> None:
    """Combined tutor turn JSON validates tutor reply and feedback."""
    content = f"""
{{
  "tutor_reply": "很好！现在请说：请给我一份中国菜。",
  "feedback": {_valid_feedback_json()}
}}
"""

    tutor_reply, analysis = parse_tutor_turn_json(content)

    assert tutor_reply == "很好！现在请说：请给我一份中国菜。"
    assert analysis.mistakes[0].target == "中国菜 / 吃"


def test_combined_json_parsing_works_with_code_fence() -> None:
    """Combined tutor turn JSON handles optional markdown code fences."""
    content = f"""```json
{{
  "tutor_reply": "很好！现在请说：请给我一份中国菜。",
  "feedback": {_valid_feedback_json()}
}}
```"""

    tutor_reply, analysis = parse_tutor_turn_json(content)

    assert tutor_reply.startswith("很好")
    assert analysis.next_focus == "Practice zh/ch sounds."


def test_combined_json_missing_tutor_reply_raises_value_error() -> None:
    """Combined parser rejects missing tutor_reply."""
    content = f"""
{{
  "feedback": {_valid_feedback_json()}
}}
"""

    with pytest.raises(ValueError, match="missing tutor_reply"):
        parse_tutor_turn_json(content)


def test_combined_json_missing_feedback_raises_value_error() -> None:
    """Combined parser rejects missing feedback."""
    with pytest.raises(ValueError, match="missing feedback"):
        parse_tutor_turn_json('{"tutor_reply": "很好！"}')


def test_combined_json_invalid_feedback_enum_raises_value_error() -> None:
    """Combined parser rejects invalid feedback schema or enum values."""
    content = """
{
  "tutor_reply": "很好！",
  "feedback": {
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
}
"""

    with pytest.raises(ValueError, match="feedback did not match"):
        parse_tutor_turn_json(content)


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
