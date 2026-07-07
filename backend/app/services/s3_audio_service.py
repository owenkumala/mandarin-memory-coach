"""S3-compatible upload helper for temporary Qwen ASR audio references.

Cloudflare R2 is used only as a temporary S3-compatible fallback while Alibaba
OSS setup is blocked. Alibaba OSS remains the intended final provider.
"""

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from app.core.config import Settings

S3_AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


@dataclass(frozen=True)
class S3AudioReference:
    """Safe S3 upload result used by ASR and diagnostics."""

    object_key: str
    url: str


def upload_audio_to_s3(audio_path: str, settings: Settings) -> S3AudioReference:
    """Upload local audio to S3-compatible storage and return an HTTPS URL."""
    _validate_s3_settings(settings)
    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        raise ValueError("Audio file for S3 upload was not found.")

    boto3 = _load_boto3()
    object_key = _s3_object_key(path.name, settings.S3_PREFIX)
    content_type = _content_type_for_audio(path)
    client = boto3.client(
        "s3",
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        endpoint_url=settings.S3_ENDPOINT_URL,
        region_name=settings.S3_REGION,
    )

    try:
        client.upload_file(
            str(path),
            settings.S3_BUCKET,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )
        if settings.S3_PUBLIC_BASE_URL.strip():
            url = _join_url(settings.S3_PUBLIC_BASE_URL, object_key)
        else:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET, "Key": object_key},
                ExpiresIn=settings.S3_SIGNED_URL_EXPIRES_SECONDS,
            )
    except _boto_error_types() as exc:
        raise ValueError("S3-compatible audio upload failed.") from exc

    _validate_https_url(url)
    return S3AudioReference(object_key=object_key, url=url)


def _validate_s3_settings(settings: Settings) -> None:
    """Ensure all S3-compatible upload settings are present before upload."""
    missing_settings = [
        name
        for name in (
            "S3_ACCESS_KEY_ID",
            "S3_SECRET_ACCESS_KEY",
            "S3_ENDPOINT_URL",
            "S3_BUCKET",
        )
        if not getattr(settings, name).strip()
    ]
    if missing_settings:
        missing = ", ".join(missing_settings)
        raise ValueError(f"Qwen ASR S3 mode requires S3 settings. Missing: {missing}.")


def _content_type_for_audio(path: Path) -> str:
    """Return the MIME type DashScope should see when fetching S3 audio."""
    return S3_AUDIO_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _s3_object_key(filename: str, prefix: str) -> str:
    """Build the destination S3 object key from prefix and local filename."""
    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        return filename
    return f"{normalized_prefix}/{filename}"


def _join_url(base_url: str, path: str) -> str:
    """Join public S3 base URL and object key without double slashes."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _validate_https_url(url: str) -> None:
    """Require HTTPS URLs because Qwen ASR fetches audio server-side."""
    if not url.startswith("https://"):
        raise ValueError("S3-compatible ASR audio URL must start with https://.")


def _load_boto3() -> ModuleType:
    """Import boto3 lazily so fake-mode tests do not require live dependencies."""
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("boto3 is required for QWEN_ASR_AUDIO_REF_MODE=s3_url.") from exc
    return boto3


def _boto_error_types() -> tuple[type[Exception], ...]:
    """Return botocore error types when boto3 is installed."""
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return ()
    return (BotoCoreError, ClientError)
