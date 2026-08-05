from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel


class ActionResponse(BaseModel):
    external_reference: str
    status: str
    deduplicated: bool = False


class MockStore:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.lock = threading.Lock()
        self.by_key: dict[str, ActionResponse] = {}
        self.by_reference: dict[str, ActionResponse] = {}
        self.calls: list[dict[str, Any]] = []

    def execute(self, key: str, operation: str, payload: dict[str, Any]) -> ActionResponse:
        with self.lock:
            self.calls.append({"idempotency_key": key, "operation": operation})
            if key in self.by_key:
                existing = self.by_key[key]
                return existing.model_copy(update={"deduplicated": True})
            response = ActionResponse(
                external_reference=f"{self.prefix}-{len(self.by_key) + 1}",
                status="OPEN" if operation == "create_ticket" else "COMPLETED",
            )
            self.by_key[key] = response
            self.by_reference[response.external_reference] = response
            if payload.get("_simulate") == "timeout_after_create_once":
                payload.pop("_simulate", None)
                raise TimeoutError
            return response


app = FastAPI(title="VisionQC Mock MES/QMS", version="0.1.0")
stores = {"mes": MockStore("MES"), "qms": MockStore("QMS")}


@app.get("/{system}/health")
def health(system: str) -> dict[str, str]:
    if system not in stores:
        raise HTTPException(status_code=404)
    return {"status": "ok"}


@app.post("/{system}/actions/{operation}", response_model=ActionResponse)
async def execute(
    system: str,
    operation: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
) -> ActionResponse:
    if system not in stores:
        raise HTTPException(status_code=404)
    payload = await request.json()
    if payload.get("_simulate") == "always_fail":
        raise HTTPException(status_code=503, detail="injected failure")
    try:
        return stores[system].execute(idempotency_key, operation, payload)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="injected timeout after commit") from exc


@app.get("/{system}/actions/{external_reference}", response_model=ActionResponse)
def get_status(system: str, external_reference: str) -> ActionResponse:
    if system not in stores or external_reference not in stores[system].by_reference:
        raise HTTPException(status_code=404)
    return stores[system].by_reference[external_reference]


@app.get("/{system}/calls")
def calls(system: str) -> list[dict[str, Any]]:
    if system not in stores:
        raise HTTPException(status_code=404)
    return stores[system].calls
