"""Alibaba OSS upload helper for Qwen ASR audio references.

This module uploads saved learner audio to OSS and returns an HTTPS URL that
DashScope qwen3-asr-flash can fetch server-side.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import time
from types import ModuleType

from app.core.config import Settings

logger = logging.getLogger(__name__)

OSS_AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


@dataclass(frozen=True)
class OssAudioReference:
    """Safe OSS upload result used by ASR and diagnostics."""

    object_key: str
    url: str


def upload_audio_to_oss(audio_path: str, settings: Settings) -> OssAudioReference:
    """Upload local audio to OSS and return a signed or public HTTPS URL."""
    _validate_oss_settings(settings)
    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        raise ValueError("Audio file for OSS upload was not found.")

    oss2 = _load_oss2()
    object_key = _oss_object_key(path.name, settings.ALIBABA_OSS_PREFIX)
    headers = {"Content-Type": _content_type_for_audio(path)}

    # OSS SDK is sync; callers wrap this helper with asyncio.to_thread.
    auth = oss2.Auth(
        settings.ALIBABA_OSS_ACCESS_KEY_ID,
        settings.ALIBABA_OSS_ACCESS_KEY_SECRET,
    )
    bucket = oss2.Bucket(auth, settings.ALIBABA_OSS_ENDPOINT, settings.ALIBABA_OSS_BUCKET)
    upload_started_at = time.perf_counter()
    bucket.put_object_from_file(object_key, str(path), headers=headers)
    logger.info(
        "oss.upload_audio_seconds=%.2f bytes=%s key=%s",
        time.perf_counter() - upload_started_at,
        path.stat().st_size,
        object_key,
    )

    if settings.ALIBABA_OSS_PUBLIC_BASE_URL.strip():
        url = _join_url(settings.ALIBABA_OSS_PUBLIC_BASE_URL, object_key)
    else:
        signed_url_started_at = time.perf_counter()
        url = bucket.sign_url(
            "GET",
            object_key,
            settings.ALIBABA_OSS_SIGNED_URL_EXPIRES_SECONDS,
        )
        logger.info(
            "oss.signed_url_seconds=%.2f key=%s",
            time.perf_counter() - signed_url_started_at,
            object_key,
        )
    _validate_https_url(url)
    return OssAudioReference(object_key=object_key, url=url)


def _validate_oss_settings(settings: Settings) -> None:
    """Ensure all OSS upload settings are present before network work starts."""
    missing_settings = [
        name
        for name in (
            "ALIBABA_OSS_ACCESS_KEY_ID",
            "ALIBABA_OSS_ACCESS_KEY_SECRET",
            "ALIBABA_OSS_ENDPOINT",
            "ALIBABA_OSS_BUCKET",
        )
        if not getattr(settings, name).strip()
    ]
    if missing_settings:
        missing = ", ".join(missing_settings)
        raise ValueError(f"Qwen ASR OSS mode requires OSS settings. Missing: {missing}.")


def _content_type_for_audio(path: Path) -> str:
    """Return the MIME type DashScope should see when fetching OSS audio."""
    return OSS_AUDIO_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _oss_object_key(filename: str, prefix: str) -> str:
    """Build the destination OSS object key from prefix and local filename."""
    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        return filename
    return f"{normalized_prefix}/{filename}"


def _join_url(base_url: str, path: str) -> str:
    """Join public OSS base URL and object key without double slashes."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _validate_https_url(url: str) -> None:
    """Require HTTPS URLs because Qwen ASR fetches audio server-side."""
    if not url.startswith("https://"):
        raise ValueError("Alibaba OSS ASR audio URL must start with https://.")


def _load_oss2() -> ModuleType:
    """Import oss2 lazily so fake-mode tests do not require live dependencies."""
    try:
        import oss2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("oss2 is required for QWEN_ASR_AUDIO_REF_MODE=oss_url.") from exc
    return oss2
