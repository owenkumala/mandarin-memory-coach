"""Manual Python certificate diagnostic for DashScope websocket access.

This script checks local certificate configuration for Qwen CosyVoice TTS.
It never prints API keys and treats 401-style DashScope responses as proof
that TLS and network connectivity reached the service.
"""

import asyncio
import platform
import ssl
import sys

import certifi
from dotenv import load_dotenv

try:
    import websockets
except ImportError:  # pragma: no cover - manual diagnostic dependency guard.
    websockets = None

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402

WSS_TEST_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"


def main() -> None:
    """Load settings, print certificate diagnostics, and test WSS reachability."""
    load_dotenv(BACKEND_DIR / ".env")
    settings = Settings()

    print_certificate_diagnostics(settings)
    result = asyncio.run(test_wss_connectivity(WSS_TEST_URL))
    print(result)


def print_certificate_diagnostics(settings: Settings) -> None:
    """Print safe local Python and certificate configuration facts."""
    print(f"python_version={sys.version.split()[0]}")
    print(f"certifi_where={certifi.where()}")
    print(f"SSL_CERT_FILE={_display_env_value(settings.SSL_CERT_FILE)}")
    print(f"REQUESTS_CA_BUNDLE={_display_env_value(settings.REQUESTS_CA_BUNDLE)}")

    if not settings.SSL_CERT_FILE.strip() or not settings.REQUESTS_CA_BUNDLE.strip():
        print("certificate_exports_missing=true")
        print(
            "export SSL_CERT_FILE=\"$(python3 -c 'import certifi; "
            "print(certifi.where())')\""
        )
        print('export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"')

    install_command = macos_install_certificates_command()
    if install_command:
        print(f"macos_framework_python_fix={install_command}")


async def test_wss_connectivity(url: str) -> str:
    """Connect to DashScope WSS with certifi and return a human diagnostic."""
    if websockets is None:
        return "websockets package is missing; install backend requirements first."

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        async with websockets.connect(url, ssl=ssl_context, open_timeout=10):
            return "WSS connectivity OK: websocket handshake succeeded."
    except ssl.SSLCertVerificationError:
        return (
            "Certificate verification failed. Run: python3 -m pip install "
            "--upgrade certifi, then export SSL_CERT_FILE and REQUESTS_CA_BUNDLE "
            "to certifi.where(). Do not disable SSL verification."
        )
    except TimeoutError:
        return (
            "WSS connectivity timed out. Check network, firewall, VPN, or proxy "
            "access to dashscope-intl.aliyuncs.com."
        )
    except OSError as exc:
        return _connectivity_result_from_error(exc)
    except Exception as exc:  # noqa: BLE001 - manual diagnostics need SDK-version tolerance.
        return _connectivity_result_from_error(exc)


def _connectivity_result_from_error(exc: Exception) -> str:
    """Classify websocket errors without exposing secrets."""
    message = str(exc)
    if any(token in message for token in ("401", "InvalidApiKey", "No API-key")):
        return (
            "WSS connectivity OK: DashScope returned an API-key error after TLS, "
            "so certificates and network reached the service."
        )
    if "CERTIFICATE_VERIFY_FAILED" in message:
        return (
            "Certificate verification failed. Point SSL_CERT_FILE and "
            "REQUESTS_CA_BUNDLE at certifi.where(); do not disable SSL verification."
        )
    return f"WSS connectivity failed: {type(exc).__name__}: {message}"


def macos_install_certificates_command() -> str:
    """Return the framework-Python macOS certificate installer command if useful."""
    if platform.system() != "Darwin":
        return ""
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return f'open "/Applications/Python {version}/Install Certificates.command"'


def _display_env_value(value: str) -> str:
    """Display whether a certificate env var is set without special parsing."""
    return value.strip() or "(not set)"


if __name__ == "__main__":
    main()
