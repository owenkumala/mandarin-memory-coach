"""Manual diagnostic client for the realtime voice-chat WebSocket endpoint.

The script sends a start message, streams base64 audio chunks, and prints
frontend-facing events with elapsed timestamps for latency inspection.
"""

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

import websockets

DEFAULT_WS_URL = "ws://localhost:8000/api/v1/voice-chat/realtime"
DEFAULT_AUDIO_PATH = "sample-mandarin.mp3"
DEFAULT_USER_ID = "demo-user-realtime-manual"
DEFAULT_SCENARIO = "restaurant ordering"
DEFAULT_LEVEL = "HSK3 lower intermediate"
DEFAULT_CHUNK_SIZE = 240_000


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the realtime WebSocket diagnostic."""
    parser = argparse.ArgumentParser(
        description="Send audio to WS /api/v1/voice-chat/realtime and print events.",
    )
    parser.add_argument("--url", default=DEFAULT_WS_URL, help="Realtime WebSocket URL.")
    parser.add_argument(
        "--audio",
        default=DEFAULT_AUDIO_PATH,
        help="Audio file to send. Defaults to sample-mandarin.mp3.",
    )
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--level", default=DEFAULT_LEVEL)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Raw audio bytes per WebSocket audio_chunk message.",
    )
    return parser.parse_args()


def build_start_message(user_id: str, scenario: str, level: str) -> dict[str, str]:
    """Return the realtime start message sent before audio chunks."""
    return {
        "type": "start",
        "user_id": user_id,
        "scenario": scenario,
        "level": level,
    }


def read_audio_file(audio_path: str) -> bytes:
    """Read an audio file or fail with a clear local diagnostic message."""
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Audio file not found: {path}. Pass --audio with a valid file."
        )
    if not path.is_file():
        raise ValueError(f"Audio path is not a file: {path}")
    audio_bytes = path.read_bytes()
    if not audio_bytes:
        raise ValueError(f"Audio file is empty: {path}")
    return audio_bytes


def build_audio_chunk_messages(
    audio_bytes: bytes,
    chunk_size: int,
) -> list[dict[str, str]]:
    """Encode audio bytes into base64 realtime audio_chunk messages."""
    if chunk_size <= 0:
        raise ValueError("--chunk-size must be greater than 0.")
    messages = []
    for index in range(0, len(audio_bytes), chunk_size):
        chunk = audio_bytes[index : index + chunk_size]
        messages.append(
            {
                "type": "audio_chunk",
                "audio_base64": base64.b64encode(chunk).decode("ascii"),
            }
        )
    return messages


def format_event_line(elapsed_seconds: float, event: dict[str, Any]) -> str:
    """Return one compact diagnostic line for a realtime event."""
    event_type = str(event.get("type", "unknown"))
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    details = _event_details(event_type, payload)
    if details:
        return f"{elapsed_seconds:.2f}s {event_type} {details}"
    return f"{elapsed_seconds:.2f}s {event_type}"


def _event_details(event_type: str, payload: dict[str, Any]) -> str:
    """Return type-specific event details without printing secrets."""
    if event_type == "session_started":
        return f"payload_keys={','.join(payload.keys())}"
    if event_type == "audio_received":
        return f"total_bytes_received={payload.get('total_bytes_received', '')}"
    if event_type == "asr_final":
        return f"transcript={_short_text(payload.get('transcript', ''))}"
    if event_type == "tutor_token":
        return f"text={_short_text(payload.get('text', ''))}"
    if event_type == "tutor_sentence":
        return (
            f"sequence={payload.get('sequence', '')} "
            f"text={_short_text(payload.get('text', ''))}"
        )
    if event_type == "audio_chunk_ready":
        return (
            f"sequence={payload.get('sequence', '')} "
            f"audio_url={payload.get('audio_url', '')}"
        )
    if event_type in {"feedback_ready", "memory_updated", "done"}:
        return ""
    if event_type == "error":
        return (
            f"severity={payload.get('severity', '')} "
            f"code={payload.get('code', '')} "
            f"message={_short_text(payload.get('message', ''))}"
        )
    return f"payload_keys={','.join(payload.keys())}"


def _short_text(value: Any, max_length: int = 120) -> str:
    """Return compact single-line text for terminal diagnostics."""
    text = str(value).replace("\n", " ").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


async def run_diagnostic(args: argparse.Namespace) -> None:
    """Connect to the realtime WebSocket, send audio, and print events."""
    audio_bytes = read_audio_file(args.audio)
    audio_messages = build_audio_chunk_messages(audio_bytes, args.chunk_size)
    start_message = build_start_message(args.user_id, args.scenario, args.level)
    started_at = time.perf_counter()

    async with websockets.connect(args.url) as websocket:
        await websocket.send(json.dumps(start_message, ensure_ascii=False))
        for message in audio_messages:
            await websocket.send(json.dumps(message))
        await websocket.send(json.dumps({"type": "end_audio"}))

        async for raw_message in websocket:
            elapsed = time.perf_counter() - started_at
            event = json.loads(raw_message)
            print(format_event_line(elapsed, event), flush=True)
            if isinstance(event, dict) and event.get("type") == "done":
                return


def main() -> None:
    """Run the realtime WebSocket diagnostic from the command line."""
    args = parse_args()
    try:
        asyncio.run(run_diagnostic(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Realtime WebSocket diagnostic failed: {exc}") from exc


if __name__ == "__main__":
    main()
