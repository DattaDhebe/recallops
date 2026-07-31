from types import SimpleNamespace

import pytest

from app.mcp_client import (
    MAX_AUDIT_LIMIT,
    CockroachDBMCPClient,
    MCPProtocolError,
    build_incident_memory_audit_query,
    build_select_query_arguments,
    normalize_call_tool_result,
)


INCIDENT_ID = "a15ddc42-5d66-4f60-9d9e-1c80ba3b4e3f"


def test_audit_query_is_single_bounded_select() -> None:
    query = build_incident_memory_audit_query(INCIDENT_ID.upper(), limit=17)

    assert query.startswith("SELECT id, incident_id, service, kind, content")
    assert query.upper().count("SELECT") == 1
    assert ";" not in query
    assert f"WHERE incident_id = '{INCIDENT_ID}'" in query
    assert query.endswith("LIMIT 17")
    assert "embedding" not in query


@pytest.mark.parametrize(
    "incident_id",
    [
        "not-a-uuid",
        f"{INCIDENT_ID}' OR TRUE --",
        "",
        None,
    ],
)
def test_audit_query_rejects_invalid_incident_ids(incident_id: object) -> None:
    with pytest.raises(ValueError, match="valid UUID"):
        build_incident_memory_audit_query(incident_id)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, -1, MAX_AUDIT_LIMIT + 1, True, 1.5])
def test_audit_query_rejects_unbounded_limits(limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        build_incident_memory_audit_query(INCIDENT_ID, limit=limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("query_field", ["query", "sql", "statement", "sql_query"])
def test_select_arguments_map_common_query_names(query_field: str) -> None:
    schema = {
        "type": "object",
        "properties": {query_field: {"type": "string"}},
        "required": [query_field],
    }

    assert build_select_query_arguments(schema, "SELECT 1") == {
        query_field: "SELECT 1"
    }


def test_select_arguments_map_required_database_and_pagination() -> None:
    schema = {
        "type": "object",
        "properties": {
            "sqlQuery": {"type": "string"},
            "database_name": {"type": "string"},
            "maxRows": {"type": "integer"},
            "row_offset": {"type": "integer"},
        },
        "required": ["sqlQuery", "database_name", "maxRows", "row_offset"],
    }

    assert build_select_query_arguments(
        schema,
        "SELECT 1 LIMIT 9",
        database="recallops",
        limit=9,
    ) == {
        "sqlQuery": "SELECT 1 LIMIT 9",
        "database_name": "recallops",
        "maxRows": 9,
        "row_offset": 0,
    }


def test_select_arguments_fail_closed_for_unknown_required_fields() -> None:
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "tenant_token": {"type": "string"},
        },
        "required": ["query", "tenant_token"],
    }

    with pytest.raises(MCPProtocolError, match="tenant_token"):
        build_select_query_arguments(schema, "SELECT 1")


def test_normalization_preserves_text_and_structure_but_redacts_secrets() -> None:
    api_key = "service-account-key-123"
    result = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text=f"Authorization: Bearer {api_key}"),
            {"type": "text", "text": "password=hunter2 incident recovered"},
            {"type": "image", "data": "large-binary-payload"},
        ],
        structuredContent={
            "rows": [
                {
                    "kind": "resolution",
                    "content": f"rotated api_key={api_key}",
                    "metadata": {
                        "access_token": "another-secret",
                        "owner": "ops",
                    },
                }
            ]
        },
        isError=False,
    )

    normalized = normalize_call_tool_result(result, secrets=(api_key,))
    serialized = repr(normalized)

    assert normalized["is_error"] is False
    assert normalized["text"] == (
        "Authorization: [REDACTED]\n"
        "password=[REDACTED] incident recovered"
    )
    assert normalized["structured_content"]["rows"][0]["metadata"] == {
        "access_token": "[REDACTED]",
        "owner": "ops",
    }
    assert api_key not in serialized
    assert "hunter2" not in serialized
    assert "another-secret" not in serialized
    assert "large-binary-payload" not in serialized


def test_normalization_supports_snake_case_sdk_fields() -> None:
    result = {
        "content": [{"type": "text", "text": "one row"}],
        "structured_content": {"count": 1},
        "is_error": True,
    }

    assert normalize_call_tool_result(result) == {
        "is_error": True,
        "text": "one row",
        "structured_content": {"count": 1},
    }


def test_client_headers_scope_requests_and_repr_does_not_leak_key() -> None:
    api_key = "service-account-key-123"
    client = CockroachDBMCPClient(
        api_key=api_key,
        cluster_id="cluster-abc",
        database="recallops",
    )

    assert client._request_headers() == {
        "Authorization": f"Bearer {api_key}",
        "mcp-cluster-id": "cluster-abc",
    }
    assert api_key not in repr(client)


@pytest.mark.asyncio
async def test_tool_allowlist_rejects_write_tools_before_session_call() -> None:
    class Session:
        called = False

        async def call_tool(self, *_: object, **__: object) -> object:
            self.called = True
            return object()

    session = Session()
    with pytest.raises(MCPProtocolError, match="not allowlisted"):
        await CockroachDBMCPClient._call_allowed_tool(
            session,
            "insert_rows",
            {"statement": "INSERT INTO incident_memories VALUES (...)"},
        )
    assert session.called is False
