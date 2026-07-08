"""Unit tests for fake and real-mode Qwen client helpers."""

import asyncio
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import certifi
from dashscope.common.error import DashScopeException
from openai import APIConnectionError, APITimeoutError
import pytest

from app.core.certificates import configure_python_ssl_certificates
from app.core.config import Settings
from app.schemas import (
    AnalysisResponse,
    MemoryResponse,
    MistakeAnalysis,
    MistakeType,
    WeaknessCategory,
)
from app.services import qwen_client
from app.services.qwen_client import (
    QwenClient,
    _asr_api_key,
    _analysis_system_prompt,
    _analysis_user_prompt,
    _build_asr_audio_ref,
    _extract_asr_transcript,
    _safe_error_detail,
    _tutor_realtime_system_prompt,
    _tutor_realtime_user_prompt,
    _tts_base_url,
    build_asr_audio_ref,
    parse_dashscope_asr_response,
    parse_analysis_json,
    parse_tutor_turn_json,
    run_dashscope_tts,
    strip_json_code_fence,
)
from scripts.check_python_certs import (  # noqa: E402
    _connectivity_result_from_error,
    print_certificate_diagnostics,
)
from scripts.check_qwen_asr import _safe_audio_ref
from scripts.check_qwen_tts import print_tts_config


class _FakeOssAuth:
    """Capture OSS auth construction without using real credentials."""

    def __init__(self, access_key_id: str, access_key_secret: str) -> None:
        """Store credential placeholders for assertions if needed."""
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret


class _FakeOssBucket:
    """Fake oss2 Bucket that records upload and signing calls."""

    instances: list["_FakeOssBucket"] = []

    def __init__(self, auth: _FakeOssAuth, endpoint: str, bucket_name: str) -> None:
        """Store constructor args and register this fake bucket instance."""
        self.auth = auth
        self.endpoint = endpoint
        self.bucket_name = bucket_name
        self.put_object_from_file = Mock()
        self.sign_url = Mock(return_value="https://bucket.oss.example.com/signed.mp3?sig=1")
        self.instances.append(self)


def _install_fake_oss2(monkeypatch) -> type[_FakeOssBucket]:
    """Install a fake oss2 module for non-live OSS tests."""
    _FakeOssBucket.instances = []
    fake_oss2 = SimpleNamespace(Auth=_FakeOssAuth, Bucket=_FakeOssBucket)
    monkeypatch.setitem(sys.modules, "oss2", fake_oss2)
    return _FakeOssBucket


class _FakeS3Client:
    """Fake boto3 S3 client that records upload and presign calls."""

    instances: list["_FakeS3Client"] = []

    def __init__(self) -> None:
        """Register this fake S3 client instance."""
        self.upload_file = Mock()
        self.generate_presigned_url = Mock(
            return_value="https://bucket.r2.example.com/signed.mp3?sig=1"
        )
        self.instances.append(self)


class _FakeBoto3:
    """Fake boto3 module with a client factory for tests."""

    clients: list[_FakeS3Client] = []
    client_calls: list[dict[str, object]] = []

    @staticmethod
    def client(service_name: str, **kwargs) -> _FakeS3Client:
        """Return a fake S3 client and record constructor kwargs."""
        _FakeBoto3.client_calls.append({"service_name": service_name, **kwargs})
        client = _FakeS3Client()
        _FakeBoto3.clients.append(client)
        return client


def _install_fake_boto3(monkeypatch) -> type[_FakeBoto3]:
    """Install a fake boto3 module for non-live S3/R2 tests."""
    _FakeBoto3.clients = []
    _FakeBoto3.client_calls = []
    _FakeS3Client.instances = []
    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)
    return _FakeBoto3


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


