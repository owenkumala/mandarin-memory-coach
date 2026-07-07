"""Manual DashScope ASR diagnostic script for SpeakHan developers.

This script loads backend/.env, prints safe ASR configuration facts, and calls
the same DashScope ASR helper/parser used by the backend. It is intentionally
manual and is not used by pytest.
"""

import argparse
import asyncio
from pathlib import Path
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.services.qwen_client import (  # noqa: E402
    _asr_api_key,
    _build_asr_audio_ref,
    _safe_error_detail,
    call_dashscope_asr,
    parse_dashscope_asr_response,
)
from app.services.oss_audio_service import upload_audio_to_oss  # noqa: E402

DEFAULT_AUDIO_URL = "https://dashscope.oss-cn-beijing.aliyuncs.com/audios/welcome.mp3"


def main() -> None:
    """Load settings, print safe diagnostics, and run one manual ASR call."""
    parser = argparse.ArgumentParser(description="Check Qwen DashScope ASR config.")
    parser.add_argument(
        "audio",
        nargs="?",
        default=DEFAULT_AUDIO_URL,
        help="Audio path or URL. Defaults to Qwen Cloud sample audio URL.",
    )
    parser.add_argument(
        "--audio-ref-mode",
        choices=("oss_url", "public_url", "local_path", "file_url"),
        help="Override QWEN_ASR_AUDIO_REF_MODE for this diagnostic run.",
    )
    args = parser.parse_args()

    load_dotenv(BACKEND_DIR / ".env")
    settings = Settings()
    if args.audio_ref_mode:
        settings = settings.model_copy(
            update={"QWEN_ASR_AUDIO_REF_MODE": args.audio_ref_mode}
        )
    try:
        audio_ref = asyncio.run(_audio_ref(args.audio, settings))
        _print_config(settings=settings, audio_ref=audio_ref)
        response = asyncio.run(call_dashscope_asr(settings, audio_ref))
        print("sanitized_response:")
        print(_safe_error_detail(_response_to_printable(response), settings))
        print("transcript:")
        print(parse_dashscope_asr_response(response, settings))
    except ValueError as exc:
        print("sanitized_error:")
        print(_safe_error_detail(str(exc), settings))
        raise SystemExit(1) from exc


async def _audio_ref(audio_arg: str, settings: Settings) -> str:
    """Return a direct URL or build the configured local audio reference."""
    if audio_arg.startswith(("http://", "https://")):
        return audio_arg

    if settings.QWEN_ASR_AUDIO_REF_MODE.strip().lower() == "oss_url":
        result = await asyncio.to_thread(upload_audio_to_oss, str(Path(audio_arg)), settings)
        print(f"oss_object_key={result.object_key}")
        print(f"oss_url_host_path={_url_host_path(result.url)}")
        return result.url

    try:
        return _build_asr_audio_ref(str(Path(audio_arg)), settings)
    except ValueError as exc:
        if settings.QWEN_ASR_AUDIO_REF_MODE.strip().lower() == "public_url":
            raise ValueError(
                "Local audio with QWEN_ASR_AUDIO_REF_MODE=public_url must be "
                "under STORAGE_DIR and PUBLIC_BACKEND_BASE_URL must be set. "
                "Use a public HTTPS URL, ngrok/deployed backend URL, or OSS."
            ) from exc
        raise


def _url_host_path(url: str) -> str:
    """Return URL host/path only so signed query credentials are not printed."""
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _print_config(settings: Settings, audio_ref: str) -> None:
    """Print safe ASR configuration facts without exposing key values."""
    try:
        _, key_source = _asr_api_key(settings)
    except ValueError:
        key_source = "missing"

    print(f"has_QWEN_API_KEY={'yes' if settings.QWEN_API_KEY else 'no'}")
    print(f"has_DASHSCOPE_API_KEY={'yes' if settings.DASHSCOPE_API_KEY else 'no'}")
    print(f"QWEN_BASE_URL={settings.QWEN_BASE_URL}")
    print(f"QWEN_ASR_BASE_URL={settings.QWEN_ASR_BASE_URL}")
    print(f"QWEN_ASR_MODEL={settings.QWEN_ASR_MODEL}")
    print(f"QWEN_ASR_AUDIO_REF_MODE={settings.QWEN_ASR_AUDIO_REF_MODE}")
    print(f"PUBLIC_BACKEND_BASE_URL={settings.PUBLIC_BACKEND_BASE_URL}")
    print(f"key_source_used={key_source}")
    print(f"audio_ref={audio_ref}")


def _response_to_printable(response: object) -> object:
    """Convert common DashScope response objects into printable dictionaries."""
    if isinstance(response, dict):
        return response
    return {
        "status_code": getattr(response, "status_code", None),
        "request_id": getattr(response, "request_id", None),
        "code": getattr(response, "code", None),
        "message": getattr(response, "message", None),
        "output": getattr(response, "output", None),
        "usage": getattr(response, "usage", None),
    }


if __name__ == "__main__":
    main()
