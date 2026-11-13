import pytest

from incident_responder.service import Conflict, NotFound
from incident_responder.tools import MAX_TOOL_CALLS

from .conftest import HAPPY, call, text

ALERT = "checkout-api 5xx rate above 15% for 5 minutes"


async def test_full_workflow_proposes_but_does_not_execute(make_service, backends):
    service = make_service()
    incident = await service.handle_alert(ALERT)

    assert "SEV2" in incident["triage"]
    assert "v142" in incident["diagnosis"]
    assert incident["ticket_id"] == "INC-1000"
    assert incident["actions"] == [{"action": "rollback_deploy", "service": "checkout-api",
                                    "reason": "RB-001, deploy 12 min ago", "status": "pending"}]
    assert backends.executor.executed == []          # nothing runs without a human
    assert len(backends.ticketing.tickets) == 1


async def test_agents_receive_previous_agents_output(make_service):
    service = make_service()
    await service.handle_alert(ALERT)
    diagnosis_prompt = str(service.script.requests["diagnosis"][0].config.system_instruction)
    remediation_prompt = str(service.script.requests["remediation"][0].config.system_instruction)
    assert "SEVERITY: SEV2" in diagnosis_prompt
    assert "deploy v142" in remediation_prompt


async def test_approval_executes_once(make_service, backends):
    service = make_service()
    incident = await service.handle_alert(ALERT)
    action = service.decide(incident["id"], 0, "dhruthi", approve=True)
    assert action["status"] == "executed" and action["decided_by"] == "dhruthi"
    assert backends.executor.executed == [
        {"action": "rollback_deploy", "service": "checkout-api", "status": "executed"}]
    with pytest.raises(Conflict):
        service.decide(incident["id"], 0, "dhruthi", approve=True)
    assert len(backends.executor.executed) == 1


async def test_rejection_executes_nothing(make_service, backends):
    service = make_service()
    incident = await service.handle_alert(ALERT)
    assert service.decide(incident["id"], 0, "dhruthi", approve=False)["status"] == "rejected"
    assert backends.executor.executed == []


async def test_decide_validation(make_service):
    service = make_service()
    incident = await service.handle_alert(ALERT)
    with pytest.raises(NotFound):
        service.decide("nope", 0, "a", True)
    with pytest.raises(NotFound):
        service.decide(incident["id"], 5, "a", True)
    with pytest.raises(ValueError):
        service.decide(incident["id"], 0, "  ", True)


async def test_guard_blocks_disallowed_action_and_unknown_service(make_service, backends):
    replies = dict(HAPPY, remediation=[
        call("propose_action", action="delete_database", service="checkout-api", reason="x"),
        call("propose_action", action="restart_service", service="prod-db-primary", reason="x"),
        call("create_ticket", title="t", severity="URGENT", summary="s"),
        text("Could not act."),
    ])
    service = make_service(replies)
    incident = await service.handle_alert(ALERT)
    assert incident["actions"] == [] and incident["ticket_id"] is None
    denied = [e for e in backends.audit if e["event"] == "tool_call" and not e["allowed"]]
    assert len(denied) == 3


async def test_tool_budget_stops_runaway_loop(make_service, backends):
    seen = []
    original = backends.metrics.get
    backends.metrics.get = lambda service: seen.append(service) or original(service)
    replies = dict(HAPPY, diagnosis=[call("get_service_metrics", service="checkout-api")] * 30 + [text("gave up")])
    service = make_service(replies)
    await service.handle_alert(ALERT)
    assert len(seen) == MAX_TOOL_CALLS


async def test_only_one_ticket_per_incident(make_service, backends):
    replies = dict(HAPPY, remediation=[
        call("create_ticket", title="a", severity="SEV2", summary="s"),
        call("create_ticket", title="b", severity="SEV2", summary="s"),
        text("done"),
    ])
    service = make_service(replies)
    await service.handle_alert(ALERT)
    assert len(backends.ticketing.tickets) == 1


async def test_alert_validation(make_service):
    service = make_service()
    with pytest.raises(ValueError):
        await service.handle_alert("   ")
    with pytest.raises(ValueError):
        await service.handle_alert("x" * 5000)


def test_runbook_search(backends):
    hits = backends.runbooks.search("high cpu saturation")
    assert hits[0]["id"] == "RB-002"
    assert backends.runbooks.search("zzzz") == []
