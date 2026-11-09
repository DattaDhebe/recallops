import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import StatementError

test_directory = Path(tempfile.mkdtemp(prefix="recallops-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(test_directory / 'test.db').as_posix()}"
os.environ["USE_BEDROCK"] = "false"
os.environ["REQUIRE_COCKROACHDB"] = "false"

import app.agent as agent_module
import app.memory as memory_module
import app.main as main_module
from app.config import Settings
from app.main import app



@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
    shutil.rmtree(test_directory, ignore_errors=True)


def test_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    UUID(response.headers["X-Request-ID"])

    monkeypatch.setattr(main_module.settings, "api_key", "judge-demo-key")
    assert client.get("/incidents").status_code == 401
    assert (
        client.get(
            "/incidents",
            headers={"X-API-Key": "judge-demo-key"},
        ).status_code
        == 200
    )


def test_safe_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "demo-trace-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "demo-trace-123"


def test_readiness_checks_database(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "sqlite-local"


def test_system_reports_local_fallback(client: TestClient) -> None:
    response = client.get("/system")
    assert response.status_code == 200
    assert response.json()["database"] == "sqlite-local"


def test_operator_console_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "RecallOps" in response.text


def test_incident_input_is_normalized(client: TestClient) -> None:
    response = client.post(
        "/incidents",
        json={
            "title": "  API latency alert  ",
            "service": "  Customer API  ",
            "symptoms": "  Elevated latency in the customer API  ",
        },
    )
    assert response.status_code == 201
    assert response.json()["title"] == "API latency alert"
    assert response.json()["service"] == "customer-api"


def test_enabled_mcp_requires_cluster_scoped_credentials() -> None:
    with pytest.raises(RuntimeError, match="COCKROACH_MCP_API_KEY"):
        Settings(use_cockroach_mcp=True).validate_runtime_integrations()
    with pytest.raises(RuntimeError, match="COCKROACH_MCP_CLUSTER_ID"):
        Settings(
            use_cockroach_mcp=True,
            cockroach_mcp_api_key="secret",
        ).validate_runtime_integrations()


def test_competition_mode_rejects_local_fallbacks() -> None:
    with pytest.raises(RuntimeError, match="required production settings"):
        Settings(competition_mode=True).validate_runtime_integrations()


def test_incident_memory_loop(client: TestClient) -> None:
    resolved = client.post(
        "/incidents",
        json={"title": "Checkout timeout", "service": "payments", "symptoms": "checkout requests timeout after database connection saturation"},
    )
    assert resolved.status_code == 201
    incident_id = resolved.json()["id"]

    response = client.post(
        f"/incidents/{incident_id}/resolve",
        json={"resolution": "Raised connection pool limit and restarted the worker", "outcome": "Error rate returned to baseline", "notes": "Monitor saturation dashboard"},
    )
    assert response.status_code == 200

    next_incident = client.post(
        "/incidents",
        json={"title": "Payment checkout latency", "service": "payments", "symptoms": "database connections saturated and checkout latency increased"},
    )
    recommendation = client.post(f"/incidents/{next_incident.json()['id']}/investigate")
    assert recommendation.status_code == 200
    payload = recommendation.json()
    assert payload["recommendations"][0]["incident_id"] == incident_id
    assert payload["recommendations"][0]["outcome"] == "Error rate returned to baseline"
    assert "similarity score" in payload["summary"]
    assert "token overlap" not in payload["summary"]

    evidence = payload["recommendations"][0]["evidence"]
    assert len(evidence) == 3
    assert {item["kind"] for item in evidence} == {"symptoms", "resolution", "outcome"}
    assert all(item["incident_id"] == incident_id for item in evidence)
    outcome_evidence = next(item for item in evidence if item["kind"] == "outcome")
    assert outcome_evidence["content"] == "Error rate returned to baseline"
    assert outcome_evidence["metadata_json"]["notes"] == "Monitor saturation dashboard"


def test_open_incident_is_not_used_as_recommendation(client: TestClient) -> None:
    source = client.post(
        "/incidents",
        json={
            "title": "Queue lag in shipment events",
            "service": "shipment-memory-filter",
            "symptoms": "Shipment event workers have a growing queue lag",
        },
    )
    assert source.status_code == 201

    current = client.post(
        "/incidents",
        json={
            "title": "Shipment queue delay",
            "service": "shipment-memory-filter",
            "symptoms": "Shipment workers show the same growing event queue lag",
        },
    )
    response = client.post(f"/incidents/{current.json()['id']}/investigate")
    assert response.status_code == 200
    assert response.json()["recommendations"] == []


def test_agent_runs_managed_mcp_audit_for_top_memory(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = client.post(
        "/incidents",
        json={
            "title": "Ledger consumer saturation",
            "service": "ledger-mcp-audit",
            "symptoms": "Ledger consumers stall after connection saturation",
        },
    )
    source_id = source.json()["id"]
    resolved = client.post(
        f"/incidents/{source_id}/resolve",
        json={
            "resolution": "Reduced consumer concurrency and recycled connections",
            "outcome": "Consumer lag returned to its recorded baseline",
        },
    )
    assert resolved.status_code == 200
    current = client.post(
        "/incidents",
        json={
            "title": "Ledger processing stalls",
            "service": "ledger-mcp-audit",
            "symptoms": "Ledger consumers stall while database connections are saturated",
        },
    )

    captured: dict = {}

    class FakeMCPClient:
        def __init__(self, **kwargs):
            captured["config"] = kwargs

        async def audit_incident_memories(self, incident_id: str) -> dict:
            captured["incident_id"] = incident_id
            return {
                "is_error": False,
                "text": "3 durable memory rows",
                "structured_content": {"row_count": 3},
            }

    monkeypatch.setattr(main_module, "CockroachDBMCPClient", FakeMCPClient)
    monkeypatch.setattr(main_module.settings, "use_cockroach_mcp", True)
    monkeypatch.setattr(main_module.settings, "cockroach_mcp_api_key", "test-secret")
    monkeypatch.setattr(main_module.settings, "cockroach_mcp_cluster_id", "test-cluster")

    response = client.post(f"/incidents/{current.json()['id']}/investigate")
    assert response.status_code == 200
    payload = response.json()
    assert captured["incident_id"] == source_id
    assert captured["config"]["cluster_id"] == "test-cluster"
    assert payload["memory_audits"] == [
        {
            "source_incident_id": source_id,
            "tool": "select_query",
            "status": "completed",
            "text": "3 durable memory rows",
            "structured_content": {"row_count": 3},
        }
    ]
    managed_mcp = next(
        item for item in payload["tools_used"]
        if item["name"] == "cockroachdb-cloud-managed-mcp"
    )
    assert managed_mcp["status"] == "used"
    assert "test-secret" not in response.text


def test_create_rolls_back_when_embedding_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingEmbedder:
        def embed(self, _: str) -> list[float]:
            raise RuntimeError("embedding failed")

    monkeypatch.setattr(memory_module, "get_embedder", lambda _: FailingEmbedder())

    with pytest.raises(RuntimeError, match="embedding failed"):
        client.post(
            "/incidents",
            json={
                "title": "Atomic create failure",
                "service": "catalog",
                "symptoms": "This incident must not survive a failed embedding",
            },
        )

    incidents = client.get("/incidents")
    assert incidents.status_code == 200
    assert all(item["title"] != "Atomic create failure" for item in incidents.json())


def test_resolve_rolls_back_when_outcome_embedding_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post(
        "/incidents",
        json={
            "title": "Atomic resolution failure",
            "service": "catalog",
            "symptoms": "Resolution state must remain open if an outcome embedding fails",
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["id"]

    class FailOnSecondEmbedding:
        calls = 0

        def embed(self, _: str) -> list[float]:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("outcome embedding failed")
            return [0.0] * 512

    embedder = FailOnSecondEmbedding()
    monkeypatch.setattr(memory_module, "get_embedder", lambda _: embedder)

    with pytest.raises(RuntimeError, match="outcome embedding failed"):
        client.post(
            f"/incidents/{incident_id}/resolve",
            json={
                "resolution": "This resolution must roll back",
                "outcome": "This outcome must roll back",
            },
        )

    incident = client.get(f"/incidents/{incident_id}")
    assert incident.status_code == 200
    assert incident.json()["status"] == "open"
    assert incident.json()["resolution"] is None

    memories = client.get(f"/incidents/{incident_id}/memory")
    assert memories.status_code == 200
    assert [item["kind"] for item in memories.json()] == ["symptoms"]


def test_create_rolls_back_when_embedding_has_wrong_dimensions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ShortEmbedder:
        def embed(self, _: str) -> list[float]:
            return [1.0] * 511

    monkeypatch.setattr(memory_module, "get_embedder", lambda _: ShortEmbedder())

    with pytest.raises(StatementError, match="exactly 512"):
        client.post(
            "/incidents",
            json={
                "title": "Malformed embedding must not be stored",
                "service": "embedding-validation-create",
                "symptoms": "Reject a provider response with the wrong embedding dimensions",
            },
        )

    incidents = client.get("/incidents")
    assert incidents.status_code == 200
    assert all(item["service"] != "embedding-validation-create" for item in incidents.json())


def test_resolve_rolls_back_when_outcome_embedding_is_nonfinite(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post(
        "/incidents",
        json={
            "title": "Reject invalid outcome embedding",
            "service": "embedding-validation-resolve",
            "symptoms": "Keep the original incident state if the provider returns NaN",
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["id"]

    class InvalidSecondEmbedding:
        calls = 0

        def embed(self, _: str) -> list[float]:
            self.calls += 1
            return [float("nan") if self.calls == 2 else 1.0] * 512

    embedder = InvalidSecondEmbedding()
    monkeypatch.setattr(memory_module, "get_embedder", lambda _: embedder)

    with pytest.raises(StatementError, match="must be finite"):
        client.post(
            f"/incidents/{incident_id}/resolve",
            json={
                "resolution": "This resolution must roll back",
                "outcome": "This invalid outcome must roll back",
            },
        )

    incident = client.get(f"/incidents/{incident_id}")
    assert incident.status_code == 200
    assert incident.json()["status"] == "open"
    assert incident.json()["resolution"] is None
    memories = client.get(f"/incidents/{incident_id}/memory")
    assert memories.status_code == 200
    assert [item["kind"] for item in memories.json()] == ["symptoms"]


def test_bedrock_reasoner_receives_outcome_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved = client.post(
        "/incidents",
        json={
            "title": "Search workers overloaded",
            "service": "search",
            "symptoms": "Search workers are overloaded and requests are timing out",
        },
    )
    assert resolved.status_code == 201
    source_incident_id = resolved.json()["id"]
    result = client.post(
        f"/incidents/{source_incident_id}/resolve",
        json={
            "resolution": "Reduced batch concurrency",
            "outcome": "Worker utilization returned below 70 percent",
            "notes": "Observed for twenty minutes",
        },
    )
    assert result.status_code == 200

    current = client.post(
        "/incidents",
        json={
            "title": "Search request timeouts",
            "service": "search",
            "symptoms": "Search workers are overloaded and requests time out",
        },
    )
    assert current.status_code == 201

    captured: dict = {}

    class CapturingReasoner:
        def __init__(self, _):
            pass

        def summarize(self, incident_title: str, symptoms: str, recommendations: list[dict]) -> str:
            captured["incident_title"] = incident_title
            captured["symptoms"] = symptoms
            captured["recommendations"] = recommendations
            return "Grounded Bedrock summary"

    monkeypatch.setattr(agent_module, "BedrockReasoner", CapturingReasoner)
    monkeypatch.setattr(main_module.settings, "use_bedrock", True)

    response = client.post(f"/incidents/{current.json()['id']}/investigate")
    assert response.status_code == 200
    assert response.json()["provider"] == "amazon-bedrock"
    assert response.json()["summary"] == "Grounded Bedrock summary"

    recommendation = captured["recommendations"][0]
    assert recommendation["outcome"] == "Worker utilization returned below 70 percent"
    outcome_evidence = next(item for item in recommendation["evidence"] if item["kind"] == "outcome")
    assert outcome_evidence["incident_id"] == source_incident_id
    assert outcome_evidence["metadata_json"]["notes"] == "Observed for twenty minutes"