def test_realtime_tutor_prompt_is_tts_safe_and_level_aware() -> None:
    """Realtime tutor prompts constrain output for short TTS-friendly chunks."""
    system_prompt = _tutor_realtime_system_prompt()
    user_prompt = _tutor_realtime_user_prompt(
        transcript="我想入住",
        memory=_empty_memory(),
        scenario="hotel check-in",
        level="HSK3 lower intermediate",
    )

    assert "A short acknowledgement has already been spoken" in system_prompt
    assert "Do not repeat that acknowledgement" in system_prompt
    assert "friendly Mandarin tutor in a live call" in system_prompt
    assert "2 to 4 short spoken sentences" in system_prompt
    assert "6 to 10 seconds of speech" in system_prompt
    assert "under 22 Chinese characters" in system_prompt
    assert "Do not make one long sentence" in system_prompt
    assert "Do not split tiny filler" in system_prompt
    assert "at most one main correction" in system_prompt
    assert "Recast the learner into the natural speaker role" in system_prompt
    assert "Do not preserve an off-scenario literal phrase" in system_prompt
    assert "hotel check-in the learner is usually the guest" in system_prompt
    assert "natural follow-up question or repeat prompt" in system_prompt
    assert "Avoid always starting with 可以说" in system_prompt
    assert "Do not use spoken placeholders like ……" in system_prompt
    assert "save detailed feedback, pinyin, and pronunciation notes" in system_prompt
    assert "For HSK1-HSK2, be English-friendly" in system_prompt
    assert "For HSK5-HSK6, use Mandarin-first" in system_prompt
    assert "Do not use emoji" in system_prompt
    assert "Avoid nested Chinese quotation marks" in system_prompt
    assert "Use the provided scenario dynamically" in system_prompt
    assert "HSK3 lower intermediate" in user_prompt
    assert "hotel check-in" in user_prompt
    assert "2 to 4 short spoken sentences" in user_prompt
    assert "selected scenario" in user_prompt
    assert "replace it with a natural phrase for the scenario" in user_prompt
    assert "guest checking in" in user_prompt
    assert "HSK3: mixed English/Chinese" in user_prompt
    assert "one conversational next turn" in user_prompt
    assert "Save detailed mistake explanations, pinyin" in user_prompt
    assert "your name" in user_prompt
    assert "For HSK3, use practical restaurant language" not in user_prompt
    assert "我要一份宫保鸡丁" not in system_prompt
    assert "我要一份宫保鸡丁" not in user_prompt


def test_analysis_prompt_requests_frontend_friendly_pronunciation_fields() -> None:
    """Structured analysis prompt asks for optional pinyin correction metadata."""
    system_prompt = _analysis_system_prompt()
    user_prompt = _analysis_user_prompt(
        transcript="我是 Owen",
        scenario="self introduction",
        level="HSK2 elementary",
    )

    assert "target_pinyin" in system_prompt
    assert "heard_pinyin" in system_prompt
    assert "problem_sound" in system_prompt
    assert "problem_tone" in system_prompt
    assert "display_correction" in system_prompt
    assert "pinyin" in system_prompt
    assert "tone" in system_prompt
    assert "是 and 市" in system_prompt
    assert "frontend correction card" in user_prompt


def test_mistake_analysis_optional_pronunciation_fields_serialize() -> None:
    """Optional pinyin fields support frontend cards without breaking old payloads."""
    mistake = MistakeAnalysis(
        type=MistakeType.PRONUNCIATION,
        weakness_category=WeaknessCategory.ZH_CH_CONFUSION,
        target="我是 Owen",
        target_pinyin="wǒ shì Owen",
        heard_pinyin="wǒ sì Owen",
        problem_sound="sh/s",
        problem_tone="4th tone",
        display_correction="是 shì, not sì",
        severity=3,
        feedback="Practice 是 with a clear sh sound and fourth tone.",
        example_sentence="我是 Owen。",
        recommended_drill="Repeat 我是 Owen three times.",
    )
    old_payload = {
        "type": "grammar",
        "weakness_category": "grammar_structure",
        "target": "word order",
        "severity": 2,
        "feedback": "Move the time phrase before the verb.",
        "example_sentence": "我明天去。",
        "recommended_drill": "Repeat the sentence once.",
    }

    assert mistake.model_dump()["target_pinyin"] == "wǒ shì Owen"
    assert mistake.model_dump()["display_correction"] == "是 shì, not sì"
    assert MistakeAnalysis.model_validate(old_payload).target_pinyin is None


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


def test_fake_tts_returns_none(tmp_path) -> None:
    """Fake TTS mode keeps tutor_audio_url null without credentials."""
    client = QwenClient(settings=Settings(USE_FAKE_TTS=True))

    synthesized_path = asyncio.run(
        client.synthesize_speech("你好", str(tmp_path / "reply.mp3"))
    )

    assert synthesized_path is None


