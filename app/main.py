import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent import investigate
from app.bootstrap import bootstrap_database, database_status
from app.config import get_settings
from app.db import engine, get_db
from app.memory import remember
from app.mcp_client import CockroachDBMCPClient, MCPClientError
from app.models import Incident, IncidentMemory
from app.schemas import AgentResponse, IncidentCreate, IncidentRead, MemoryRead, ResolutionRequest

settings = get_settings()
logger = logging.getLogger("recallops.http")
safe_request_id = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime_integrations()
    bootstrap_database(engine, settings)
    yield

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "An incident-response agent with durable CockroachDB vector memory, "
        "a Managed MCP audit trail, and Amazon Bedrock reasoning."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_request_id
        if safe_request_id.fullmatch(supplied_request_id)
        else str(uuid4())
    )
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "event": "http_request_failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
                separators=(",", ":"),
            )
        )
        raise
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        json.dumps(
            {
                "event": "http_request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
            separators=(",", ":"),
        )
    )
    return response


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and (not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key)):
        raise HTTPException(status_code=401, detail="A valid X-API-Key header is required")


@app.exception_handler(BotoCoreError)
@app.exception_handler(ClientError)
async def bedrock_error_handler(_, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": "Amazon Bedrock request failed", "error_type": type(exc).__name__},
    )


@app.get("/", include_in_schema=False)
def operator_console() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/system", tags=["observability"])
def system_status() -> dict[str, object]:
    return database_status(engine, settings)


@app.get("/ready", tags=["observability"])
def readiness() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(select(1)).scalar_one()
        status = database_status(engine, settings)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not-ready", "database": "unavailable"},
        )
    return JSONResponse(
        content={
            "status": "ready",
            "database": status["database"],
            "competition_stack_configured": status["competition_stack_configured"],
        }
    )


@app.post("/incidents", response_model=IncidentRead, status_code=201)
def create_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> Incident:
    incident = Incident(**payload.model_dump())
    try:
        db.add(incident)
        db.flush()
        remember(db, incident, "symptoms", payload.symptoms, settings, {"service": payload.service})
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(incident)
    return incident


@app.get("/incidents", response_model=list[IncidentRead])
def list_incidents(
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> list[Incident]:
    return list(db.scalars(select(Incident).order_by(Incident.created_at.desc())).all())


@app.get("/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> Incident:
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.post("/incidents/{incident_id}/resolve", response_model=IncidentRead)
def resolve_incident(
    incident_id: str,
    payload: ResolutionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> Incident:
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        incident.resolution = payload.resolution
        incident.status = "resolved"
        db.add(incident)
        remember(db, incident, "resolution", payload.resolution, settings, {"outcome": payload.outcome, "notes": payload.notes})
        remember(db, incident, "outcome", payload.outcome, settings, {"notes": payload.notes})
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(incident)
    return incident


@app.get("/incidents/{incident_id}/memory", response_model=list[MemoryRead])
def list_memory(
    incident_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> list[IncidentMemory]:
    if not db.get(Incident, incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    return list(db.scalars(select(IncidentMemory).where(IncidentMemory.incident_id == incident_id).order_by(IncidentMemory.created_at)).all())


@app.post("/incidents/{incident_id}/investigate", response_model=AgentResponse)
async def investigate_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> dict:
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    result = await run_in_threadpool(investigate, db, incident, settings)

    database_is_cockroach = database_status(engine, settings)["database"] == "cockroachdb"
    result["tools_used"] = [
        {
            "name": (
                "cockroachdb-distributed-vector-indexing"
                if database_is_cockroach
                else "local-vector-fallback"
            ),
            "purpose": "Retrieve semantically similar resolved incident memories",
            "status": "used" if database_is_cockroach else "fallback",
            "detail": None,
        }
    ]
    result["memory_audits"] = []

    recommendations = result["recommendations"]
    if settings.use_cockroach_mcp and recommendations:
        source_incident_id = recommendations[0]["incident_id"]
        client = CockroachDBMCPClient(
            api_key=settings.cockroach_mcp_api_key or "",
            cluster_id=settings.cockroach_mcp_cluster_id,
            database=settings.cockroach_mcp_database,
            endpoint=settings.cockroach_mcp_url,
            timeout_seconds=settings.cockroach_mcp_timeout_seconds,
        )
        try:
            audit = await client.audit_incident_memories(source_incident_id)
            audit_failed = bool(audit["is_error"])
            result["memory_audits"].append(
                {
                    "source_incident_id": source_incident_id,
                    "status": "failed" if audit_failed else "completed",
                    "text": audit["text"],
                    "structured_content": audit["structured_content"],
                }
            )
            result["tools_used"].append(
                {
                    "name": "cockroachdb-cloud-managed-mcp",
                    "purpose": "Read back the top recommendation's durable memory trail with select_query",
                    "status": "failed" if audit_failed else "used",
                    "detail": "The server returned an MCP tool error" if audit_failed else "select_query completed",
                }
            )
            if not audit_failed:
                result["summary"] += (
                    " The top recommendation's durable memory trail was independently read "
                    "through CockroachDB Cloud Managed MCP."
                )
        except (MCPClientError, ValueError):
            result["memory_audits"].append(
                {
                    "source_incident_id": source_incident_id,
                    "status": "failed",
                    "text": "CockroachDB MCP audit was unavailable.",
                    "structured_content": None,
                }
            )
            result["tools_used"].append(
                {
                    "name": "cockroachdb-cloud-managed-mcp",
                    "purpose": "Read back the top recommendation's durable memory trail with select_query",
                    "status": "failed",
                    "detail": "Audit unavailable; no MCP credentials or server details were exposed",
                }
            )
    elif settings.use_cockroach_mcp:
        result["tools_used"].append(
            {
                "name": "cockroachdb-cloud-managed-mcp",
                "purpose": "Read back the top recommendation's durable memory trail with select_query",
                "status": "skipped",
                "detail": "No recalled recommendation required an audit",
            }
        )

    result["tools_used"].append(
        {
            "name": "amazon-bedrock" if settings.use_bedrock else "local-summary-fallback",
            "purpose": "Summarize grounded recommendations without executing changes",
            "status": "used" if settings.use_bedrock else "fallback",
            "detail": settings.bedrock_model_id if settings.use_bedrock else None,
        }
    )
    return result
