"""Unit tests for fake and real-mode Qwen client helpers."""

import asyncio
from unittest.mock import AsyncMock, Mock

from dashscope.common.error import DashScopeException
from openai import APIConnectionError, APITimeoutError
import pytest

from app.core.config import Settings
from app.schemas import AnalysisResponse, MemoryResponse
from app.services import qwen_client
from app.services.qwen_client import (
    QwenClient,
    _asr_api_key,
    _extract_asr_transcript,
    _safe_error_detail,
    parse_dashscope_asr_response,
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


def test_fake_asr_still_returns_fixed_transcript() -> None:
    """Fake mode keeps ASR deterministic and credential-free."""
    client = QwenClient(settings=Settings(USE_FAKE_QWEN=True))

    transcript = asyncio.run(client.transcribe_audio("anything.webm"))

    assert transcript == "我想吃中国菜"


def test_fake_asr_returns_fixed_transcript_when_qwen_chat_is_real() -> None:
    """USE_FAKE_ASR keeps ASR fake even when chat/feedback are real."""
    client = QwenClient(
        settings=Settings(USE_FAKE_QWEN=False, USE_FAKE_ASR=True)
    )

    transcript = asyncio.run(client.transcribe_audio("anything.webm"))

    assert transcript == "我想吃中国菜"


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


def test_asr_uses_dashscope_api_key_before_qwen_api_key() -> None:
    """ASR prefers DASHSCOPE_API_KEY when both key names are configured."""
    settings = Settings(DASHSCOPE_API_KEY="dash-key", QWEN_API_KEY="qwen-key")

    api_key, key_source = _asr_api_key(settings)

    assert api_key == "dash-key"
    assert key_source == "DASHSCOPE_API_KEY"


def test_asr_falls_back_to_qwen_api_key() -> None:
    """ASR falls back to QWEN_API_KEY for Qwen Cloud key reuse."""
    settings = Settings(DASHSCOPE_API_KEY="", QWEN_API_KEY="qwen-key")

    api_key, key_source = _asr_api_key(settings)

    assert api_key == "qwen-key"
    assert key_source == "QWEN_API_KEY"


def test_asr_missing_both_keys_raises_useful_value_error() -> None:
    """ASR validates that at least one accepted key setting is configured."""
    settings = Settings(DASHSCOPE_API_KEY="", QWEN_API_KEY="")

    with pytest.raises(
        ValueError,
        match="Qwen ASR requires DASHSCOPE_API_KEY or QWEN_API_KEY",
    ):
        _asr_api_key(settings)


def test_real_asr_missing_model_raises_useful_value_error() -> None:
    """Real ASR mode validates model config before any SDK call."""
    with pytest.raises(ValueError, match="Qwen ASR requires QWEN_ASR_MODEL"):
        asyncio.run(
            qwen_client.run_dashscope_asr(
                Settings(
                    USE_FAKE_QWEN=False,
                    USE_FAKE_ASR=False,
                    QWEN_API_KEY="test-key",
                    QWEN_ASR_MODEL="",
                ),
                "sample.webm",
            )
        )


def test_real_asr_success_with_mocked_dashscope_call(tmp_path, monkeypatch) -> None:
    """Real ASR calls DashScope native API through a mocked SDK call."""
    audio_path = tmp_path / "sample.webm"
    audio_path.write_bytes(b"fake audio")
    call_kwargs = {}

    def fake_call(**kwargs):
        """Return a fake DashScope ASR response without live network."""
        call_kwargs.update(kwargs)
        return {
            "status_code": 200,
            "output": {
                "choices": [
                    {"message": {"content": [{"text": " 我想吃中国菜 "}]}}
                ]
            },
        }

    monkeypatch.setattr(
        qwen_client.dashscope.MultiModalConversation,
        "call",
        staticmethod(fake_call),
    )
    client = QwenClient(
        settings=Settings(
            USE_FAKE_QWEN=False,
            USE_FAKE_ASR=False,
            DASHSCOPE_API_KEY="",
            QWEN_API_KEY="test-key",
            QWEN_ASR_MODEL="qwen-asr-test",
            QWEN_ASR_BASE_URL="https://dashscope-intl.aliyuncs.com/api/v1",
        )
    )

    transcript = asyncio.run(client.transcribe_audio(str(audio_path)))

    assert transcript == "我想吃中国菜"
    assert call_kwargs["api_key"] == "test-key"
    assert call_kwargs["model"] == "qwen-asr-test"
    assert call_kwargs["base_address"] == "https://dashscope-intl.aliyuncs.com/api/v1"
    assert call_kwargs["asr_options"]["language"] == "zh"


def test_dashscope_asr_non_200_response_raises_useful_error() -> None:
    """Failed DashScope ASR responses include safe debugging fields."""
    settings = Settings(QWEN_API_KEY="secret-key")

    with pytest.raises(ValueError) as exc_info:
        parse_dashscope_asr_response(
            {
                "status_code": 401,
                "request_id": "req-123",
                "code": "InvalidApiKey",
                "message": "InvalidAPI-key provided for secret-key.",
            },
            settings,
        )

    message = str(exc_info.value)
    assert "status_code=401" in message
    assert "code=InvalidApiKey" in message
    assert "request_id=req-123" in message
    assert "InvalidAPI-key provided for [redacted]." in message
    assert "QWEN_ASR_BASE_URL is correct" in message
    assert "secret-key" not in message


def test_asr_parser_extracts_content_string() -> None:
    """DashScope ASR parser supports string message content."""
    response = {
        "status_code": 200,
        "output": {"choices": [{"message": {"content": " 我想吃中国菜 "}}]},
    }

    assert parse_dashscope_asr_response(response, Settings()) == "我想吃中国菜"


def test_asr_parser_extracts_content_text_list() -> None:
    """DashScope ASR parser supports content lists with text objects."""
    response = {
        "status_code": 200,
        "output": {
            "choices": [
                {"message": {"content": [{"text": "我想"}, {"text": "吃中国菜"}]}}
            ]
        },
    }

    assert parse_dashscope_asr_response(response, Settings()) == "我想 吃中国菜"


def test_asr_parser_extracts_dict_like_output_choices() -> None:
    """DashScope ASR parser supports dict-like output choices."""
    output = {"choices": [{"message": {"content": [{"text": " 我想吃中国菜 "}]}}]}

    assert _extract_asr_transcript(output) == "我想吃中国菜"


def test_asr_empty_transcript_raises_useful_error() -> None:
    """Empty ASR transcripts fail clearly before downstream Qwen calls."""
    with pytest.raises(ValueError, match="transcript was empty"):
        parse_dashscope_asr_response(
            {"status_code": 200, "output": {"choices": [{"message": {"content": ""}}]}},
            Settings(),
        )


def test_safe_error_detail_redacts_configured_api_key() -> None:
    """Logged error details redact configured secrets defensively."""
    settings = Settings(QWEN_API_KEY="secret-key")

    detail = _safe_error_detail(
        {
            "message": "Authorization failed for secret-key",
            "authorization": "Bearer secret-key",
        },
        settings,
    )

    assert detail == {"message": "Authorization failed for [redacted]"}


def test_dashscope_asr_exception_becomes_value_error(monkeypatch) -> None:
    """DashScope SDK exceptions are converted into a useful ValueError."""
    def fake_call(**kwargs):
        """Raise a fake SDK error without live network."""
        raise DashScopeException("SDK failure")

    monkeypatch.setattr(
        qwen_client.dashscope.MultiModalConversation,
        "call",
        staticmethod(fake_call),
    )

    with pytest.raises(ValueError, match="Qwen ASR DashScope request failed."):
        asyncio.run(
            qwen_client.run_dashscope_asr(
                Settings(DASHSCOPE_API_KEY="test-key"),
                "https://example.com/sample.mp3",
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


def test_generate_tutor_turn_timeout_error_has_specific_message() -> None:
    """Combined Qwen timeout includes the configured timeout in the error."""
    client = QwenClient(
        settings=Settings(
            USE_FAKE_QWEN=False,
            QWEN_API_KEY="test-key",
            QWEN_BASE_URL="https://example.com/compatible-mode/v1",
            QWEN_CHAT_MODEL="qwen-plus",
            QWEN_REQUEST_TIMEOUT_SECONDS=25,
        )
    )
    mock_qwen = Mock()
    mock_qwen.chat.completions.create = AsyncMock(
        side_effect=APITimeoutError(request=Mock())
    )
    client._real_client = Mock(return_value=mock_qwen)

    with pytest.raises(ValueError, match="Qwen tutor turn request timed out after 25 seconds."):
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
