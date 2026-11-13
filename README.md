# adk-incident-responder

A multi-agent incident responder built on Google's Agent Development Kit (ADK) with Gemini on Vertex AI. An alert comes in; three agents triage it, diagnose it from metrics, deploy history and runbooks, then open a ticket and propose a fix. A human approves the fix before anything is executed.

## Design

```
POST /incidents {alert}
        |
        v
  ADK Workflow:  triage  ->  diagnosis  ->  remediation
                   |            |               |
              state.triage  tools:          tools:
                            get_service_    create_ticket
                            metrics         propose_action   (records a proposal only)
                            get_recent_
                            deploys
                            search_runbooks
        |
        v
  incident {triage, diagnosis, ticket_id, actions: [pending]}
        |
POST /incidents/{id}/actions/{n}/decision {approver, approve}
        |
        v
  Executor runs the action (only here, only after a human approves)
```

Safety choices:

- **The model cannot execute remediations.** It has no tool that changes infrastructure. `propose_action` only records a proposal; execution happens in ordinary code behind the approval endpoint, which re-validates the action first. Each action can be decided once.
- **A guard runs before every tool call** (`before_tool_callback`): service names must be in the registry, actions must be in a fixed allowlist, severities must be valid, and each incident has a tool-call budget that stops runaway loops.
- **Untrusted text stays data.** Alerts, deploy notes and runbooks are flagged as untrusted in every instruction. That reduces prompt injection but does not prevent it, which is why the two controls above do not depend on the model behaving.
- **Audit trail:** every tool call (allowed or denied) and every human decision is logged. Tool calls record argument names, not values.

Agents pass results through ADK session state (`output_key`), and the next agent reads them through its instruction template.

## Run locally

```bash
pip install -r requirements.txt
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=my-project GOOGLE_CLOUD_LOCATION=us-central1
export MODEL=gemini-2.5-flash        # any current Gemini model on Vertex AI
gcloud auth application-default login
uvicorn incident_responder.server:create_app --factory --port 8080
```

```bash
curl -s localhost:8080/incidents -H 'content-type: application/json' \
  -d '{"alert": "checkout-api 5xx rate above 15% for 5 minutes"}'
curl -s localhost:8080/incidents/<id>/actions/0/decision -H 'content-type: application/json' \
  -d '{"approver": "you@example.com", "approve": true}'
```

It ships with fixture backends (three sample services, their metrics, deploys and runbooks) so it runs without any monitoring stack.

## Deploy to Cloud Run

```bash
PROJECT=my-project REGION=asia-south1 ./deploy/cloudrun.sh
```

The script creates a dedicated service account with only `roles/aiplatform.user` and deploys with authentication required.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt && pytest -q    # 13 tests
```

The tests run the real ADK workflow, tools, guard and HTTP API offline. A scripted `before_model_callback` stands in for Gemini, so no credentials or network are needed. They cover: the full triage to proposal flow, state passing between agents, approve and reject, single execution, the guard blocking a hallucinated action and an unknown service, the tool-call budget, one ticket per incident, and API error handling.

## Status and limits

- Tested offline against google-adk 2.14 on Python 3.13 with a scripted model. A run against live Gemini and the Cloud Run deploy script have not been exercised in CI; run them in your own project.
- Backends are fixtures. Production use means implementing the five small interfaces in `backends.py` (Cloud Monitoring, deploy history, a runbook store, ticketing, an executor).
- Incidents and sessions are held in memory, so they are lost on restart and not shared between instances. Use a persistent ADK session service and a database for incidents before running more than one instance.
- The approver is a name supplied by the caller. Put the API behind IAP or verify identity tokens so the approver is authenticated.

Related: [agent-permission-firewall](https://github.com/DhruthiRao1/agent-permission-firewall), [guardrails-gateway](https://github.com/DhruthiRao1/guardrails-gateway), [llm-redteam-harness](https://github.com/DhruthiRao1/llm-redteam-harness).

## License

MIT