def test_tts_base_url_accepts_blank() -> None:
    """Blank TTS base URL lets the SDK use its default CosyVoice endpoint."""
    assert _tts_base_url(Settings(QWEN_TTS_BASE_URL="")) is None


def test_tts_base_url_accepts_websocket_url() -> None:
    """Configured TTS base URL must be a websocket endpoint."""
    url = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"

    assert _tts_base_url(Settings(QWEN_TTS_BASE_URL=url)) == url


def test_tts_base_url_rejects_https_url() -> None:
    """HTTP DashScope API URLs are rejected for CosyVoice websocket TTS."""
    with pytest.raises(ValueError, match="websocket URL starting with ws:// or wss://"):
        _tts_base_url(
            Settings(QWEN_TTS_BASE_URL="https://dashscope-intl.aliyuncs.com/api/v1")
        )


def test_real_tts_success_with_mocked_dashscope_call(tmp_path, monkeypatch) -> None:
    """Real TTS uses DashScope CosyVoice TTS and writes returned audio bytes."""
    output_path = tmp_path / "reply.mp3"
    init_kwargs = {}
    call_args = []

    class FakeSpeechSynthesizer:
        """Fake DashScope tts_v2 synthesizer for non-live tests."""

        def __init__(self, **kwargs) -> None:
            """Capture constructor settings for assertions."""
            init_kwargs.update(kwargs)

        def call(self, text: str) -> bytes:
            """Return fake complete audio bytes."""
            call_args.append(text)
            return b"fake-audio"

    monkeypatch.setattr(qwen_client, "SpeechSynthesizer", FakeSpeechSynthesizer)

    synthesized_path = asyncio.run(
        run_dashscope_tts(
            Settings(
                USE_FAKE_TTS=False,
                DASHSCOPE_API_KEY="dash-key",
                QWEN_API_KEY="qwen-key",
                QWEN_TTS_MODEL="cosyvoice-v3-plus",
                QWEN_TTS_VOICE="longanyang",
                QWEN_TTS_BASE_URL="",
                QWEN_TTS_OUTPUT_FORMAT="mp3",
            ),
            "欢迎回来！",
            str(output_path),
        )
    )

    assert synthesized_path == str(output_path)
    assert output_path.read_bytes() == b"fake-audio"
    assert init_kwargs["model"] == "cosyvoice-v3-plus"
    assert init_kwargs["voice"] == "longanyang"
    assert init_kwargs["format"] == qwen_client.AudioFormat.MP3_24000HZ_MONO_256KBPS
    assert init_kwargs["url"] is None
    assert call_args == ["欢迎回来！"]


def test_real_tts_passes_websocket_base_url(tmp_path, monkeypatch) -> None:
    """Real TTS passes a configured WSS base URL to the DashScope SDK."""
    output_path = tmp_path / "reply.mp3"
    init_kwargs = {}

    class FakeSpeechSynthesizer:
        """Fake DashScope synthesizer that captures the websocket URL."""

        def __init__(self, **kwargs) -> None:
            """Capture constructor settings for assertions."""
            init_kwargs.update(kwargs)

        def call(self, text: str) -> bytes:
            """Return fake complete audio bytes."""
            return b"fake-audio"

    monkeypatch.setattr(qwen_client, "SpeechSynthesizer", FakeSpeechSynthesizer)

    asyncio.run(
        run_dashscope_tts(
            Settings(
                USE_FAKE_TTS=False,
                QWEN_API_KEY="qwen-key",
                QWEN_TTS_MODEL="cosyvoice-v3-plus",
                QWEN_TTS_VOICE="longanyang",
                QWEN_TTS_BASE_URL="wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference",
            ),
            "欢迎回来！",
            str(output_path),
        )
    )

    assert init_kwargs["url"] == "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"


def test_real_tts_type_error_becomes_value_error(tmp_path, monkeypatch) -> None:
    """DashScope TTS SDK type errors are converted into a useful ValueError."""
    class BrokenSpeechSynthesizer:
        """Fake synthesizer that simulates an SDK call failure."""

        def __init__(self, **kwargs) -> None:
            """Accept constructor kwargs like the real SDK."""

        def call(self, text: str) -> bytes:
            """Raise a non-live SDK-style error."""
            raise TypeError("bad tts response")

    monkeypatch.setattr(qwen_client, "SpeechSynthesizer", BrokenSpeechSynthesizer)

    with pytest.raises(ValueError, match="Qwen TTS request failed."):
        asyncio.run(
            run_dashscope_tts(
                Settings(
                    USE_FAKE_TTS=False,
                    QWEN_API_KEY="qwen-key",
                    QWEN_TTS_MODEL="cosyvoice-v3-plus",
                    QWEN_TTS_VOICE="longanyang",
                ),
                "你好",
                str(tmp_path / "reply.mp3"),
            )
        )


