from sqlalchemy.orm import Session

from app.aws import BedrockReasoner
from app.config import Settings
from app.memory import explain_matches, retrieve_similar
from app.models import Incident, IncidentMemory


def _evidence_payload(memories: list[IncidentMemory]) -> list[dict]:
    ordered = sorted(
        memories,
        key=lambda memory: (
            memory.created_at.isoformat() if memory.created_at else "",
            memory.id,
        ),
    )
    return [
        {
            "memory_id": memory.id,
            "incident_id": memory.incident_id,
            "kind": memory.kind,
            "content": memory.content,
            "metadata_json": memory.metadata_json,
            "created_at": memory.created_at.isoformat() if memory.created_at else None,
        }
        for memory in ordered
    ]


def investigate(db: Session, incident: Incident, settings: Settings) -> dict:
    matches = retrieve_similar(db, incident, settings)
    recommendations = []
    for candidate, memories, score in matches:
        evidence = _evidence_payload(memories)
        outcomes = [item for item in evidence if item["kind"] == "outcome"]
        recommendations.append({
            "incident_id": candidate.id,
            "title": candidate.title,
            "service": candidate.service,
            "status": candidate.status,
            "relevance": round(score, 3),
            "resolution": candidate.resolution,
            "outcome": outcomes[-1]["content"] if outcomes else None,
            "matched_memory": explain_matches(incident, candidate, memories),
            "evidence": evidence,
        })
    if recommendations and settings.use_bedrock:
        summary = BedrockReasoner(settings).summarize(incident.title, incident.symptoms, recommendations)
        provider = "amazon-bedrock"
    elif recommendations:
        best = recommendations[0]
        summary = f"Found {len(recommendations)} related incident(s). Highest match: {best['title']} ({best['relevance']:.0%} similarity score). Review its recorded resolution and outcome before acting."
        provider = "local-retrieval"
    else:
        summary = "No related incident memory was found for this service. Capture the investigation outcome to improve future recommendations."
        provider = "local-retrieval"
    return {"incident_id": incident.id, "summary": summary, "recommendations": recommendations, "provider": provider}
