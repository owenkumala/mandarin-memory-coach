"""Runtime Python certificate configuration for DashScope websocket clients."""

import logging
import os

import certifi

logger = logging.getLogger(__name__)


def configure_python_ssl_certificates() -> None:
    """Set process-level Python CA bundle env vars when they are missing."""
    ca_bundle_path = certifi.where()
    configured_names = [
        name
        for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
        if not os.environ.get(name)
    ]

    os.environ.setdefault("SSL_CERT_FILE", ca_bundle_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle_path)

    if configured_names:
        logger.info(
            "Configured certifi CA bundle for Python SSL: %s",
            ", ".join(configured_names),
        )
