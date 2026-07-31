import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import Base

logger = logging.getLogger(__name__)


def bootstrap_database(engine: Engine, settings: Settings) -> None:
    """Create a fresh schema and safely extend the original starter schema."""

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "incident_memories" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("incident_memories")}
    with engine.begin() as connection:
        if "service" not in columns:
            connection.execute(text("ALTER TABLE incident_memories ADD COLUMN service VARCHAR(120)"))
            connection.execute(
                text(
                    """
                    UPDATE incident_memories
                    SET service = (SELECT service FROM incidents WHERE incidents.id = incident_memories.incident_id)
                    WHERE service IS NULL
                    """
                )
            )
        if "embedding" not in columns:
            column_type = f"VECTOR({settings.embedding_dimensions})" if engine.dialect.name == "postgresql" else "TEXT"
            connection.execute(text(f"ALTER TABLE incident_memories ADD COLUMN embedding {column_type}"))

    if engine.dialect.name != "postgresql":
        if settings.require_cockroachdb:
            raise RuntimeError("REQUIRE_COCKROACHDB is enabled, but DATABASE_URL is not PostgreSQL/CockroachDB")
        return

    with engine.begin() as connection:
        version = str(connection.scalar(text("SELECT version()")))
        if "CockroachDB" not in version:
            if settings.require_cockroachdb:
                raise RuntimeError("REQUIRE_COCKROACHDB is enabled, but the server is not CockroachDB")
            logger.warning("PostgreSQL-compatible server is not identified as CockroachDB")
            return

    try:
        with engine.begin() as connection:
            vector_enabled = str(
                connection.scalar(text("SHOW CLUSTER SETTING feature.vector_index.enabled"))
            ).lower()
            if vector_enabled not in {"true", "on", "1"}:
                raise RuntimeError(
                    "CockroachDB distributed vector indexing is disabled; enable feature.vector_index.enabled"
                )
            indexes = connection.execute(text("SHOW INDEXES FROM incident_memories")).mappings().all()
            if not any(index["index_name"] == "incident_memory_embedding_idx" for index in indexes):
                connection.execute(text("SET sql_safe_updates = false"))
                connection.execute(
                    text(
                        """
                        CREATE VECTOR INDEX incident_memory_embedding_idx
                        ON incident_memories (service, embedding vector_cosine_ops)
                        """
                    )
                )
    except Exception:
        logger.exception("CockroachDB vector index could not be created")
        if settings.require_cockroachdb:
            raise


def database_status(engine: Engine, settings: Settings) -> dict[str, object]:
    backend = "sqlite-local"
    vector_search = "in-process cosine"
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            version = str(connection.scalar(text("SELECT version()")))
        backend = "cockroachdb" if "CockroachDB" in version else "postgresql-compatible"
        vector_search = "CockroachDB VECTOR cosine search"
    mcp_configured = bool(
        settings.use_cockroach_mcp
        and settings.cockroach_mcp_api_key
        and settings.cockroach_mcp_cluster_id
    )
    stack = {
        "competition_mode": settings.competition_mode,
        "cockroachdb": backend == "cockroachdb",
        "distributed_vector_indexing": backend == "cockroachdb",
        "managed_mcp": mcp_configured,
        "amazon_bedrock": settings.use_bedrock,
    }
    return {
        "database": backend,
        "memory": "durable incident events + 512-dimensional embeddings",
        "vector_search": vector_search,
        "embedding_provider": "Amazon Bedrock Titan Text Embeddings V2" if settings.use_bedrock else "local deterministic fallback",
        "reasoning_provider": "Amazon Bedrock Nova" if settings.use_bedrock else "local retrieval summary",
        "cockroachdb_tools": {
            "distributed_vector_indexing": backend == "cockroachdb",
            "managed_mcp_server": mcp_configured,
        },
        "competition_stack_configured": stack,
        "minimum_relevance": settings.minimum_relevance,
    }
