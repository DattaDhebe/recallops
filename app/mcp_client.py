"""Read-only access to incident memory through CockroachDB Cloud MCP.

The runtime dependency on the official MCP SDK is intentionally imported only
when a request is made.  This keeps the application's local fallback usable
when the optional integration is not installed while still using the official
v1 ``ClientSession`` + Streamable HTTP client lifecycle in production.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx


COCKROACHDB_CLOUD_MCP_ENDPOINT = "https://cockroachlabs.cloud/mcp"
SELECT_QUERY_TOOL = "select_query"
ALLOWED_TOOLS = frozenset({SELECT_QUERY_TOOL})
DEFAULT_AUDIT_LIMIT = 50
MAX_AUDIT_LIMIT = 100

_QUERY_ARGUMENT_ALIASES = (
    "query",
    "sql",
    "statement",
    "sql_query",
    "select_query",
)
_DATABASE_ARGUMENT_ALIASES = ("database", "database_name", "db")
_LIMIT_ARGUMENT_ALIASES = ("limit", "row_limit", "max_rows")
_OFFSET_ARGUMENT_ALIASES = ("offset", "row_offset")
_SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,62}$")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_AUTHORIZATION_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>[\"']?authorization[\"']?\s*[:=]\s*)"
    r"(?:Bearer\s+)?(?P<value>[^,\r\n;}\]]+)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>[\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|secret|cookie)[\"']?\s*[:=]\s*)"
    r"(?P<value>[\"'][^\"']*[\"']|[^\s,;}\]]+)"
)
_POSTGRES_PASSWORD = re.compile(
    r"(?i)\b(?P<prefix>postgres(?:ql)?://[^:\s/@]+:)(?P<password>[^@\s/]+)(?P<suffix>@)"
)
_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credentials",
        "databaseurl",
        "dsn",
        "password",
        "refreshtoken",
        "secret",
        "setcookie",
        "token",
        "accesstoken",
        "connectionstring",
    }
)
_SENSITIVE_KEY_SUFFIXES = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "credential",
    "credentials",
    "connectionstring",
    "databaseurl",
)


class MCPClientError(RuntimeError):
    """Base error for safe, user-facing MCP failures."""


class MCPDependencyError(MCPClientError):
    """Raised when the optional official MCP v1 SDK is unavailable."""


class MCPProtocolError(MCPClientError):
    """Raised when a server does not expose the expected read-only contract."""


def _validated_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if not 1 <= limit <= MAX_AUDIT_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_AUDIT_LIMIT}")
    return limit


def _validated_uuid(value: str | UUID) -> str:
    try:
        parsed = value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("incident_id must be a valid UUID") from exc
    return str(parsed)


def build_incident_memory_audit_query(
    incident_id: str | UUID,
    *,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> str:
    """Build the sole SQL statement this client is permitted to execute.

    UUID canonicalization and a hard row cap make interpolation safe here.  No
    caller-controlled SQL, table name, column name, ordering, or predicate is
    accepted.
    """

    canonical_id = _validated_uuid(incident_id)
    bounded_limit = _validated_limit(limit)
    return (
        "SELECT id, incident_id, service, kind, content, metadata_json, created_at "
        "FROM incident_memories "
        f"WHERE incident_id = '{canonical_id}' "
        "ORDER BY created_at ASC, id ASC "
        f"LIMIT {bounded_limit}"
    )


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _find_schema_property(
    properties: Mapping[str, Any], aliases: Sequence[str]
) -> str | None:
    by_normalized_name = {
        _normalized_name(name): name
        for name in properties
        if isinstance(name, str)
    }
    for alias in aliases:
        match = by_normalized_name.get(_normalized_name(alias))
        if match is not None:
            return match
    return None


def _accepts_type(definition: Any, expected: str) -> bool:
    if not isinstance(definition, Mapping) or "type" not in definition:
        return True
    declared = definition["type"]
    if isinstance(declared, str):
        return declared == expected
    if isinstance(declared, Sequence) and not isinstance(declared, (str, bytes)):
        return expected in declared
    return False


def build_select_query_arguments(
    input_schema: Mapping[str, Any],
    query: str,
    *,
    database: str | None = None,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> dict[str, Any]:
    """Map the fixed audit query to the server-advertised tool schema.

    The managed service can evolve argument spelling independently of this
    application.  We therefore inspect its JSON Schema but only recognize a
    small set of semantically unambiguous names.  Unknown required arguments
    fail closed rather than being guessed.
    """

    if not isinstance(input_schema, Mapping):
        raise MCPProtocolError("select_query advertised an invalid input schema")
    properties = input_schema.get("properties")
    if not isinstance(properties, Mapping):
        raise MCPProtocolError("select_query input schema has no properties")

    query_name = _find_schema_property(properties, _QUERY_ARGUMENT_ALIASES)
    if query_name is None or not _accepts_type(properties[query_name], "string"):
        raise MCPProtocolError("select_query schema has no supported SQL argument")

    bounded_limit = _validated_limit(limit)
    arguments: dict[str, Any] = {query_name: query}
    supplied_names = {query_name}

    database_name = _find_schema_property(properties, _DATABASE_ARGUMENT_ALIASES)
    if database_name is not None and database is not None:
        if not _SAFE_DATABASE_NAME.fullmatch(database):
            raise ValueError("database must be a simple CockroachDB database name")
        if not _accepts_type(properties[database_name], "string"):
            raise MCPProtocolError("select_query database argument is not a string")
        arguments[database_name] = database
        supplied_names.add(database_name)

    limit_name = _find_schema_property(properties, _LIMIT_ARGUMENT_ALIASES)
    required = input_schema.get("required", ())
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        raise MCPProtocolError("select_query schema has an invalid required list")
    required_names = {name for name in required if isinstance(name, str)}

    # The SQL statement already has the authoritative LIMIT.  A required tool
    # limit is repeated only for servers that model pagination separately.
    if limit_name is not None and limit_name in required_names:
        if not _accepts_type(properties[limit_name], "integer"):
            raise MCPProtocolError("select_query limit argument is not an integer")
        arguments[limit_name] = bounded_limit
        supplied_names.add(limit_name)

    offset_name = _find_schema_property(properties, _OFFSET_ARGUMENT_ALIASES)
    if offset_name is not None and offset_name in required_names:
        if not _accepts_type(properties[offset_name], "integer"):
            raise MCPProtocolError("select_query offset argument is not an integer")
        arguments[offset_name] = 0
        supplied_names.add(offset_name)

    missing = sorted(required_names - supplied_names)
    if missing:
        # Do not echo schema descriptions or values, which may be server
        # controlled.  Argument names alone are sufficient for integration.
        raise MCPProtocolError(
            "select_query requires unsupported arguments: " + ", ".join(missing)
        )
    return arguments


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = _normalized_name(key)
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def _redact_text(value: str, secrets: Sequence[str]) -> str:
    redacted = value
    redacted = _AUTHORIZATION_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]", redacted
    )
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]", redacted
    )
    redacted = _POSTGRES_PASSWORD.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]{match.group('suffix')}",
        redacted,
    )
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _json_safe(value: Any, secrets: Sequence[str]) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, (UUID, date, datetime, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return "[binary content omitted]"
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _is_sensitive_key(key)
            else _json_safe(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, Sequence):
        return [_json_safe(item, secrets) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclasses.asdict(value), secrets)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json", by_alias=True), secrets)
        except TypeError:
            return _json_safe(model_dump(), secrets)
    return _redact_text(str(value), secrets)


def normalize_call_tool_result(
    result: Any,
    *,
    secrets: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a stable, JSON-safe view of an MCP ``CallToolResult``.

    Only text content and structured content are returned.  Images, embedded
    resources, and raw SDK objects are deliberately omitted from this database
    audit path.  Known credential-shaped values are recursively redacted.
    """

    text_parts: list[str] = []
    content = _field(result, "content", default=())
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        for block in content:
            block_type = _field(block, "type")
            text_value = _field(block, "text")
            if block_type in (None, "text") and isinstance(text_value, str):
                text_parts.append(_redact_text(text_value, secrets))

    structured = _field(
        result,
        "structuredContent",
        "structured_content",
        default=None,
    )
    is_error = bool(_field(result, "isError", "is_error", default=False))
    return {
        "is_error": is_error,
        "text": "\n".join(text_parts),
        "structured_content": _json_safe(structured, secrets),
    }


