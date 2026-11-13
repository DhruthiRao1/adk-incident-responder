"""Runs the workflow for an alert and handles human approval of proposed actions."""
from __future__ import annotations

import uuid
from typing import Callable, Optional

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agents import build_workflow
from .backends import Backends
from .tools import ALLOWED_ACTIONS

APP = "incident_responder"
MAX_ALERT_CHARS = 4000


class NotFound(KeyError):
    pass


class Conflict(ValueError):
    pass


class InvalidInput(ValueError):
    """Bad caller input. Kept separate from ValueErrors raised inside the agent run,
    which are server faults and must not be reported as the caller's mistake."""


class IncidentService:
    def __init__(self, backends: Backends, model: Optional[str] = None,
                 model_callback: Optional[Callable] = None):
        self.backends = backends
        self.runner = InMemoryRunner(node=build_workflow(backends, model, model_callback), app_name=APP)
        self.incidents: dict[str, dict] = {}

    async def handle_alert(self, alert: str) -> dict:
        alert = alert.strip()
        if not alert:
            raise InvalidInput("alert must not be empty")
        if len(alert) > MAX_ALERT_CHARS:
            raise InvalidInput(f"alert longer than {MAX_ALERT_CHARS} characters")
        incident_id = uuid.uuid4().hex[:12]
        session = await self.runner.session_service.create_session(app_name=APP, user_id=incident_id)
        message = types.Content(role="user", parts=[types.Part(text=f"ALERT:\n{alert}")])
        async for _ in self.runner.run_async(user_id=incident_id, session_id=session.id, new_message=message):
            pass
        session = await self.runner.session_service.get_session(
            app_name=APP, user_id=incident_id, session_id=session.id)
        state = session.state
        incident = {
            "id": incident_id,
            "alert": alert,
            "triage": state.get("triage"),
            "diagnosis": state.get("diagnosis"),
            "remediation": state.get("remediation"),
            "ticket_id": state.get("ticket_id"),
            "actions": [dict(a) for a in state.get("pending_actions", [])],
        }
        self.incidents[incident_id] = incident
        self.backends.log("incident_handled", incident=incident_id, actions=len(incident["actions"]))
        return incident

    def get(self, incident_id: str) -> dict:
        if incident_id not in self.incidents:
            raise NotFound(incident_id)
        return self.incidents[incident_id]

    def decide(self, incident_id: str, index: int, approver: str, approve: bool) -> dict:
        """A human approves or rejects a proposed action. Only an approval executes it,
        and each action can be decided once."""
        incident = self.get(incident_id)
        if not approver.strip():
            raise InvalidInput("approver is required")
        if not 0 <= index < len(incident["actions"]):
            raise NotFound(f"action {index}")
        action = incident["actions"][index]
        if action["status"] != "pending":
            raise Conflict(f"action already {action['status']}")
        # Re-validate at execution time: never trust what was stored at proposal time.
        if action["action"] not in ALLOWED_ACTIONS or action["service"] not in self.backends.services:
            action["status"] = "invalid"
            raise Conflict("action failed validation")
        if approve:
            action["result"] = self.backends.executor.run(action["action"], action["service"])
            action["status"] = "executed"
        else:
            action["status"] = "rejected"
        action["decided_by"] = approver
        self.backends.log("action_decision", incident=incident_id, index=index,
                          action=action["action"], service=action["service"],
                          status=action["status"], approver=approver)
        return action
