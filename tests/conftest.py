"""A scripted model so the full ADK workflow runs offline and deterministically.

ADK calls before_model_callback before every model request; returning an
LlmResponse there skips the real model. Each agent gets a queue of replies."""
from collections import defaultdict

import pytest
from google.adk.models import LlmResponse
from google.genai import types

from incident_responder.backends import fixture_backends
from incident_responder.service import IncidentService


def text(value: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=value)]))


def call(name: str, **args) -> LlmResponse:
    return LlmResponse(content=types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]))


class Script:
    def __init__(self, replies: dict):
        self.replies = {agent: list(items) for agent, items in replies.items()}
        self.requests = defaultdict(list)

    def __call__(self, callback_context, llm_request):
        agent = callback_context.agent_name
        self.requests[agent].append(llm_request)
        queue = self.replies.get(agent, [])
        return queue.pop(0) if queue else text(f"{agent} done")


HAPPY = {
    "triage": [text("SERVICE: checkout-api\nSEVERITY: SEV2\nSUMMARY: Elevated 5xx on checkout.")],
    "diagnosis": [
        call("get_service_metrics", service="checkout-api"),
        call("get_recent_deploys", service="checkout-api"),
        call("search_runbooks", query="5xx error rate after deploy"),
        text("Likely cause: deploy v142 12 minutes ago. Error rate 0.18 vs 0.01 baseline. RB-001. Confidence: high."),
    ],
    "remediation": [
        call("create_ticket", title="checkout-api 5xx after v142", severity="SEV2", summary="Error rate 18%"),
        call("propose_action", action="rollback_deploy", service="checkout-api", reason="RB-001, deploy 12 min ago"),
        text("Ticket INC-1000 opened. Proposed rollback of v142, awaiting approval."),
    ],
}


@pytest.fixture
def backends():
    return fixture_backends()


@pytest.fixture
def make_service(backends):
    def make(replies=HAPPY):
        script = Script(replies)
        service = IncidentService(backends, model="gemini-2.5-flash", model_callback=script)
        service.script = script
        return service
    return make
