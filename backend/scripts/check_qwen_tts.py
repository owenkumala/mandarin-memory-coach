"""Manual Qwen CosyVoice TTS diagnostic for SpeakHan developers.

This script prints safe TTS configuration facts and runs the same
QwenClient.synthesize_speech path used by `/voice-chat`.
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.certificates import configure_python_ssl_certificates  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.services.qwen_client import QwenClient  # noqa: E402

DEFAULT_TEXT = "你好！请跟我说：我要一份宫保鸡丁。"
DEFAULT_OUTPUT = Path("storage/tutor_audio/manual-tts-test.mp3")


def main() -> None:
    """Load settings, print safe diagnostics, and run one TTS synthesis."""
    parser = argparse.ArgumentParser(description="Check Qwen CosyVoice TTS config.")
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Text to synthesize. Defaults to a short Mandarin tutor sentence.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output audio path relative to backend unless absolute.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_DIR / ".env")
    previous_env = certificate_env_sources()
    configure_python_ssl_certificates()
    settings = Settings()
    print_tts_config(settings, previous_env)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = BACKEND_DIR / output_path

    result = asyncio.run(run_tts_check(settings, args.text, output_path))
    print(result)


def print_tts_config(
    settings: Settings,
    previous_env: dict[str, str] | None = None,
) -> None:
    """Print safe TTS configuration facts without exposing secret values."""
    previous_env = previous_env or certificate_env_sources()
    print(f"USE_FAKE_TTS={settings.USE_FAKE_TTS}")
    print(f"QWEN_TTS_MODEL={settings.QWEN_TTS_MODEL}")
    print(f"QWEN_TTS_VOICE={settings.QWEN_TTS_VOICE}")
    print(f"QWEN_TTS_BASE_URL={settings.QWEN_TTS_BASE_URL}")
    print(f"QWEN_TTS_OUTPUT_FORMAT={settings.QWEN_TTS_OUTPUT_FORMAT}")
    print(f"has_QWEN_API_KEY={'yes' if settings.QWEN_API_KEY else 'no'}")
    print(f"has_DASHSCOPE_API_KEY={'yes' if settings.DASHSCOPE_API_KEY else 'no'}")
    print(f"SSL_CERT_FILE_set={'yes' if settings.SSL_CERT_FILE else 'no'}")
    print(f"REQUESTS_CA_BUNDLE_set={'yes' if settings.REQUESTS_CA_BUNDLE else 'no'}")
    print("automatic_certifi_configuration=active")
    print(f"SSL_CERT_FILE_source={_certificate_source(previous_env, 'SSL_CERT_FILE')}")
    print(
        "REQUESTS_CA_BUNDLE_source="
        f"{_certificate_source(previous_env, 'REQUESTS_CA_BUNDLE')}"
    )

    if not settings.SSL_CERT_FILE.strip() or not settings.REQUESTS_CA_BUNDLE.strip():
        print(
            "warning=SSL_CERT_FILE or REQUESTS_CA_BUNDLE is missing; CosyVoice "
            "WSS may fail certificate verification on macOS."
        )
        print(
            "export SSL_CERT_FILE=\"$(python3 -c 'import certifi; "
            "print(certifi.where())')\""
        )
        print('export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"')


def certificate_env_sources() -> dict[str, str]:
    """Return current certificate env var values for source diagnostics."""
    return {
        "SSL_CERT_FILE": os.environ.get("SSL_CERT_FILE", ""),
        "REQUESTS_CA_BUNDLE": os.environ.get("REQUESTS_CA_BUNDLE", ""),
    }


def _certificate_source(previous_env: dict[str, str], name: str) -> str:
    """Return whether a certificate setting came from user env or auto config."""
    if previous_env.get(name):
        return "user-env"
    return "auto-certifi"


async def run_tts_check(settings: Settings, text: str, output_path: Path) -> str:
    """Run TTS and return a compact success or failure message."""
    try:
        result = await QwenClient(settings=settings).synthesize_speech(
            text,
            str(output_path),
        )
    except ValueError as exc:
        return f"tts_error={exc}"

    if result is None:
        return "tts_result=None; USE_FAKE_TTS is likely true."
    size = output_path.stat().st_size if output_path.exists() else 0
    return f"tts_result={result}\nexists={output_path.exists()}\nsize={size}"


if __name__ == "__main__":
    main()