def test_real_tts_missing_model_raises_useful_error(tmp_path) -> None:
    """Real TTS validates required model and voice settings before SDK calls."""
    with pytest.raises(ValueError, match="Qwen TTS requires QWEN_TTS_MODEL"):
        asyncio.run(
            run_dashscope_tts(
                Settings(
                    USE_FAKE_TTS=False,
                    DASHSCOPE_API_KEY="dash-key",
                    QWEN_TTS_MODEL="",
                    QWEN_TTS_VOICE="longanyang",
                ),
                "你好",
                str(tmp_path / "reply.mp3"),
            )
        )


def test_python_cert_diagnostics_do_not_print_secrets(capsys) -> None:
    """Certificate diagnostics print cert state without leaking API keys."""
    print_certificate_diagnostics(
        Settings(
            QWEN_API_KEY="qwen-secret",
            DASHSCOPE_API_KEY="dash-secret",
            SSL_CERT_FILE="",
            REQUESTS_CA_BUNDLE="",
        )
    )

    output = capsys.readouterr().out
    assert "certifi_where=" in output
    assert "export SSL_CERT_FILE=" in output
    assert "qwen-secret" not in output
    assert "dash-secret" not in output


def test_configure_python_ssl_certificates_sets_missing_env(
    monkeypatch,
    caplog,
) -> None:
    """Certificate helper sets missing SSL env vars to certifi for this process."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    with caplog.at_level(logging.INFO, logger="app.core.certificates"):
        configure_python_ssl_certificates()

    assert os.environ["SSL_CERT_FILE"] == certifi.where()
    assert os.environ["REQUESTS_CA_BUNDLE"] == certifi.where()
    assert "Configured certifi CA bundle" in caplog.text
    assert "secret" not in caplog.text.lower()


def test_configure_python_ssl_certificates_does_not_overwrite_existing_env(
    monkeypatch,
) -> None:
    """Certificate helper preserves user-provided certificate env vars."""
    monkeypatch.setenv("SSL_CERT_FILE", "/custom/ssl.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/custom/requests.pem")

    configure_python_ssl_certificates()

    assert os.environ["SSL_CERT_FILE"] == "/custom/ssl.pem"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "/custom/requests.pem"


def test_qwen_tts_diagnostics_do_not_print_secrets(capsys) -> None:
    """TTS diagnostics print key presence flags without leaking key values."""
    print_tts_config(
        Settings(
            USE_FAKE_TTS=False,
            QWEN_API_KEY="qwen-secret",
            DASHSCOPE_API_KEY="dash-secret",
            QWEN_TTS_MODEL="cosyvoice-v3-plus",
            QWEN_TTS_VOICE="longanyang",
            QWEN_TTS_BASE_URL="wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference",
            SSL_CERT_FILE="",
            REQUESTS_CA_BUNDLE="",
        )
    )

    output = capsys.readouterr().out
    assert "has_QWEN_API_KEY=yes" in output
    assert "has_DASHSCOPE_API_KEY=yes" in output
    assert "automatic_certifi_configuration=active" in output
    assert "qwen-secret" not in output
    assert "dash-secret" not in output


def test_python_cert_connectivity_treats_401_as_good() -> None:
    """A 401-style websocket response means TLS reached DashScope."""
    message = _connectivity_result_from_error(RuntimeError("401 No API-key provided"))

    assert "WSS connectivity OK" in message


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


def test_real_asr_success_with_mocked_dashscope_call(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
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
            QWEN_ASR_AUDIO_REF_MODE="local_path",
        )
    )

    with caplog.at_level(logging.INFO, logger="app.services.qwen_client"):
        transcript = asyncio.run(client.transcribe_audio(str(audio_path)))

    assert transcript == "我想吃中国菜"
    assert call_kwargs["api_key"] == "test-key"
    assert call_kwargs["model"] == "qwen-asr-test"
    assert call_kwargs["base_address"] == "https://dashscope-intl.aliyuncs.com/api/v1"
    assert call_kwargs["asr_options"]["language"] == "zh"
    assert "qwen.asr_audio_ref_mode=local_path bytes=10" in caplog.text
    assert "qwen.asr_request_start model=qwen-asr-test" in caplog.text
    assert "qwen.asr_parse_seconds=" in caplog.text
    assert "qwen.asr_total_seconds=" in caplog.text


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


def test_asr_public_url_mode_builds_url_from_storage_path(tmp_path) -> None:
    """Public URL mode converts stored audio paths into backend URLs."""
    storage_dir = tmp_path / "storage"
    audio_path = storage_dir / "user_audio" / "sample.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        STORAGE_DIR=str(storage_dir),
        PUBLIC_BACKEND_BASE_URL="https://demo.example.com",
        QWEN_ASR_AUDIO_REF_MODE="public_url",
    )

    audio_ref = _build_asr_audio_ref(str(audio_path), settings)

    assert audio_ref == "https://demo.example.com/storage/user_audio/sample.m4a"


def test_asr_public_url_mode_requires_public_backend_base_url(tmp_path) -> None:
    """Public URL mode fails clearly when no public backend URL is configured."""
    storage_dir = tmp_path / "storage"
    audio_path = storage_dir / "user_audio" / "sample.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"fake audio")

    with pytest.raises(ValueError, match="PUBLIC_BACKEND_BASE_URL is required"):
        _build_asr_audio_ref(
            str(audio_path),
            Settings(
                STORAGE_DIR=str(storage_dir),
                PUBLIC_BACKEND_BASE_URL="",
                QWEN_ASR_AUDIO_REF_MODE="public_url",
            ),
        )


def test_asr_local_path_mode_returns_raw_path(tmp_path) -> None:
    """Local path diagnostic mode still returns the raw file path."""
    audio_path = tmp_path / "sample.m4a"
    audio_path.write_bytes(b"fake audio")

    audio_ref = _build_asr_audio_ref(
        str(audio_path),
        Settings(QWEN_ASR_AUDIO_REF_MODE="local_path"),
    )

    assert audio_ref == str(audio_path)


def test_asr_file_url_mode_returns_file_uri(tmp_path) -> None:
    """File URL diagnostic mode still returns a file:// URI."""
    audio_path = tmp_path / "sample.m4a"
    audio_path.write_bytes(b"fake audio")

    audio_ref = _build_asr_audio_ref(
        str(audio_path),
        Settings(QWEN_ASR_AUDIO_REF_MODE="file_url"),
    )

    assert audio_ref == audio_path.resolve().as_uri()


