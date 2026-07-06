"""Audio storage helpers for upload naming, paths, and file writes."""

from pathlib import Path
from uuid import uuid4

import aiofiles

SUPPORTED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a"}


class AudioValidationError(ValueError):
    """Raised when an uploaded audio file is missing or unsupported."""


def ensure_storage_directories(*directories: str) -> None:
    """Create storage directories needed by upload and tutor-audio flows."""
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


def validate_audio_upload(original_filename: str, content: bytes) -> None:
    """Reject empty audio uploads or files outside supported extensions."""
    suffix = Path(original_filename).suffix.lower()
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise AudioValidationError(f"Unsupported audio extension. Use one of: {supported}.")
    if not content:
        raise AudioValidationError("Audio file is empty.")


def build_audio_file_path(directory: str, user_id: str, original_filename: str) -> Path:
    """Return a unique path for an uploaded or generated audio file."""
    suffix = Path(original_filename).suffix or ".webm"
    safe_user_id = "".join(character for character in user_id if character.isalnum() or character in "-_")
    filename = f"{safe_user_id}_{uuid4().hex}{suffix}"
    return Path(directory) / filename


async def write_audio_bytes(destination: Path, content: bytes) -> str:
    """Write audio bytes to disk and return the string path for persistence."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(destination, "wb") as audio_file:
        await audio_file.write(content)
    return str(destination)


def storage_url(path: str, storage_root: str) -> str:
    """Convert a storage path into the URL served by FastAPI StaticFiles."""
    relative_path = Path(path).resolve().relative_to(Path(storage_root).resolve())
    return f"/storage/{relative_path.as_posix()}"