def _load_mcp_v1() -> tuple[Any, Any]:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise MCPDependencyError(
            'CockroachDB MCP requires the optional dependency "mcp>=1.24,<2"'
        ) from exc
    return ClientSession, streamable_http_client


def _input_schema(tool: Any) -> Mapping[str, Any]:
    schema = _field(tool, "inputSchema", "input_schema")
    if not isinstance(schema, Mapping):
        raise MCPProtocolError("select_query advertised an invalid input schema")
    return schema


def _select_query_tool(list_tools_result: Any) -> Any:
    tools = _field(list_tools_result, "tools", default=())
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        raise MCPProtocolError("MCP server returned an invalid tool list")
    for tool in tools:
        if _field(tool, "name") == SELECT_QUERY_TOOL:
            return tool
    raise MCPProtocolError("MCP server does not expose the required select_query tool")


class CockroachDBMCPClient:
    """Narrow, read-only CockroachDB Cloud MCP client for incident audits."""

    __slots__ = (
        "_api_key",
        "_cluster_id",
        "_database",
        "_endpoint",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        api_key: str,
        cluster_id: str | None = None,
        database: str | None = None,
        endpoint: str = COCKROACHDB_CLOUD_MCP_ENDPOINT,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key or api_key != api_key.strip() or _CONTROL_CHARACTER.search(api_key):
            raise ValueError("api_key must be a non-empty value without whitespace padding")
        if cluster_id is not None and (
            not cluster_id.strip() or _CONTROL_CHARACTER.search(cluster_id)
        ):
            raise ValueError("cluster_id must be non-empty and contain no control characters")
        if database is not None and not _SAFE_DATABASE_NAME.fullmatch(database):
            raise ValueError("database must be a simple CockroachDB database name")
        parsed_endpoint = urlparse(endpoint)
        if (
            parsed_endpoint.scheme != "https"
            or not parsed_endpoint.netloc
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise ValueError("endpoint must be an HTTPS URL without credentials, query, or fragment")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._api_key = api_key
        self._cluster_id = cluster_id.strip() if cluster_id is not None else None
        self._database = database
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(endpoint={self._endpoint!r}, "
            f"cluster_id={self._cluster_id!r}, database={self._database!r})"
        )

    def _request_headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._cluster_id is not None:
            headers["mcp-cluster-id"] = self._cluster_id
        return headers

    @staticmethod
    async def _call_allowed_tool(
        session: Any,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> Any:
        if tool_name not in ALLOWED_TOOLS:
            raise MCPProtocolError(f"MCP tool is not allowlisted: {tool_name}")
        return await session.call_tool(tool_name, arguments=dict(arguments))

    async def audit_incident_memories(
        self,
        incident_id: str | UUID,
        *,
        limit: int = DEFAULT_AUDIT_LIMIT,
    ) -> dict[str, Any]:
        """Read a bounded incident-memory audit trail through Managed MCP."""

        query = build_incident_memory_audit_query(incident_id, limit=limit)
        ClientSession, streamable_http_client = _load_mcp_v1()

        try:
            # The SDK transport receives an explicit httpx client so auth and
            # cluster scoping are attached to every protocol request.
            async with httpx.AsyncClient(
                headers=self._request_headers(),
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
            ) as http_client:
                async with streamable_http_client(
                    self._endpoint,
                    http_client=http_client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tool = _select_query_tool(await session.list_tools())
                        arguments = build_select_query_arguments(
                            _input_schema(tool),
                            query,
                            database=self._database,
                            limit=limit,
                        )
                        result = await self._call_allowed_tool(
                            session,
                            SELECT_QUERY_TOOL,
                            arguments,
                        )
        except MCPClientError:
            raise
        except Exception as exc:
            safe_detail = _redact_text(str(exc), (self._api_key,))
            message = "CockroachDB MCP audit request failed"
            if safe_detail:
                message = f"{message}: {safe_detail}"
            raise MCPClientError(message) from None

        return normalize_call_tool_result(result, secrets=(self._api_key,))


def result_as_json(result: Mapping[str, Any]) -> str:
    """Serialize a normalized result for logs or API responses."""

    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