def test_asr_public_url_join_avoids_double_slashes(tmp_path) -> None:
    """Public URL mode joins base URL and /storage path cleanly."""
    storage_dir = tmp_path / "storage"
    audio_path = storage_dir / "user_audio" / "sample.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"fake audio")

    audio_ref = _build_asr_audio_ref(
        str(audio_path),
        Settings(
            STORAGE_DIR=str(storage_dir),
            PUBLIC_BACKEND_BASE_URL="https://demo.example.com/",
            QWEN_ASR_AUDIO_REF_MODE="public_url",
        ),
    )

    assert audio_ref == "https://demo.example.com/storage/user_audio/sample.m4a"
    assert "com//storage" not in audio_ref


def test_asr_oss_url_requires_oss_config(tmp_path) -> None:
    """OSS mode validates required Alibaba OSS settings before upload."""
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")

    with pytest.raises(ValueError, match="Missing: ALIBABA_OSS_ACCESS_KEY_ID"):
        asyncio.run(
            build_asr_audio_ref(
                str(audio_path),
                Settings(
                    QWEN_ASR_AUDIO_REF_MODE="oss_url",
                    ALIBABA_OSS_ACCESS_KEY_ID="",
                    ALIBABA_OSS_ACCESS_KEY_SECRET="",
                    ALIBABA_OSS_ENDPOINT="",
                    ALIBABA_OSS_BUCKET="",
                ),
            )
        )


