from __future__ import annotations

import pytest

from app.dxq_mock import DxqMockConnector, validate_quality_event


def _payload() -> dict[str, object]:
    return {
        "body_id": "BODY-DEMO-001",
        "workpiece_id": "insp_demo",
        "paint_shop": "PAINT_SHOP_DEMO",
        "booth_station": "PAINT-QC-01",
        "line": "LINE-01",
        "model_variant": "SUV-DEMO",
        "color_code": "C101",
        "paint_recipe": "R-01",
        "shift": "A",
        "timestamp": "2026-08-23T10:00:00+08:00",
        "visual_defect_type": "UNCONFIRMED_ANOMALY",
        "severity": "MAJOR",
        "mask_or_heatmap": {"heatmap_uri": "asset://heatmap"},
        "operator_decision": "INVESTIGATE",
        "equipment_alarm_refs": [],
        "process_parameter_refs": [],
        "root_cause_candidates": ["PENDING_INVESTIGATION"],
        "disposition": "INVESTIGATE",
        "quality_case_id": "inc_demo",
    }


def test_dxq_mock_contract_requires_complete_quality_record() -> None:
    payload = _payload()
    assert validate_quality_event(payload) is payload
    payload.pop("color_code")
    with pytest.raises(ValueError, match="color_code"):
        validate_quality_event(payload)


def test_dxq_mock_is_idempotent_and_never_calls_a_private_endpoint() -> None:
    connector = DxqMockConnector()
    first = connector.execute("PUBLISH_QUALITY_EVENT", _payload(), "incident:dxq:1")
    replay = connector.execute("PUBLISH_QUALITY_EVENT", _payload(), "incident:dxq:1")
    assert first == replay
    assert connector.calls == ["incident:dxq:1", "incident:dxq:1"]
    assert connector.payloads["incident:dxq:1"]["body_id"] == "BODY-DEMO-001"
    assert first.summary["simulated"] is True
    assert first.summary["contract_version"] == "simulated-dxq-quality-loop.v1"
