import json
import math
import re
from collections import Counter

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.aws import get_embedder
from app.config import Settings
from app.models import Incident, IncidentMemory


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


def remember(
    db: Session,
    incident: Incident,
    kind: str,
    content: str,
    settings: Settings,
    metadata: dict | None = None,
) -> IncidentMemory:
    embedder = get_embedder(settings)
    infrastructure = json.dumps(incident.infrastructure or {}, sort_keys=True, separators=(",", ":"))
    embedding_text = (
        f"service: {incident.service}\n"
        f"title: {incident.title}\n"
        f"infrastructure: {infrastructure}\n"
        f"{kind}: {content}"
    )
    provenance = {
        **(metadata or {}),
        "embedding_provider": getattr(embedder, "provider", "unknown"),
        "embedding_model": (
            settings.bedrock_embedding_model_id if settings.use_bedrock else "local-hash-v1"
        ),
        "embedding_dimensions": settings.embedding_dimensions,
    }
    memory = IncidentMemory(
        incident_id=incident.id,
        service=incident.service,
        kind=kind,
        content=content,
        metadata_json=provenance,
        embedding=embedder.embed(embedding_text),
    )
    db.add(memory)
    db.flush()
    return memory


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_size = math.sqrt(sum(value * value for value in left))
    right_size = math.sqrt(sum(value * value for value in right))
    return numerator / (left_size * right_size) if left_size and right_size else 0.0


def _query_embedding(db: Session, incident: Incident, settings: Settings) -> list[float]:
    saved = db.scalar(
        select(IncidentMemory.embedding).where(
            IncidentMemory.incident_id == incident.id,
            IncidentMemory.kind == "symptoms",
        )
    )
    if saved:
        return saved
    return get_embedder(settings).embed(f"service: {incident.service}\ntitle: {incident.title}\nsymptoms: {incident.symptoms}")


def retrieve_similar(
    db: Session, incident: Incident, settings: Settings, limit: int = 5
) -> list[tuple[Incident, list[IncidentMemory], float]]:
    query_embedding = _query_embedding(db, incident, settings)
    if db.bind and db.bind.dialect.name == "postgresql":
        rows = db.execute(
            text(
                """
                SELECT memory.incident_id,
                       1 - (memory.embedding <=> CAST(:embedding AS VECTOR(512))) AS relevance
                FROM incident_memories AS memory
                JOIN incidents AS source ON source.id = memory.incident_id
                WHERE memory.service = :service
                  AND memory.kind = 'symptoms'
                  AND memory.incident_id != :incident_id
                  AND memory.embedding IS NOT NULL
                  AND source.status = 'resolved'
                  AND source.resolution IS NOT NULL
                  AND 1 - (memory.embedding <=> CAST(:embedding AS VECTOR(512))) >= :minimum_relevance
                ORDER BY memory.embedding <=> CAST(:embedding AS VECTOR(512))
                LIMIT :limit
                """
            ),
            {
                "embedding": str(query_embedding),
                "service": incident.service,
                "incident_id": incident.id,
                "minimum_relevance": settings.minimum_relevance,
                "limit": limit,
            },
        ).all()
        scored_ids = [(row.incident_id, max(0.0, float(row.relevance))) for row in rows]
        scored = []
        for incident_id, score in scored_ids:
            candidate = db.get(Incident, incident_id)
            if candidate is None:
                continue
            memories = list(db.scalars(select(IncidentMemory).where(IncidentMemory.incident_id == incident_id)).all())
            scored.append((candidate, memories, score))
        return scored

    candidates = db.scalars(
        select(Incident).where(
            Incident.id != incident.id,
            Incident.service == incident.service,
            Incident.status == "resolved",
            Incident.resolution.is_not(None),
        )
    ).all()
    query_tokens = _tokens(f"{incident.title} {incident.symptoms} {incident.service}")
    scored: list[tuple[Incident, list[IncidentMemory], float]] = []
    for candidate in candidates:
        memories = db.scalars(
            select(IncidentMemory).where(IncidentMemory.incident_id == candidate.id)
        ).all()
        corpus = " ".join([candidate.title, candidate.symptoms, candidate.resolution or ""] + [memory.content for memory in memories])
        overlap = query_tokens & _tokens(corpus)
        symptom_memory = next((memory for memory in memories if memory.kind == "symptoms" and memory.embedding), None)
        vector_score = _cosine(query_embedding, symptom_memory.embedding) if symptom_memory else 0.0
        lexical_score = len(overlap) / max(len(query_tokens), 1)
        score = (vector_score * 0.7) + (lexical_score * 0.3)
        if score >= settings.minimum_relevance:
            scored.append((candidate, memories, score))
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[:limit]


def explain_matches(incident: Incident, candidate: Incident, memories: list[IncidentMemory]) -> list[str]:
    query_counts = Counter(_tokens(f"{incident.title} {incident.symptoms}"))
    corpus = f"{candidate.title} {candidate.symptoms} {candidate.resolution or ''} " + " ".join(memory.content for memory in memories)
    return [token for token, _ in query_counts.most_common() if token in _tokens(corpus)][:6]
