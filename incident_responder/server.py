"""HTTP API. Run: uvicorn incident_responder.server:create_app --factory --port 8080"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .backends import Backends, fixture_backends
from .service import Conflict, IncidentService, InvalidInput, NotFound


class AlertIn(BaseModel):
    alert: str = Field(min_length=1, max_length=4000)


class DecisionIn(BaseModel):
    approver: str = Field(min_length=1, max_length=120)
    approve: bool


def create_app(service: Optional[IncidentService] = None, backends: Optional[Backends] = None) -> FastAPI:
    backends = backends or (service.backends if service else fixture_backends())
    service = service or IncidentService(backends)
    app = FastAPI(title="adk-incident-responder", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/incidents", status_code=201)
    async def create_incident(body: AlertIn):
        try:
            return await service.handle_alert(body.alert)
        except InvalidInput as exc:
            raise HTTPException(400, str(exc))
        except Exception:
            backends.log("incident_failed")
            raise HTTPException(502, "agent run failed")

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str):
        try:
            return service.get(incident_id)
        except NotFound:
            raise HTTPException(404, "incident not found")

    @app.post("/incidents/{incident_id}/actions/{index}/decision")
    def decide(incident_id: str, index: int, body: DecisionIn):
        try:
            return service.decide(incident_id, index, body.approver, body.approve)
        except NotFound:
            raise HTTPException(404, "incident or action not found")
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except InvalidInput as exc:
            raise HTTPException(400, str(exc))

    @app.get("/audit")
    def audit(limit: int = 100):
        return backends.audit[-limit:]

    return app