def test_asr_oss_url_uploads_file_and_returns_signed_url(tmp_path, monkeypatch) -> None:
    """OSS mode uploads the local audio file and returns the signed URL."""
    bucket_cls = _install_fake_oss2(monkeypatch)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="oss_url",
        ALIBABA_OSS_ACCESS_KEY_ID="id",
        ALIBABA_OSS_ACCESS_KEY_SECRET="secret",
        ALIBABA_OSS_ENDPOINT="https://oss.example.com",
        ALIBABA_OSS_BUCKET="bucket",
        ALIBABA_OSS_PREFIX="speechan/audio/",
        ALIBABA_OSS_SIGNED_URL_EXPIRES_SECONDS=900,
    )

    audio_ref = asyncio.run(build_asr_audio_ref(str(audio_path), settings))

    bucket = bucket_cls.instances[0]
    assert audio_ref == "https://bucket.oss.example.com/signed.mp3?sig=1"
    bucket.put_object_from_file.assert_called_once_with(
        "speechan/audio/sample.mp3",
        str(audio_path),
        headers={"Content-Type": "audio/mpeg"},
    )
    bucket.sign_url.assert_called_once_with("GET", "speechan/audio/sample.mp3", 900)


@pytest.mark.parametrize(
    ("filename", "expected_content_type"),
    [
        ("sample.mp3", "audio/mpeg"),
        ("sample.m4a", "audio/mp4"),
        ("sample.wav", "audio/wav"),
        ("sample.webm", "audio/webm"),
    ],
)
def test_asr_oss_url_sets_content_type_per_extension(
    tmp_path,
    monkeypatch,
    filename: str,
    expected_content_type: str,
) -> None:
    """OSS upload sets the expected audio content type by extension."""
    bucket_cls = _install_fake_oss2(monkeypatch)
    audio_path = tmp_path / filename
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="oss_url",
        ALIBABA_OSS_ACCESS_KEY_ID="id",
        ALIBABA_OSS_ACCESS_KEY_SECRET="secret",
        ALIBABA_OSS_ENDPOINT="https://oss.example.com",
        ALIBABA_OSS_BUCKET="bucket",
    )

    asyncio.run(build_asr_audio_ref(str(audio_path), settings))

    _, _, kwargs = bucket_cls.instances[0].put_object_from_file.mock_calls[0]
    assert kwargs["headers"] == {"Content-Type": expected_content_type}


def test_asr_oss_url_can_return_public_oss_url(tmp_path, monkeypatch) -> None:
    """OSS mode can return a public base URL instead of a signed URL."""
    bucket_cls = _install_fake_oss2(monkeypatch)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="oss_url",
        ALIBABA_OSS_ACCESS_KEY_ID="id",
        ALIBABA_OSS_ACCESS_KEY_SECRET="secret",
        ALIBABA_OSS_ENDPOINT="https://oss.example.com",
        ALIBABA_OSS_BUCKET="bucket",
        ALIBABA_OSS_PUBLIC_BASE_URL="https://cdn.example.com/audio",
        ALIBABA_OSS_PREFIX="speechan/audio/",
    )

    audio_ref = asyncio.run(build_asr_audio_ref(str(audio_path), settings))

    assert audio_ref == "https://cdn.example.com/audio/speechan/audio/sample.mp3"
    bucket_cls.instances[0].sign_url.assert_not_called()


def test_asr_s3_url_requires_s3_config(tmp_path) -> None:
    """S3 mode validates required S3-compatible settings before upload."""
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")

    with pytest.raises(ValueError, match="Missing: S3_ACCESS_KEY_ID"):
        asyncio.run(
            build_asr_audio_ref(
                str(audio_path),
                Settings(
                    QWEN_ASR_AUDIO_REF_MODE="s3_url",
                    S3_ACCESS_KEY_ID="",
                    S3_SECRET_ACCESS_KEY="",
                    S3_ENDPOINT_URL="",
                    S3_BUCKET="",
                ),
            )
        )


