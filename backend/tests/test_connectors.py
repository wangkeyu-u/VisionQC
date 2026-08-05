from __future__ import annotations

from app.connectors import InMemoryConnector, RetryingConnectorExecutor


def test_timeout_after_server_commit_reuses_idempotency_key() -> None:
    connector = InMemoryConnector("qms")
    connector.fail_after_create_once = True
    executor = RetryingConnectorExecutor(max_attempts=3, backoff_seconds=0)

    outcome = executor.execute(
        connector,
        "CREATE_TICKET",
        {"inspection_id": "insp-1"},
        "inc-1:qms:create",
    )

    assert outcome.error is None
    assert outcome.result is not None
    assert outcome.attempts == 2
    assert connector.calls == ["inc-1:qms:create", "inc-1:qms:create"]
    assert len(connector.records) == 1


def test_final_failure_is_reported_not_disguised_as_success() -> None:
    connector = InMemoryConnector("qms")
    connector.always_fail = True
    executor = RetryingConnectorExecutor(max_attempts=3, backoff_seconds=0)

    outcome = executor.execute(connector, "CREATE_TICKET", {}, "stable-key")

    assert outcome.result is None
    assert outcome.error is not None
    assert outcome.attempts == 3
    assert len(connector.records) == 0
