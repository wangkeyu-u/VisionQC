from __future__ import annotations

import pytest
from pydantic import SecretStr

from edge_gateway.config import GatewaySettings


def test_production_requires_upload_and_status_credentials() -> None:
    missing_upload = GatewaySettings(mode="production")
    with pytest.raises(ValueError, match="AUTH_TOKEN"):
        missing_upload.validate_mode()

    missing_status = GatewaySettings(
        mode="production",
        auth_token=SecretStr("production-upload-token"),
    )
    with pytest.raises(ValueError, match="STATUS_TOKEN"):
        missing_status.validate_mode()

    configured = GatewaySettings(
        mode="production",
        auth_token=SecretStr("production-upload-token"),
        status_token=SecretStr("production-status-token"),
    )
    configured.validate_mode()
