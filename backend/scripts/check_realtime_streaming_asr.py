"""Manual diagnostic for opt-in Qwen realtime streaming ASR.

This script streams a local PCM file through the same
QwenStreamingRealtimeAsrSession used by the realtime WebSocket path. It is
manual-only and is not used by pytest.
"""

import argparse
import asyncio
import time
from pathlib import Path
import sys

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.services.qwen_client import QwenClient  # noqa: E402
from app.services.realtime_asr_service import (  # noqa: E402
    REALTIME_ASR_MODE_QWEN_STREAMING,
    QwenStreamingRealtimeAsrSession,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the streaming ASR diagnostic."""
    parser = argparse.ArgumentParser(
        description="Stream a local PCM file through Qwen realtime ASR.",
    )
    parser.add_argument("audio", help="Raw PCM 16-bit mono audio file.")
    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=200,
        help="Approximate PCM milliseconds per provider append.",
    )
    parser.add_argument("--user-id", default="demo-user-realtime-streaming-asr")
    return parser.parse_args()


async def run_diagnostic(args: argparse.Namespace) -> None:
    """Stream local PCM audio and print partial/final transcript events."""
    load_dotenv(BACKEND_DIR / ".env")
    settings = Settings()
    if settings.REALTIME_ASR_MODE.strip().lower() != REALTIME_ASR_MODE_QWEN_STREAMING:
        raise ValueError(
            "Set REALTIME_ASR_MODE=qwen_streaming_realtime in backend/.env "
            "before running this diagnostic."
        )
    if settings.REALTIME_ASR_AUDIO_FORMAT.strip().lower() != "pcm":
        raise ValueError("This diagnostic expects REALTIME_ASR_AUDIO_FORMAT=pcm.")

    audio_path = Path(args.audio)
    audio_bytes = _read_pcm(audio_path)
    chunk_size = _chunk_size(settings.REALTIME_ASR_SAMPLE_RATE, args.chunk_ms)
    session = QwenStreamingRealtimeAsrSession(
        qwen_client=QwenClient(settings=settings),
        settings=settings,
        user_id=args.user_id,
        audio_filename=audio_path.name,
        audio_mime_type="audio/pcm",
    )
    started_at = time.perf_counter()
    print(
        "Streaming PCM chunks to Qwen realtime ASR. "
        "Do not use MP3/WebM with this diagnostic.",
        flush=True,
    )
    for event in await session.start():
        _print_event(started_at, event)
    for index in range(0, len(audio_bytes), chunk_size):
        chunk = audio_bytes[index : index + chunk_size]
        for event in await session.accept_audio_chunk(chunk):
            _print_event(started_at, event)
        await asyncio.sleep(args.chunk_ms / 1000)
    result = await session.finish()
    elapsed = time.perf_counter() - started_at
    print(f"{elapsed:.2f}s asr_final transcript={result.transcript}", flush=True)
    print(f"saved_audio_path={result.audio_path}", flush=True)


def _read_pcm(audio_path: Path) -> bytes:
    """Read a local PCM file or fail with clear instructions."""
    if audio_path.suffix.lower() not in {".pcm", ".raw"}:
        raise ValueError("Use a raw PCM file with .pcm or .raw extension.")
    if not audio_path.exists() or not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    audio_bytes = audio_path.read_bytes()
    if not audio_bytes:
        raise ValueError(f"Audio file is empty: {audio_path}")
    return audio_bytes


def _chunk_size(sample_rate: int, chunk_ms: int) -> int:
    """Return bytes per chunk for 16-bit mono PCM."""
    if chunk_ms <= 0:
        raise ValueError("--chunk-ms must be greater than 0.")
    bytes_per_second = sample_rate * 2
    return max(1, int(bytes_per_second * chunk_ms / 1000))


def _print_event(started_at: float, event: object) -> None:
    """Print one realtime event without exposing credentials."""
    elapsed = time.perf_counter() - started_at
    event_type = getattr(event, "type", "unknown")
    event_type = getattr(event_type, "value", event_type)
    payload = getattr(event, "payload", {})
    print(f"{elapsed:.2f}s {event_type} {payload}", flush=True)


def main() -> None:
    """Run the manual streaming ASR diagnostic."""
    args = parse_args()
    try:
        asyncio.run(run_diagnostic(args))
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Realtime streaming ASR diagnostic failed: {exc}") from exc


if __name__ == "__main__":
    main()