def test_asr_s3_url_uploads_file_and_returns_presigned_url(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    """S3 mode uploads audio and returns a presigned URL."""
    fake_boto3 = _install_fake_boto3(monkeypatch)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="s3_url",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
        S3_ENDPOINT_URL="https://r2.example.com",
        S3_BUCKET="bucket",
        S3_REGION="auto",
        S3_PREFIX="speechan/audio/",
        S3_SIGNED_URL_EXPIRES_SECONDS=900,
    )

    with caplog.at_level(logging.INFO):
        audio_ref = asyncio.run(build_asr_audio_ref(str(audio_path), settings))

    client = fake_boto3.clients[0]
    assert audio_ref == "https://bucket.r2.example.com/signed.mp3?sig=1"
    assert fake_boto3.client_calls[0]["service_name"] == "s3"
    client.upload_file.assert_called_once_with(
        str(audio_path),
        "bucket",
        "speechan/audio/sample.mp3",
        ExtraArgs={"ContentType": "audio/mpeg"},
    )
    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "bucket", "Key": "speechan/audio/sample.mp3"},
        ExpiresIn=900,
    )
    assert "s3.upload_audio_seconds=" in caplog.text
    assert "s3.presigned_url_seconds=" in caplog.text
    assert "qwen.asr_upload_seconds=" in caplog.text
    assert "https://bucket.r2.example.com/signed.mp3?sig=1" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    ("filename", "expected_content_type"),
    [
        ("sample.mp3", "audio/mpeg"),
        ("sample.m4a", "audio/mp4"),
        ("sample.wav", "audio/wav"),
        ("sample.webm", "audio/webm"),
    ],
)
def test_asr_s3_url_sets_content_type_per_extension(
    tmp_path,
    monkeypatch,
    filename: str,
    expected_content_type: str,
) -> None:
    """S3 upload sets the expected audio content type by extension."""
    fake_boto3 = _install_fake_boto3(monkeypatch)
    audio_path = tmp_path / filename
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="s3_url",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
        S3_ENDPOINT_URL="https://r2.example.com",
        S3_BUCKET="bucket",
    )

    asyncio.run(build_asr_audio_ref(str(audio_path), settings))

    _, args, kwargs = fake_boto3.clients[0].upload_file.mock_calls[0]
    assert args[2] == f"speechan/audio/{filename}"
    assert kwargs["ExtraArgs"] == {"ContentType": expected_content_type}


def test_asr_s3_url_can_return_public_url(tmp_path, monkeypatch) -> None:
    """S3 mode can return a public base URL instead of a presigned URL."""
    fake_boto3 = _install_fake_boto3(monkeypatch)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="s3_url",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
        S3_ENDPOINT_URL="https://r2.example.com",
        S3_BUCKET="bucket",
        S3_PUBLIC_BASE_URL="https://pub.example.com/audio",
        S3_PREFIX="speechan/audio/",
    )

    audio_ref = asyncio.run(build_asr_audio_ref(str(audio_path), settings))

    assert audio_ref == "https://pub.example.com/audio/speechan/audio/sample.mp3"
    fake_boto3.clients[0].generate_presigned_url.assert_not_called()


def test_asr_s3_url_rejects_non_https_url(tmp_path, monkeypatch) -> None:
    """S3 mode rejects non-HTTPS public or presigned URLs."""
    fake_boto3 = _install_fake_boto3(monkeypatch)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")
    fake_boto3.clients = []
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="s3_url",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
        S3_ENDPOINT_URL="https://r2.example.com",
        S3_BUCKET="bucket",
        S3_PUBLIC_BASE_URL="http://pub.example.com/audio",
    )

    with pytest.raises(ValueError, match="must start with https://"):
        asyncio.run(build_asr_audio_ref(str(audio_path), settings))


def test_asr_oss_url_rejects_non_https_url(tmp_path, monkeypatch) -> None:
    """OSS mode rejects non-HTTPS public or signed URLs."""
    _install_fake_oss2(monkeypatch)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake audio")
    settings = Settings(
        QWEN_ASR_AUDIO_REF_MODE="oss_url",
        ALIBABA_OSS_ACCESS_KEY_ID="id",
        ALIBABA_OSS_ACCESS_KEY_SECRET="secret",
        ALIBABA_OSS_ENDPOINT="https://oss.example.com",
        ALIBABA_OSS_BUCKET="bucket",
        ALIBABA_OSS_PUBLIC_BASE_URL="http://cdn.example.com/audio",
    )

    with pytest.raises(ValueError, match="must start with https://"):
        asyncio.run(build_asr_audio_ref(str(audio_path), settings))


def test_diagnostic_safe_audio_ref_drops_signed_query_params() -> None:
    """Diagnostic printing removes signed URL query parameters."""
    signed_url = "https://bucket.r2.example.com/signed.mp3?X-Amz-Signature=secret"

    assert _safe_audio_ref(signed_url) == "https://bucket.r2.example.com/signed.mp3"


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
