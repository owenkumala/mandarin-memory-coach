"""Shared pytest environment setup for backend tests."""

import os
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.gettempdir()) / "speakh_backend_tests"
shutil.rmtree(TEST_ROOT, ignore_errors=True)
TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'memory_test.db'}"
os.environ["STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["USER_AUDIO_DIR"] = str(TEST_ROOT / "storage" / "user_audio")
os.environ["TUTOR_AUDIO_DIR"] = str(TEST_ROOT / "storage" / "tutor_audio")
os.environ["USE_FAKE_QWEN"] = "true"
os.environ["USE_FAKE_TTS"] = "true"
