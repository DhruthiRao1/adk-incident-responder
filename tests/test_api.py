from fastapi.testclient import TestClient

from incident_responder.server import create_app


def test_api_end_to_end(make_service, backends):
    client = TestClient(create_app(make_service()))
    assert client.get("/health").json() == {"status": "ok"}

    created = client.post("/incidents", json={"alert": "checkout-api 5xx above 15%"})
    assert created.status_code == 201
    incident = created.json()
    assert incident["actions"][0]["status"] == "pending"

    assert client.get(f"/incidents/{incident['id']}").json()["ticket_id"] == "INC-1000"
    assert client.get("/incidents/missing").status_code == 404

    url = f"/incidents/{incident['id']}/actions/0/decision"
    assert client.post(url, json={"approver": "", "approve": True}).status_code == 422
    done = client.post(url, json={"approver": "dhruthi", "approve": True})
    assert done.status_code == 200 and done.json()["status"] == "executed"
    assert client.post(url, json={"approver": "dhruthi", "approve": True}).status_code == 409
    assert client.post(f"/incidents/{incident['id']}/actions/9/decision",
                       json={"approver": "d", "approve": True}).status_code == 404

    events = {e["event"] for e in client.get("/audit").json()}
    assert {"tool_call", "incident_handled", "action_decision"} <= events


def test_api_rejects_bad_alert(make_service):
    client = TestClient(create_app(make_service()))
    assert client.post("/incidents", json={"alert": ""}).status_code == 422
    assert client.post("/incidents", json={"alert": "x" * 5000}).status_code == 422


def test_api_hides_agent_errors(make_service):
    def boom(callback_context, llm_request):
        raise RuntimeError("secret internal detail")
    service = make_service()
    from incident_responder.service import IncidentService
    broken = IncidentService(service.backends, model="gemini-2.5-flash", model_callback=boom)
    client = TestClient(create_app(broken), raise_server_exceptions=False)
    response = client.post("/incidents", json={"alert": "anything"})
    assert response.status_code == 502 and "secret" not in response.text
