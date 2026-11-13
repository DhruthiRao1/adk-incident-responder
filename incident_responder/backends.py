"""Backends the agents talk to. Each is a small interface so the fixture
implementations here can be swapped for Cloud Monitoring, Cloud Deploy,
ServiceNow/Jira and so on without touching the agents."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

FIXTURES = Path(__file__).parent / "data" / "fixtures.json"


class Metrics(Protocol):
    def get(self, service: str) -> dict: ...


class Deploys(Protocol):
    def recent(self, service: str) -> list: ...


class Runbooks(Protocol):
    def search(self, query: str, limit: int = 3) -> list: ...


class Ticketing(Protocol):
    def create(self, title: str, severity: str, summary: str) -> str: ...


class Executor(Protocol):
    def run(self, action: str, service: str) -> dict: ...


class FixtureMetrics:
    def __init__(self, data: dict):
        self._data = data

    def get(self, service: str) -> dict:
        return dict(self._data[service])


class FixtureDeploys:
    def __init__(self, data: dict):
        self._data = data

    def recent(self, service: str) -> list:
        return list(self._data.get(service, []))


class KeywordRunbooks:
    """Tiny keyword-overlap search. Swap for a vector store in production."""

    def __init__(self, runbooks: list):
        self._runbooks = runbooks

    def search(self, query: str, limit: int = 3) -> list:
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        scored = []
        for rb in self._runbooks:
            words = set(re.findall(r"[a-z0-9]+", (rb["title"] + " " + rb["body"]).lower()))
            overlap = len(terms & words)
            if overlap:
                scored.append((overlap, rb))
        scored.sort(key=lambda pair: -pair[0])
        return [rb for _, rb in scored[:limit]]


class InMemoryTicketing:
    def __init__(self):
        self.tickets: list[dict] = []

    def create(self, title: str, severity: str, summary: str) -> str:
        ticket_id = f"INC-{1000 + len(self.tickets)}"
        self.tickets.append({"id": ticket_id, "title": title, "severity": severity, "summary": summary})
        return ticket_id


class RecordingExecutor:
    """Records actions instead of touching infrastructure. Replace with a real
    executor (Cloud Run revisions, GKE rollouts) behind the same interface."""

    def __init__(self):
        self.executed: list[dict] = []

    def run(self, action: str, service: str) -> dict:
        record = {"action": action, "service": service, "status": "executed"}
        self.executed.append(record)
        return record


@dataclass
class Backends:
    services: frozenset
    metrics: Metrics
    deploys: Deploys
    runbooks: Runbooks
    ticketing: Ticketing
    executor: Executor
    audit: list = field(default_factory=list)

    def log(self, event: str, **fields) -> None:
        self.audit.append({"ts": time.time(), "event": event, **fields})


def fixture_backends(path: Path = FIXTURES) -> Backends:
    data = json.loads(path.read_text())
    return Backends(
        services=frozenset(data["services"]),
        metrics=FixtureMetrics(data["metrics"]),
        deploys=FixtureDeploys(data["deploys"]),
        runbooks=KeywordRunbooks(data["runbooks"]),
        ticketing=InMemoryTicketing(),
        executor=RecordingExecutor(),
    )
